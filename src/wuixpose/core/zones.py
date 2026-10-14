"""Zones: rings around each structure at set distances from its footprint.

The rings are defined here, in code. Zone rows hold the geometry they produce for one structure,
so tiles and anything that later measures a zone read polygons rather than rebuilding them.
"""

from dataclasses import dataclass

from django.db import connection, transaction

from wuixpose.core.models import JobRun

M_PER_FT = 0.3048


@dataclass(frozen=True)
class Ring:
    key: str  # Zone.ring_key
    # Distances from the footprint's edge. A ring starting at 0 starts at the wall.
    inner_ft: float
    outer_ft: float


# Home ignition zones 1 to 3, nearest the structure first. Each starts where the last ends, so
# together they cover everything within 100 ft with no overlap.
RINGS = (
    Ring("hiz_0_5", 0, 5),
    Ring("hiz_5_30", 5, 30),
    Ring("hiz_30_100", 30, 100),
)

# Bump when RINGS, or how a ring is drawn from a footprint, changes. Zones are then built again
# under the new version and the old rows are kept (see Zone); tiles serve the current one.
RULE_VERSION = 1


@dataclass
class BuildResult:
    changed: int
    full: bool

    def __str__(self) -> str:
        scope = "full pass" if self.full else "changes since last run"
        return f"{self.changed} zones built or redrawn ({scope})"


# Structures whose zones may be out of date since `since`: their footprint changed, or they have
# none at this rule version (new rule version, or zones deleted by hand).
_CHANGED_CANDIDATES = """
    SELECT id FROM core_structure WHERE geom_updated_at >= %(since)s
    UNION
    SELECT s.id
      FROM core_structure s
     WHERE NOT EXISTS (
               SELECT 1 FROM core_zone z WHERE z.structure_id = s.id AND z.rule_version = %(rule_version)s
           )
"""
_ALL_CANDIDATES = "SELECT id FROM core_structure"

# Buffering as geography takes distances in meters: PostGIS buffers in a projection local to each
# footprint and brings the result back to 4326. Buffers are rounded at corners, so a ring's edge
# is everywhere the same distance from the footprint, and a ring's outer edge is the next ring's
# inner edge exactly, both being the same buffer of the same footprint.
_BUILD = """
    WITH candidates AS ({candidates})
    INSERT INTO core_zone (structure_id, ring_key, rule_version, geom)
    SELECT s.id,
           r.key,
           %(rule_version)s,
           ST_Multi(
               ST_Difference(
                   ST_Buffer(s.geom::geography, r.outer_m)::geometry,
                   CASE WHEN r.inner_m = 0 THEN s.geom
                        ELSE ST_Buffer(s.geom::geography, r.inner_m)::geometry
                   END
               )
           )
      FROM candidates c
      JOIN core_structure s ON s.id = c.id
     CROSS JOIN unnest(%(keys)s::text[], %(inner_m)s::float8[], %(outer_m)s::float8[]) AS r(key, inner_m, outer_m)
        ON CONFLICT (structure_id, ring_key, rule_version) DO UPDATE
       SET geom = EXCLUDED.geom
     WHERE core_zone.geom IS DISTINCT FROM EXCLUDED.geom
"""


def build_zones(*, full: bool = False) -> BuildResult:
    """Draw RINGS around structures and store them as Zone rows at RULE_VERSION.

    Only structures whose footprint changed since the last successful run, or that have no zones
    at this rule version, are redrawn; a changed footprint's zones are updated in place. The first
    run, and any run with `full`, redraws every structure.
    """
    job = JobRun.Job.BUILD_ZONES
    with transaction.atomic(), connection.cursor() as cursor:
        # One run at a time, so two runs can't interleave their watermarks.
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [job])
        # The transaction's start, the same clock the geom_updated_at trigger stamps with.
        cursor.execute("SELECT now()")
        (started_at,) = cursor.fetchone()
        since = (
            None
            if full
            else JobRun.objects.filter(job=job).order_by("-started_at").values_list("started_at", flat=True).first()
        )
        candidates = _ALL_CANDIDATES if since is None else _CHANGED_CANDIDATES
        cursor.execute(
            _BUILD.format(candidates=candidates),
            {
                "since": since,
                "rule_version": RULE_VERSION,
                "keys": [ring.key for ring in RINGS],
                "inner_m": [ring.inner_ft * M_PER_FT for ring in RINGS],
                "outer_m": [ring.outer_ft * M_PER_FT for ring in RINGS],
            },
        )
        result = BuildResult(changed=cursor.rowcount, full=since is None)
        JobRun.objects.create(job=job, started_at=started_at, full=result.full, rows_changed=result.changed)
    return result
