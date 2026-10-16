"""Geometry change tracking and the incremental structure-to-tract assignment built on it.

These use transactional tests: the trigger stamps now(), which is constant within a transaction,
so ordinary (rolled-back, single-transaction) tests would give every write the same timestamp.
"""

import io

import pytest
from django.core.management import call_command
from django.db import connection

from wuixpose.core import assignment
from wuixpose.core.ingest import boulder
from wuixpose.core.models import JobRun, Structure, Tract

from .factories import box, feature, multipolygon

transactional = pytest.mark.django_db(transaction=True)


def geom_updated_at(model, pk):
    return model.objects.values_list("geom_updated_at", flat=True).get(pk=pk)


def set_tract_without_touching_geometry(structure_id, tract_id):
    """A write the assignment job can't see: no geometry changed, so nothing marks it."""
    with connection.cursor() as cursor:
        cursor.execute("UPDATE core_structure SET tract_id = %s WHERE id = %s", [tract_id, structure_id])


def tract_of():
    return dict(Structure.objects.values_list("source_id", "tract_id"))


# The trigger


@transactional
def test_insert_stamps_geom_updated_at():
    tract = Tract.objects.create(geom=multipolygon(box(0, 0, 0.001, 0.001)))

    assert geom_updated_at(Tract, tract.pk) is not None


@transactional
def test_geom_updated_at_moves_only_when_geometry_changes():
    tract = Tract.objects.create(geom=multipolygon(box(0, 0, 0.001, 0.001)))
    stamped = geom_updated_at(Tract, tract.pk)

    # bulk_update rewrites the column even when the value is identical, as ingests do.
    Tract.objects.bulk_update([Tract(pk=tract.pk, geom=multipolygon(box(0, 0, 0.001, 0.001)))], ["geom"])
    assert geom_updated_at(Tract, tract.pk) == stamped

    Tract.objects.filter(pk=tract.pk).update(geom=multipolygon(box(0, 0, 0.002, 0.001)))
    assert geom_updated_at(Tract, tract.pk) > stamped


@transactional
def test_values_written_from_python_are_ignored():
    tract = Tract.objects.create(geom=multipolygon(box(0, 0, 0.001, 0.001)))
    stamped = geom_updated_at(Tract, tract.pk)

    with connection.cursor() as cursor:
        cursor.execute("UPDATE core_tract SET geom_updated_at = '2000-01-01' WHERE id = %s", [tract.pk])

    assert geom_updated_at(Tract, tract.pk) == stamped


@transactional
def test_structures_are_tracked_too():
    boulder.load_structures([feature({"StructureID": "S"}, box(0, 0, 0.0001, 0.0001))])
    structure = Structure.objects.get()
    stamped = geom_updated_at(Structure, structure.pk)

    boulder.load_structures([feature({"StructureID": "S"}, box(0, 0, 0.0002, 0.0001))])

    assert geom_updated_at(Structure, structure.pk) > stamped


# Incremental assignment


def load_two_lots_and_structures():
    boulder.load_tracts(
        [
            feature({"PARCEL_NO": "A"}, box(0, 0, 0.001, 0.001)),
            feature({"PARCEL_NO": "B"}, box(0.002, 0, 0.003, 0.001)),
        ]
    )
    boulder.load_structures(
        [
            feature({"StructureID": "on-a"}, box(0.0001, 0.0001, 0.0002, 0.0002)),
            feature({"StructureID": "on-b"}, box(0.0021, 0.0001, 0.0022, 0.0002)),
            # In the gap between the lots.
            feature({"StructureID": "between"}, box(0.0014, 0.0001, 0.0015, 0.0002)),
        ]
    )


@transactional
def test_first_run_is_a_full_pass_and_is_recorded():
    load_two_lots_and_structures()

    result = assignment.assign_structure_tracts()

    assert (result.changed, result.full) == (2, True)
    run = JobRun.objects.get()
    assert (run.job, run.full, run.rows_changed) == ("assign_structure_tracts", True, 2)


@transactional
def test_a_tract_growing_onto_an_unchanged_structure_is_picked_up():
    load_two_lots_and_structures()
    assignment.assign_structure_tracts()

    # Lot A is redrawn to take in the gap; the structure there didn't change.
    boulder.load_tracts([feature({"PARCEL_NO": "A"}, box(0, 0, 0.0018, 0.001))])
    result = assignment.assign_structure_tracts()

    a = Tract.objects.get(identifiers__value="A").pk
    assert (result.changed, result.full) == (1, False)
    assert tract_of()["between"] == a


@transactional
def test_a_tract_shrinking_away_from_an_unchanged_structure_is_picked_up():
    load_two_lots_and_structures()
    assignment.assign_structure_tracts()

    # Lot B shrinks to its east half, leaving its structure outside it.
    boulder.load_tracts([feature({"PARCEL_NO": "B"}, box(0.0025, 0, 0.003, 0.001))])
    assignment.assign_structure_tracts()

    assert tract_of()["on-b"] is None


@transactional
def test_a_moved_structure_is_picked_up():
    load_two_lots_and_structures()
    assignment.assign_structure_tracts()

    boulder.load_structures([feature({"StructureID": "between"}, box(0.0022, 0.0003, 0.0023, 0.0004))])
    assignment.assign_structure_tracts()

    assert tract_of()["between"] == Tract.objects.get(identifiers__value="B").pk


@transactional
def test_incremental_runs_leave_unchanged_structures_alone_and_full_runs_do_not():
    load_two_lots_and_structures()
    assignment.assign_structure_tracts()
    on_a = Structure.objects.get(source_id="on-a")
    b = Tract.objects.get(identifiers__value="B").pk
    set_tract_without_touching_geometry(on_a.pk, b)

    assert assignment.assign_structure_tracts().changed == 0
    assert tract_of()["on-a"] == b

    assert assignment.assign_structure_tracts(full=True).changed == 1
    assert tract_of()["on-a"] == Tract.objects.get(identifiers__value="A").pk


@transactional
def test_assign_command_reports_scope():
    load_two_lots_and_structures()
    out = io.StringIO()

    call_command("assign_structure_tracts", stdout=out)
    call_command("assign_structure_tracts", stdout=out)
    call_command("assign_structure_tracts", "--full", stdout=out)

    assert out.getvalue().splitlines() == [
        "2 structure-tract assignments changed (full pass).",
        "0 structure-tract assignments changed (changes since last run).",
        "0 structure-tract assignments changed (full pass).",
    ]


@transactional
def test_watermark_is_the_jobs_transaction_start():
    load_two_lots_and_structures()

    assignment.assign_structure_tracts()

    # Every structure was written before the job's transaction began.
    run = JobRun.objects.get()
    latest_write = Structure.objects.order_by("-geom_updated_at").values_list("geom_updated_at", flat=True).first()
    assert latest_write is not None
    assert run.started_at > latest_write
