import math

import mapbox_vector_tile
import pytest
from django.urls import reverse

from wuixpose.core.ingest import boulder
from wuixpose.core.models import Structure, Tract

from .factories import ORIGIN, box, feature


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
    boulder.assign_structure_tracts()
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
def test_tile_away_from_data_is_empty(client, loaded):
    assert get_tile(client, "tracts", *tile_for(-100.0, 35.0, 15)).status_code == 204


@pytest.mark.django_db
def test_tiles_below_layer_min_zoom_are_empty(client, loaded):
    assert get_tile(client, "structures", *tile_for(*ORIGIN, 12)).status_code == 204


@pytest.mark.django_db
@pytest.mark.parametrize(("layer", "z", "x", "y"), [("roads", 15, 0, 0), ("tracts", 15, 2**15, 0), ("tracts", 23, 0, 0)])
def test_bad_tile_requests_are_404(client, layer, z, x, y):
    assert get_tile(client, layer, z, x, y).status_code == 404


# Detail and summary endpoints


@pytest.mark.django_db
def test_tract_detail(client, loaded):
    tract = loaded["tract"]

    data = client.get(reverse("tract-detail", args=[tract.pk])).json()

    assert data["id"] == tract.pk
    assert data["county_apns"] == ["146100000001"]
    assert data["structure_ids"] == [loaded["structure"].pk]
    # 0.001 deg of longitude at 40.05 N is ~85 m and 0.001 deg of latitude ~111 m: ~2.3 acres.
    assert data["area_acres"] == pytest.approx(2.33, abs=0.05)


@pytest.mark.django_db
def test_structure_detail(client, loaded):
    structure = loaded["structure"]

    data = client.get(reverse("structure-detail", args=[structure.pk])).json()

    assert data["tract"] == loaded["tract"].pk
    assert data["source"] == "boco_footprints"
    assert data["source_id"] == "1N7116110001"
    # ~17 m x 11 m.
    assert data["footprint_sq_ft"] == pytest.approx(2040, rel=0.05)


@pytest.mark.django_db
def test_detail_404(client):
    assert client.get(reverse("tract-detail", args=[999])).status_code == 404


@pytest.mark.django_db
def test_summary_reports_extent_of_tracts(client, loaded):
    data = client.get(reverse("summary")).json()

    assert data["tract_count"] == 2
    assert data["structure_count"] == 1
    min_lon, min_lat, max_lon, max_lat = data["bbox"]
    assert (min_lon, min_lat) == pytest.approx(ORIGIN)
    assert (max_lon, max_lat) == pytest.approx((ORIGIN[0] + 0.002, ORIGIN[1] + 0.001))


@pytest.mark.django_db
def test_summary_with_no_data(client):
    assert client.get(reverse("summary")).json() == {"tract_count": 0, "structure_count": 0, "bbox": None}
