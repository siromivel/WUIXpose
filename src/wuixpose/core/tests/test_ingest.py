import io
import json
import logging
from datetime import date

import pytest
from django.contrib.gis.geos import GEOSGeometry
from django.core.management import CommandError, call_command
from django.utils import timezone

from wuixpose.core.ingest import arcgis, boulder
from wuixpose.core.ingest.geometry import UnreadableGeometry, multipolygon_from_geojson
from wuixpose.core.models import Address, RejectedFeature, Structure, Tract
from wuixpose.core.models.tracts import TractIdentifier

from .factories import address_props, box, feature, multipolygon, point_feature


class FakeServer:
    """Serves pages of features the way an ArcGIS query endpoint does, recording each request."""

    def __init__(self, features, page_size):
        self.features = features
        self.page_size = page_size
        self.requests = []

    def __call__(self, url, params):
        self.requests.append((url, params))
        offset = int(params["resultOffset"])
        page = self.features[offset : offset + self.page_size]
        return {
            "type": "FeatureCollection",
            "features": page,
            "properties": {"exceededTransferLimit": offset + self.page_size < len(self.features)},
        }


# ArcGIS client


def test_iter_features_pages_until_server_reports_no_more():
    features = [feature({"PARCEL_NO": str(i)}, box(0, 0, 1, 1)) for i in range(5)]
    server = FakeServer(features, page_size=2)

    got = list(arcgis.iter_features("https://gis.example/Layer/0", page_size=2, fetch=server))

    assert [f["properties"]["PARCEL_NO"] for f in got] == ["0", "1", "2", "3", "4"]
    assert [p["resultOffset"] for _, p in server.requests] == ["0", "2", "4"]
    url, params = server.requests[0]
    assert url == "https://gis.example/Layer/0/query"
    assert params["outSR"] == "4326"
    assert params["orderByFields"] == "OBJECTID"
    assert "geometry" not in params


def test_iter_features_sends_bbox_as_envelope():
    server = FakeServer([], page_size=10)

    list(arcgis.iter_features("https://gis.example/Layer/0", bbox=(-105.5, 40.0, -105.3, 40.1), fetch=server))

    _, params = server.requests[0]
    assert params["geometry"] == "-105.5,40.0,-105.3,40.1"
    assert params["geometryType"] == "esriGeometryEnvelope"
    assert params["inSR"] == "4326"


def test_fetch_json_raises_on_arcgis_error_body(monkeypatch):
    body = json.dumps({"error": {"code": 400, "message": "Invalid query"}}).encode()
    monkeypatch.setattr(arcgis.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(body))

    with pytest.raises(arcgis.ArcGISError, match="Invalid query"):
        arcgis.fetch_json("https://gis.example/Layer/0/query", {})


# Geometry cleanup


def test_bowtie_polygon_becomes_valid_multipolygon():
    bowtie = {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]]}

    geom = multipolygon_from_geojson(bowtie)

    assert geom is not None
    assert geom.valid
    assert geom.geom_type == "MultiPolygon"
    assert len(geom) == 2


def test_non_polygonal_geometry_is_dropped():
    assert multipolygon_from_geojson({"type": "LineString", "coordinates": [[0, 0], [1, 1]]}) is None
    assert multipolygon_from_geojson(None) is None


UNCLOSED_RING = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1]]]}


@pytest.mark.parametrize(
    "geometry",
    [
        pytest.param(UNCLOSED_RING, id="unclosed-ring"),
        pytest.param({"type": "Polygon", "coordinates": None}, id="null-coordinates"),
        pytest.param({"type": "Bogus", "coordinates": []}, id="unknown-type"),
    ],
)
def test_unreadable_geometry_raises_typed_error(geometry):
    with pytest.raises(UnreadableGeometry):
        multipolygon_from_geojson(geometry)


def test_heights_are_dropped():
    ring = [[0, 0, 5], [1, 0, 5], [1, 1, 5], [0, 1, 5], [0, 0, 5]]

    geom = multipolygon_from_geojson({"type": "Polygon", "coordinates": [ring]})

    assert geom is not None
    assert not geom.hasz


# Loading tracts


def current_apns():
    return dict(TractIdentifier.objects.filter(tracked_to__isnull=True).values_list("value", "tract_id"))


@pytest.mark.django_db
def test_load_tracts_creates_tract_and_apn_per_parcel():
    result = boulder.load_tracts(
        [
            feature({"PARCEL_NO": "146100000001"}, box(0, 0, 0.001, 0.001)),
            feature({"PARCEL_NO": "146100000002"}, box(0.001, 0, 0.002, 0.001)),
            feature({"PARCEL_NO": None}, box(0, 0, 0.001, 0.001)),
            feature({"PARCEL_NO": "146100000003"}, [[0, 0], [0, 0], [0, 0], [0, 0]]),
        ]
    )

    assert (result.created, result.updated, result.skipped) == (2, 0, 2)
    ids = TractIdentifier.objects.order_by("value")
    assert [(i.scheme, i.county_fips, i.value) for i in ids] == [
        ("county_apn", "08013", "146100000001"),
        ("county_apn", "08013", "146100000002"),
    ]


@pytest.mark.django_db
def test_load_tracts_merges_features_sharing_a_parcel_number():
    boulder.load_tracts(
        [
            feature({"PARCEL_NO": "146100000001"}, box(0, 0, 0.001, 0.001)),
            feature({"PARCEL_NO": "146100000001"}, box(0.002, 0, 0.003, 0.001)),
        ]
    )

    tract = Tract.objects.get()
    assert len(tract.geom) == 2


@pytest.mark.django_db
def test_reloading_tracts_updates_geometry_in_place():
    boulder.load_tracts([feature({"PARCEL_NO": "146100000001"}, box(0, 0, 0.001, 0.001))])
    before = current_apns()

    result = boulder.load_tracts([feature({"PARCEL_NO": "146100000001"}, box(0, 0, 0.002, 0.001))])

    assert (result.created, result.updated) == (0, 1)
    assert current_apns() == before
    tract = Tract.objects.get()
    assert tract.geom.equals(multipolygon(box(0, 0, 0.002, 0.001)))


@pytest.mark.django_db
def test_new_identifiers_are_tracked_from_the_load_date():
    boulder.load_tracts([feature({"PARCEL_NO": "A"}, box(0, 0, 0.001, 0.001))], as_of=date(2026, 10, 5))
    boulder.load_tracts([feature({"PARCEL_NO": "B"}, box(0.001, 0, 0.002, 0.001))])

    tracked_from = dict(TractIdentifier.objects.values_list("value", "tracked_from"))
    assert tracked_from == {"A": date(2026, 10, 5), "B": timezone.localdate()}


@pytest.mark.django_db
def test_reloading_tracts_keeps_identifier_tracked_from():
    boulder.load_tracts([feature({"PARCEL_NO": "A"}, box(0, 0, 0.001, 0.001))], as_of=date(2026, 10, 5))

    boulder.load_tracts([feature({"PARCEL_NO": "A"}, box(0, 0, 0.002, 0.001))], as_of=date(2026, 10, 12))

    assert TractIdentifier.objects.get().tracked_from == date(2026, 10, 5)


# Loading structures


@pytest.mark.django_db
def test_load_structures_upserts_by_county_structure_id():
    boulder.load_structures([feature({"StructureID": "1N7116110001"}, box(0, 0, 0.0001, 0.0001))])
    first = Structure.objects.get()

    result = boulder.load_structures(
        [
            feature({"StructureID": "1N7116110001"}, box(0, 0, 0.0002, 0.0001)),
            feature({"StructureID": "1N7116110002"}, box(0.0005, 0, 0.0006, 0.0001)),
        ]
    )

    assert (result.created, result.updated) == (1, 1)
    first.refresh_from_db()
    assert first.source == Structure.Source.BOCO_FOOTPRINTS
    assert first.geom.equals(multipolygon(box(0, 0, 0.0002, 0.0001)))


@pytest.mark.django_db
def test_unusable_features_are_skipped_and_recorded(caplog):
    caplog.set_level(logging.INFO, logger="wuixpose.core.ingest.rejects")
    features = [
        feature({"StructureID": "good"}, box(0, 0, 0.0001, 0.0001)),
        {"type": "Feature", "geometry": UNCLOSED_RING, "properties": {"StructureID": "unclosed"}},
        feature({"StructureID": "flat"}, [[0, 0], [0, 0], [0, 0], [0, 0]]),
        feature({"StructureID": None}, box(0.0005, 0, 0.0006, 0.0001)),
    ]

    result = boulder.load_structures(features)

    assert (result.created, result.skipped) == (1, 3)
    assert list(Structure.objects.values_list("source_id", flat=True)) == ["good"]
    rows = {r.source_id: r for r in RejectedFeature.objects.all()}
    assert {sid: r.reason for sid, r in rows.items()} == {
        "unclosed": RejectedFeature.Reason.UNREADABLE_GEOMETRY,
        "flat": RejectedFeature.Reason.NOT_POLYGONAL,
        None: RejectedFeature.Reason.MISSING_ID,
    }
    assert rows["unclosed"].layer == RejectedFeature.Layer.BOCO_FOOTPRINTS
    assert rows["unclosed"].feature == features[1]
    assert rows["unclosed"].detail
    (warning,) = [r for r in caplog.records if r.name == "wuixpose.core.ingest.rejects" and r.levelno == logging.WARNING]
    assert "unclosed" in warning.getMessage()


@pytest.mark.django_db
def test_rejecting_the_same_feature_again_updates_its_row():
    bad = {"type": "Feature", "geometry": UNCLOSED_RING, "properties": {"PARCEL_NO": "A"}}
    boulder.load_tracts([bad, bad])
    first = RejectedFeature.objects.get()

    boulder.load_tracts([bad])

    again = RejectedFeature.objects.get()
    assert again.first_seen_at == first.first_seen_at
    assert again.last_seen_at > first.last_seen_at


# Structure-to-tract assignment


@pytest.mark.django_db
def test_structures_are_assigned_to_the_tract_holding_their_footprint():
    boulder.load_tracts(
        [
            feature({"PARCEL_NO": "A"}, box(0, 0, 0.001, 0.001)),
            feature({"PARCEL_NO": "B"}, box(0.001, 0, 0.002, 0.001)),
        ]
    )
    boulder.load_structures(
        [
            feature({"StructureID": "inside-a"}, box(0.0001, 0.0001, 0.0002, 0.0002)),
            # 95% on A, poking 5% over the lot line onto B.
            feature({"StructureID": "mostly-a"}, box(0.00081, 0.0001, 0.00101, 0.0002)),
            # Split evenly across the line: no single tract.
            feature({"StructureID": "straddles"}, box(0.0009, 0.0005, 0.0011, 0.0006)),
            # Not on any tract.
            feature({"StructureID": "outside"}, box(0.01, 0.01, 0.0101, 0.0101)),
        ]
    )
    apns = current_apns()

    result = boulder.assign_structure_tracts()

    tract_of = dict(Structure.objects.values_list("source_id", "tract_id"))
    assert tract_of == {"inside-a": apns["A"], "mostly-a": apns["A"], "straddles": None, "outside": None}
    assert result.changed == 2
    assert boulder.assign_structure_tracts().changed == 0


# Management command


@pytest.mark.django_db
def test_ingest_command_loads_all_layers(monkeypatch):
    seen_bbox = []

    def fake_parcels(bbox, **kwargs):
        seen_bbox.append(bbox)
        return [feature({"PARCEL_NO": "A"}, box(0, 0, 0.001, 0.001))]

    def fake_footprints(bbox, **kwargs):
        return [feature({"StructureID": "S1"}, box(0.0001, 0.0001, 0.0002, 0.0002))]

    def fake_addresses(bbox, **kwargs):
        return [point_feature(address_props("1", "12", "MAIN", "A"), 0.0005, 0.0005)]

    monkeypatch.setattr(boulder, "fetch_parcels", fake_parcels)
    monkeypatch.setattr(boulder, "fetch_footprints", fake_footprints)
    monkeypatch.setattr(boulder, "fetch_addresses", fake_addresses)
    out = io.StringIO()

    call_command("ingest_boulder", "--bbox=-105.5,40.0,-105.3,40.1", stdout=out)

    assert seen_bbox == [(-105.5, 40.0, -105.3, 40.1)]
    structure = Structure.objects.get()
    assert structure.tract == Tract.objects.get()
    assert Address.objects.get().tract == Tract.objects.get()
    assert "1 structure-tract assignments changed" in out.getvalue()
    assert "3 zones built or redrawn" in out.getvalue()
    assert "1 address-tract links changed" in out.getvalue()


def test_ingest_command_rejects_malformed_bbox():
    with pytest.raises(CommandError, match="--bbox"):
        call_command("ingest_boulder", "--bbox=1,2,3")


def test_geojson_coordinates_are_lon_lat():
    # Guards the axis order assumption the whole pipeline rests on.
    geom = multipolygon_from_geojson({"type": "Polygon", "coordinates": [box(0, 0, 0.001, 0.001)]})
    assert geom is not None
    assert GEOSGeometry(geom.centroid).x == pytest.approx(-105.3995)
