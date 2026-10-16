"""Which tract each structure and address belongs to, worked out from what's loaded.

Independent of where the data came from: ingests load tracts, structures and addresses, and these
link them up afterwards.
"""

from dataclasses import dataclass

from django.db import connection, transaction

from wuixpose.core.constants import MIN_TRACT_SHARE
from wuixpose.core.jobs import incremental_run
from wuixpose.core.models import JobRun
from wuixpose.core.models.tracts import TractIdentifier

_LINK_ADDRESSES = """
    WITH best AS (
        SELECT a.id,
               COALESCE(
                   (SELECT i.tract_id
                      FROM core_tractidentifier i
                     WHERE i.scheme = %(apn_scheme)s AND i.county_fips = a.county_fips
                       AND i.value = a.county_apn AND i.tracked_to IS NULL),
                   -- Stacked parcels (condos sharing a lot's outline) put several tracts under
                   -- one point; without a parcel number to choose, none is picked.
                   (SELECT min(t.id) FROM core_tract t WHERE ST_Intersects(t.geom, a.geom) HAVING count(*) = 1)
               ) AS tract_id
          FROM core_address a
         WHERE a.tracked_to IS NULL
    )
    UPDATE core_address a
       SET tract_id = best.tract_id
      FROM best
     WHERE a.id = best.id
       AND a.tract_id IS DISTINCT FROM best.tract_id
"""


def link_address_tracts() -> int:
    """Set every current address's tract, returning how many changed.

    An address belongs to the tract currently carrying its county parcel number. Failing that (the
    county replatted and the address still has the old number, or there's no number), it belongs
    to the one tract under its point, if there's exactly one. The point alone isn't trusted first:
    rural address points can sit at a driveway entrance on a neighbor's lot.

    Reconsiders every current address. Unlike structure assignment this is cheap enough to run in
    full after every ingest, so it needs no change tracking. Retired addresses keep the tract they
    last had.
    """
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(_LINK_ADDRESSES, {"apn_scheme": TractIdentifier.Scheme.COUNTY_APN})
        return cursor.rowcount


@dataclass
class AssignResult:
    changed: int
    full: bool

    def __str__(self) -> str:
        scope = "full pass" if self.full else "changes since last run"
        return f"{self.changed} structure-tract assignments changed ({scope})"


# Structures whose assignment may have changed since `since`: their own geometry changed, the
# tract they're assigned to changed (it may have shrunk away from them), or a changed tract now
# overlaps them (it may have grown onto them).
_CHANGED_CANDIDATES = """
    WITH changed_tracts AS (
        SELECT id, geom FROM core_tract WHERE geom_updated_at >= %(since)s
    )
    SELECT id FROM core_structure WHERE geom_updated_at >= %(since)s
    UNION
    SELECT s.id FROM core_structure s JOIN changed_tracts ct ON s.tract_id = ct.id
    UNION
    SELECT s.id FROM core_structure s JOIN changed_tracts ct ON ST_Intersects(ct.geom, s.geom)
"""
_ALL_CANDIDATES = "SELECT id FROM core_structure"

_ASSIGN = """
    WITH candidates AS ({candidates}),
    best AS (
        SELECT s.id AS structure_id, t.id AS tract_id
          FROM candidates c
          JOIN core_structure s ON s.id = c.id
          LEFT JOIN LATERAL (
              SELECT t.id
                FROM core_tract t
               CROSS JOIN LATERAL (
                   -- Most footprints sit wholly inside one lot, where ST_Covers settles the
                   -- overlap without computing an intersection polygon.
                   SELECT CASE WHEN ST_Covers(t.geom, s.geom) THEN ST_Area(s.geom)
                               ELSE ST_Area(ST_Intersection(t.geom, s.geom))
                          END AS overlap_area
               ) calc
               WHERE ST_Intersects(t.geom, s.geom)
                 AND calc.overlap_area >= %(min_share)s * ST_Area(s.geom)
               -- Lots don't overlap, so at most one usually qualifies. Stacked parcels (condos
               -- sharing a lot's outline) can, though, and without a fixed order the pick could
               -- flip between runs.
               ORDER BY calc.overlap_area DESC, t.id
               LIMIT 1
          ) t ON TRUE
    )
    UPDATE core_structure s
       SET tract_id = best.tract_id
      FROM best
     WHERE s.id = best.structure_id
       AND s.tract_id IS DISTINCT FROM best.tract_id
"""


def assign_structure_tracts(*, full: bool = False) -> AssignResult:
    """Set structures' tracts by footprint overlap (see MIN_TRACT_SHARE).

    Only structures that could have changed since the last successful run are reconsidered, as
    found through the trigger-maintained geom_updated_at columns, so this doesn't depend on being
    run by whatever wrote the geometry. The first run, and any run with `full`, reconsiders every
    structure; use `full` after changing the assignment rule itself.

    Not caught incrementally: a tract deleted without its replacement changing (its structures
    are only set to null). Ingests don't delete tracts; a full run covers it if anything does.

    Areas are compared in degrees, which is fine for a ratio between shapes a few meters apart.
    """
    with incremental_run(JobRun.Job.ASSIGN_STRUCTURE_TRACTS, full=full) as run:
        candidates = _ALL_CANDIDATES if run.full else _CHANGED_CANDIDATES
        run.cursor.execute(
            _ASSIGN.format(candidates=candidates),
            {"since": run.since, "min_share": MIN_TRACT_SHARE},
        )
        run.rows_changed = run.cursor.rowcount
    return AssignResult(changed=run.rows_changed, full=run.full)
