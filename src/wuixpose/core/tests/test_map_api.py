import math

import mapbox_vector_tile
import pytest
from django.urls import reverse

from wuixpose.core import tiles, zones
from wuixpose.core.ingest import boulder
from wuixpose.core.models import Structure, Tract, Zone

from .factories import ORIGIN, address_props, box, feature, point_feature


def tile_for(lon: float, lat: float, z: int) -> tuple[int, int, int]:
    """The XYZ (slippy map) tile containing a point."""
    n = 2**z
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return z, x, y


@pytest.fixture
def loaded():
    """Two adjacent ~85 m x 110 m lots, with one house on the first."""
    boulder.load_tracts(
        [
            feature({"PARCEL_NO": "146100000001"}, box(0, 0, 0.001, 0.001)),
            feature({"PARCEL_NO": "146100000002"}, box(0.001, 0, 0.002, 0.001)),
        ]
    )
    boulder.load_structures([feature({"StructureID": "1N7116110001"}, box(0.0002, 0.0002, 0.0004, 0.0003))])
    boulder.load_addresses(
        [
            point_feature(address_props("2", "10", "GOLD RUN", "146100000001", STREETTYPE="RD"), 0.0003, 0.0002),
            point_feature(address_props("1", "9", "GOLD RUN", "146100000001", STREETTYPE="RD"), 0.0003, 0.0003),
            point_feature(address_props("4", "10", "GOLD RUN", "146100000001", STREETTYPE="RD", UNIT="10"), 0.0003, 0.0002),
            point_feature(address_props("3", "10", "GOLD RUN", "146100000001", STREETTYPE="RD", UNIT="9"), 0.0003, 0.0002),
        ]
    )
    boulder.assign_structure_tracts()
    zones.build_zones()
    boulder.link_address_tracts()
    return {
        "tract": Tract.objects.get(identifiers__value="146100000001"),
        "structure": Structure.objects.get(),
    }


def get_tile(client, layer, z, x, y):
    return client.get(reverse("tile", kwargs={"layer": layer, "z": z, "x": x, "y": y}))


# Vector tiles


@pytest.mark.django_db
def test_tract_tile_carries_ids_and_apns(client, loaded):
    response = get_tile(client, "tracts", *tile_for(*ORIGIN, 15))

    assert response.status_code == 200
    assert response["Content-Type"] == "application/vnd.mapbox-vector-tile"
    layer = mapbox_vector_tile.decode(response.content)["tracts"]
    props = sorted((f["id"], f["properties"]["apn"]) for f in layer["features"])
    assert props == sorted((t.pk, t.identifiers.get().value) for t in Tract.objects.all())


@pytest.mark.django_db
def test_structure_tile_carries_tract_id(client, loaded):
    response = get_tile(client, "structures", *tile_for(*ORIGIN, 15))

    (feat,) = mapbox_vector_tile.decode(response.content)["structures"]["features"]
    assert feat["id"] == loaded["structure"].pk
    assert feat["properties"]["tract_id"] == loaded["tract"].pk


@pytest.mark.django_db
def test_zone_tile_carries_the_ring_and_whose_it_is(client, loaded):
    structure = loaded["structure"]
    # Rings drawn under earlier rules are kept, but not served.
    Zone.objects.create(structure=structure, ring_key="hiz_0_5", rule_version=0, geom=structure.geom)

    response = get_tile(client, "zones", *tile_for(*ORIGIN, 15))

    features = mapbox_vector_tile.decode(response.content)["zones"]["features"]
    current = structure.zones.filter(rule_version=zones.RULE_VERSION)
    assert sorted(f["id"] for f in features) == sorted(z.pk for z in current)
    assert sorted(f["properties"]["ring_key"] for f in features) == sorted(ring.key for ring in zones.RINGS)
    for feat in features:
        assert feat["properties"]["structure_id"] == structure.pk
        assert feat["properties"]["tract_id"] == loaded["tract"].pk


@pytest.mark.django_db
def test_tile_away_from_data_is_empty(client, loaded):
    assert get_tile(client, "tracts", *tile_for(-100.0, 35.0, 15)).status_code == 204


@pytest.mark.django_db
def test_tiles_below_layer_min_zoom_are_empty(client, loaded):
    assert get_tile(client, "structures", *tile_for(*ORIGIN, 12)).status_code == 204


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("layer", "z", "x", "y"),
    [("roads", 15, 0, 0), ("tracts", 15, 2**15, 0), ("tracts", 17, 0, 0)],
)
def test_bad_tile_requests_are_404(client, layer, z, x, y):
    assert get_tile(client, layer, z, x, y).status_code == 404


@pytest.mark.django_db
def test_tile_cache_lifetime_comes_from_settings(client, loaded, settings):
    settings.WUIXPOSE_TILE_CACHE_SECONDS = 42

    response = get_tile(client, "tracts", *tile_for(*ORIGIN, 15))

    assert response["Cache-Control"] == "public, max-age=42"


# TileJSON


@pytest.mark.parametrize("layer", ["tracts", "structures", "zones"])
def test_tilejson_describes_the_layer_from_its_definition(client, layer):
    spec = tiles.LAYERS[layer]

    data = client.get(reverse("tilejson", args=[layer])).json()

    assert data["tilejson"] == "3.0.0"
    assert data["tiles"] == [f"http://testserver/tiles/{layer}/{{z}}/{{x}}/{{y}}.mvt"]
    assert (data["minzoom"], data["maxzoom"]) == (spec.min_zoom, spec.max_zoom)
    assert "Boulder County" in data["attribution"]
    assert data["vector_layers"] == [
        {"id": layer, "fields": spec.fields, "minzoom": spec.min_zoom, "maxzoom": spec.max_zoom}
    ]


@pytest.mark.django_db
def test_tilejson_fields_match_what_tiles_carry(client, loaded):
    for layer in ("tracts", "structures", "zones"):
        tilejson = client.get(reverse("tilejson", args=[layer])).json()
        response = get_tile(client, layer, *tile_for(*ORIGIN, 15))

        features = mapbox_vector_tile.decode(response.content)[layer]["features"]
        assert features
        for feat in features:
            assert set(feat["properties"]) <= set(tilejson["vector_layers"][0]["fields"])


def test_tilejson_tile_urls_follow_the_request_host(client, settings):
    settings.ALLOWED_HOSTS = ["localhost"]

    data = client.get(reverse("tilejson", args=["tracts"]), HTTP_HOST="localhost:5173").json()

    assert data["tiles"] == ["http://localhost:5173/tiles/tracts/{z}/{x}/{y}.mvt"]


def test_tilejson_unknown_layer_is_404(client):
    assert client.get(reverse("tilejson", args=["roads"])).status_code == 404


# Detail and summary endpoints


@pytest.mark.django_db
def test_tract_detail(client, loaded):
    tract = loaded["tract"]

    data = client.get(reverse("tract-detail", args=[tract.pk])).json()

    assert data["id"] == tract.pk
    assert data["county_apns"] == ["146100000001"]
    # House numbers and units sort as numbers, not text.
    assert [(a["line1"], a["line2"]) for a in data["addresses"]] == [
        ("9 Gold Run Rd", "CO"),
        ("10 Gold Run Rd", "CO"),
        ("10 Gold Run Rd #9", "CO"),
        ("10 Gold Run Rd #10", "CO"),
    ]
    assert (data["addresses"][0]["lon"], data["addresses"][0]["lat"]) == pytest.approx(
        (ORIGIN[0] + 0.0003, ORIGIN[1] + 0.0003)
    )
    assert data["structure_ids"] == [loaded["structure"].pk]
    # 0.001 deg of longitude at 40.05 N is ~85 m and 0.001 deg of latitude ~111 m: ~2.3 acres.
    assert data["area_acres"] == pytest.approx(2.33, abs=0.05)


@pytest.mark.django_db
def test_structure_detail(client, loaded):
    structure = loaded["structure"]

    data = client.get(reverse("structure-detail", args=[structure.pk])).json()

    assert data["tract"] == loaded["tract"].pk
    assert data["tract_county_apns"] == ["146100000001"]
    assert data["source"] == "boco_footprints"
    assert data["source_id"] == "1N7116110001"
    assert len(data["tract_addresses"]) == 4
    # ~17 m x 11 m.
    assert data["footprint_sq_ft"] == pytest.approx(2040, rel=0.05)


@pytest.mark.django_db
def test_structure_detail_queries(client, loaded, django_assert_num_queries):
    # The structure with its tract, the tract's identifiers, and its addresses.
    with django_assert_num_queries(3):
        client.get(reverse("structure-detail", args=[loaded["structure"].pk]))


@pytest.mark.django_db
def test_structure_detail_without_a_tract(client):
    boulder.load_structures([feature({"StructureID": "S"}, box(0.0002, 0.0002, 0.0004, 0.0003))])

    data = client.get(reverse("structure-detail", args=[Structure.objects.get().pk])).json()

    assert (data["tract"], data["tract_county_apns"]) == (None, [])


@pytest.mark.django_db
def test_detail_404(client):
    assert client.get(reverse("tract-detail", args=[999])).status_code == 404


@pytest.mark.django_db
def test_summary_reports_extent_of_tracts(client, loaded):
    data = client.get(reverse("summary")).json()

    assert data["tract_count"] == 2
    assert data["structure_count"] == 1
    assert data["address_count"] == 4
    min_lon, min_lat, max_lon, max_lat = data["bbox"]
    assert (min_lon, min_lat) == pytest.approx(ORIGIN)
    assert (max_lon, max_lat) == pytest.approx((ORIGIN[0] + 0.002, ORIGIN[1] + 0.001))


@pytest.mark.django_db
def test_retired_addresses_are_left_out(client, loaded):
    boulder.load_addresses(
        [point_feature(address_props("1", "9", "GOLD RUN", "146100000001", STATUS="RETIRED"), 0.0003, 0.0003)]
    )

    tract = client.get(reverse("tract-detail", args=[loaded["tract"].pk])).json()
    summary = client.get(reverse("summary")).json()

    assert "9 Gold Run Rd" not in [a["line1"] for a in tract["addresses"]]
    assert len(tract["addresses"]) == 3
    assert summary["address_count"] == 3


@pytest.mark.django_db
def test_summary_with_no_data(client):
    assert client.get(reverse("summary")).json() == {
        "tract_count": 0,
        "structure_count": 0,
        "address_count": 0,
        "bbox": None,
    }
