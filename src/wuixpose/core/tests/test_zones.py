"""Zones drawn around structures, and the incremental job that keeps them current.

The incremental tests are transactional for the same reason as test_assignment's: the trigger
stamps now(), which is constant within a transaction.
"""

import io
from itertools import combinations

import pytest
from django.contrib.gis.geos import Point
from django.core.management import call_command

from wuixpose.core import zones
from wuixpose.core.ingest import boulder
from wuixpose.core.models import JobRun, Structure, Zone

from .factories import box, feature

transactional = pytest.mark.django_db(transaction=True)

# NAD83 / UTM zone 13N, in meters: the zone ORIGIN is in, for measuring distances there.
UTM_13N = 26913

# ~17 m x 11 m.
HOUSE = box(0.0002, 0.0002, 0.0004, 0.0003)


def load_structure(source_id="house", ring=HOUSE) -> Structure:
    boulder.load_structures([feature({"StructureID": source_id}, ring)])
    return Structure.objects.get(source_id=source_id)


def zone_geoms(structure) -> dict:
    return {z.ring_key: z.geom for z in structure.zones.filter(rule_version=zones.RULE_VERSION)}


def feet_from(footprint, ring) -> list[float]:
    """How far each vertex of a (projected) linear ring is from a (projected) footprint."""
    return [footprint.distance(Point(x, y, srid=UTM_13N)) / zones.M_PER_FT for x, y in ring.coords]


# Geometry


@pytest.mark.django_db
def test_each_ring_spans_its_distances_from_the_footprint():
    house = load_structure()

    zones.build_zones()

    footprint = house.geom.transform(UTM_13N, clone=True)
    geoms = zone_geoms(house)
    assert set(geoms) == {ring.key for ring in zones.RINGS}
    for ring in zones.RINGS:
        (polygon,) = geoms[ring.key].transform(UTM_13N, clone=True)
        outer_edge, inner_edge = polygon  # a ring is one polygon with one hole
        assert feet_from(footprint, outer_edge) == pytest.approx([ring.outer_ft] * len(outer_edge), rel=0.005)
        assert feet_from(footprint, inner_edge) == pytest.approx([ring.inner_ft] * len(inner_edge), abs=0.05)


@pytest.mark.django_db
def test_rings_meet_without_overlapping_or_leaving_gaps():
    house = load_structure()

    zones.build_zones()

    geoms = zone_geoms(house)
    for a, b in combinations(geoms.values(), 2):
        assert a.intersection(b).area == pytest.approx(0, abs=1e-15)
    for geom in geoms.values():
        assert geom.intersection(house.geom).area == pytest.approx(0, abs=1e-15)
    # Footprint plus rings is everything within the outermost distance: one shape, no holes.
    whole = house.geom
    for geom in geoms.values():
        whole = whole.union(geom)
    assert whole.geom_type == "Polygon"
    assert whole.num_interior_rings == 0


@pytest.mark.django_db
def test_zones_of_neighboring_structures_overlap():
    # ~28 ft apart: each sits inside the other's 5-30 ft ring.
    house = load_structure()
    shed = load_structure("shed", box(0.0005, 0.0002, 0.00055, 0.00025))

    zones.build_zones()

    assert zone_geoms(house)["hiz_5_30"].intersects(shed.geom)
    assert zone_geoms(house)["hiz_5_30"].intersects(zone_geoms(shed)["hiz_0_5"])


# The incremental job


@transactional
def test_first_run_is_a_full_pass_and_is_recorded():
    load_structure()

    result = zones.build_zones()

    assert (result.changed, result.full) == (3, True)
    run = JobRun.objects.get()
    assert (run.job, run.full, run.rows_changed) == ("build_zones", True, 3)


@transactional
def test_a_changed_footprint_is_redrawn_in_place_and_others_are_left_alone():
    house = load_structure()
    load_structure("shed", box(0.001, 0.001, 0.0011, 0.0011))
    zones.build_zones()
    before = {z.pk: z.geom.wkb for z in Zone.objects.all()}

    load_structure(ring=box(0.0002, 0.0002, 0.0005, 0.0003))
    result = zones.build_zones()

    assert (result.changed, result.full) == (3, False)
    after = {z.pk: z.geom.wkb for z in Zone.objects.all()}
    assert after.keys() == before.keys()
    redrawn = {pk for pk in after if after[pk] != before[pk]}
    assert redrawn == set(house.zones.values_list("pk", flat=True))


@transactional
def test_a_new_structure_gets_zones_and_an_unchanged_one_is_skipped():
    load_structure()
    zones.build_zones()

    assert zones.build_zones().changed == 0

    shed = load_structure("shed", box(0.001, 0.001, 0.0011, 0.0011))
    assert zones.build_zones().changed == 3
    assert shed.zones.count() == 3


@transactional
def test_a_new_rule_version_is_built_alongside_the_old_one(monkeypatch):
    house = load_structure()
    zones.build_zones()
    old = set(house.zones.values_list("pk", flat=True))

    monkeypatch.setattr(zones, "RULE_VERSION", zones.RULE_VERSION + 1)
    result = zones.build_zones()

    # Found without --full: nothing changed, but the structure has no zones at this version.
    assert (result.changed, result.full) == (3, False)
    assert set(house.zones.values_list("pk", flat=True)) > old
    assert sorted(house.zones.values_list("rule_version", flat=True)) == [1, 1, 1, 2, 2, 2]


@transactional
def test_full_run_redraws_only_what_differs():
    house = load_structure()
    zones.build_zones()
    Zone.objects.filter(ring_key="hiz_0_5").update(geom=house.geom)

    assert zones.build_zones().changed == 0
    result = zones.build_zones(full=True)

    assert (result.changed, result.full) == (1, True)
    assert not zone_geoms(house)["hiz_0_5"].equals(house.geom)


@transactional
def test_build_command_reports_scope():
    load_structure()
    out = io.StringIO()

    call_command("build_zones", stdout=out)
    call_command("build_zones", stdout=out)
    call_command("build_zones", "--full", stdout=out)

    assert out.getvalue().splitlines() == [
        "3 zones built or redrawn (full pass).",
        "0 zones built or redrawn (changes since last run).",
        "0 zones built or redrawn (full pass).",
    ]
