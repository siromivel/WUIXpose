"""Load Boulder County parcels (as tracts), building footprints (as structures) and addresses.

All three layers are published by Boulder County under CC BY 4.0:
- Parcels, countywide, from the Assessor's Office.
- Building footprints, unincorporated county only, from Land Use. Cities keep their own.
- Address points, countywide, from the Assessor's Office (AddressOne). The county notes a backlog
  of new developments not yet addressed.
"""

import logging
import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Any

from django.contrib.gis.geos import GEOSGeometry
from django.db import connection, transaction
from django.utils import timezone

from wuixpose.core.ingest import rejects
from wuixpose.core.ingest.arcgis import iter_features
from wuixpose.core.ingest.geometry import (
    UnreadableGeometry,
    as_multipolygon,
    multipolygon_from_geojson,
    point_from_geojson,
)
from wuixpose.core.models import Address, JobRun, RejectedFeature, Structure, Tract
from wuixpose.core.models.tracts import TractIdentifier

logger = logging.getLogger(__name__)

COUNTY_FIPS = "08013"
PARCELS_URL = "https://maps.bouldercounty.org/arcgis/rest/services/Emap/BOCO_Parcels/MapServer/0"
FOOTPRINTS_URL = "https://maps.bouldercounty.org/arcgis/rest/services/PARCELS/BUILDINGS_STRUCTURE_FOOTPRINT/MapServer/0"
ADDRESSES_URL = "https://maps.bouldercounty.org/arcgis/rest/services/PARCELS/ADDRESS_POINTS/MapServer/0"
# Credit required by CC BY 4.0 wherever this data is shown. HTML, as map clients render it.
ATTRIBUTION = (
    'Parcels, footprints and addresses: <a href="https://opendata-bouldercounty.hub.arcgis.com/">Boulder County</a>, '
    '<a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>'
)

# A structure belongs to the tract holding at least this share of its footprint. Lot lines and
# footprints are digitized separately, so a house wholly on one lot often pokes a few percent
# over the line; a footprint split more evenly than this has no single tract.
MIN_TRACT_SHARE = 0.9

BATCH_SIZE = 2000

Bbox = tuple[float, float, float, float]


@dataclass
class LoadResult:
    created: int = 0
    updated: int = 0
    skipped: int = 0  # no usable ID or geometry; each is recorded as a RejectedFeature
    retired: int | None = None  # None for layers whose loads don't retire anything
    unchanged: int | None = None  # None for layers whose loads rewrite every existing row

    def __str__(self) -> str:
        unchanged = "" if self.unchanged is None else f", {self.unchanged} unchanged"
        retired = "" if self.retired is None else f", {self.retired} retired"
        return f"{self.created} created, {self.updated} updated{unchanged}{retired}, {self.skipped} skipped"


def fetch_parcels(bbox: Bbox | None = None, **kwargs) -> Iterable[dict[str, Any]]:
    return iter_features(PARCELS_URL, out_fields=("OBJECTID", "PARCEL_NO"), bbox=bbox, **kwargs)


def fetch_footprints(bbox: Bbox | None = None, **kwargs) -> Iterable[dict[str, Any]]:
    # Demolished footprints stay in the county layer with Status = 'Demolished'.
    return iter_features(
        FOOTPRINTS_URL,
        where="Status = 'Constructed'",
        out_fields=("OBJECTID", "StructureID"),
        bbox=bbox,
        **kwargs,
    )


# Address point fields that make up the street name, in the order they're written.
STREET_FIELDS = ("PREFIX", "PREMODIFIER", "PRETYPE", "STREETNAME", "STREETTYPE", "SUFFIX", "POSTMODIFIER")


def fetch_addresses(bbox: Bbox | None = None, **kwargs) -> Iterable[dict[str, Any]]:
    """Active and retired address points. Count-checked, so a load can retire what's missing."""
    # Retired addresses either stay in the county layer as RETIRED or are removed from it. Other
    # statuses (POTENTIAL, null) aren't addresses we load.
    return iter_features(
        ADDRESSES_URL,
        where="STATUS IN ('ACTIVE', 'RETIRED')",
        out_fields=(
            "OBJECTID",
            "ADDRESS_ID",
            "STATUS",
            "STREET_NUMBER",
            "STREET_NUMBER_SUFFIX",
            *STREET_FIELDS,
            "UNITTYPE",
            "UNIT",
            "CITY",
            "ZIPCODE",
            "PARCEL_NUMBER",
        ),
        bbox=bbox,
        check_count=True,
        **kwargs,
    )


def _group_by_key(
    features: Iterable[dict[str, Any]], key_field: str, layer: RejectedFeature.Layer
) -> tuple[dict[str, GEOSGeometry], list[RejectedFeature]]:
    """Merge features sharing an ID into one MultiPolygon per ID, and reject the unusable ones.

    The county splits some parcels into several features (a lot cut by a road, say) that share
    one parcel number, so the ID, not the feature, is the unit.
    """
    Reason = RejectedFeature.Reason
    pieces: dict[str, list[tuple[dict[str, Any], GEOSGeometry]]] = defaultdict(list)
    rejected = []
    for feature in features:
        key = ((feature.get("properties") or {}).get(key_field) or "").strip()
        if not key:
            rejected.append(rejects.reject(layer, feature, Reason.MISSING_ID))
            continue
        try:
            geom = multipolygon_from_geojson(feature.get("geometry"))
        except UnreadableGeometry as exc:
            rejected.append(rejects.reject(layer, feature, Reason.UNREADABLE_GEOMETRY, source_id=key, detail=str(exc)))
            continue
        if geom is None:
            rejected.append(rejects.reject(layer, feature, Reason.NOT_POLYGONAL, source_id=key))
            continue
        pieces[key].append((feature, geom))

    merged = {}
    for key, group in pieces.items():
        geom = group[0][1] if len(group) == 1 else as_multipolygon(g for _, g in group)
        if geom is None:
            rejected.extend(rejects.reject(layer, f, Reason.NOT_POLYGONAL, source_id=key) for f, _ in group)
            continue
        merged[key] = geom
    return merged, rejected


def load_tracts(features: Iterable[dict[str, Any]], *, as_of: date | None = None) -> LoadResult:
    """Upsert one tract per parcel number, matched through its current county APN identifier.

    New identifiers are tracked from `as_of` (default: today); existing ones keep their date.
    """
    as_of = as_of or timezone.localdate()
    by_apn, rejected = _group_by_key(features, "PARCEL_NO", RejectedFeature.Layer.BOCO_PARCELS)
    result = LoadResult(skipped=len(rejected))

    with transaction.atomic():
        rejects.record(rejected)
        existing = dict(
            TractIdentifier.objects.filter(
                scheme=TractIdentifier.Scheme.COUNTY_APN,
                county_fips=COUNTY_FIPS,
                tracked_to__isnull=True,
                value__in=list(by_apn),
            ).values_list("value", "tract_id")
        )

        to_update = [Tract(pk=tract_id, geom=by_apn[apn]) for apn, tract_id in existing.items()]
        Tract.objects.bulk_update(to_update, ["geom"], batch_size=BATCH_SIZE)
        result.updated = len(to_update)

        new_apns = [apn for apn in by_apn if apn not in existing]
        tracts = Tract.objects.bulk_create([Tract(geom=by_apn[apn]) for apn in new_apns], batch_size=BATCH_SIZE)
        TractIdentifier.objects.bulk_create(
            [
                TractIdentifier(
                    tract=tract,
                    scheme=TractIdentifier.Scheme.COUNTY_APN,
                    county_fips=COUNTY_FIPS,
                    value=apn,
                    tracked_from=as_of,
                )
                for apn, tract in zip(new_apns, tracts, strict=True)
            ],
            batch_size=BATCH_SIZE,
        )
        result.created = len(tracts)
    return result


def load_structures(features: Iterable[dict[str, Any]]) -> LoadResult:
    """Upsert one structure per county StructureID."""
    by_id, rejected = _group_by_key(features, "StructureID", RejectedFeature.Layer.BOCO_FOOTPRINTS)
    result = LoadResult(skipped=len(rejected))
    source = Structure.Source.BOCO_FOOTPRINTS

    with transaction.atomic():
        rejects.record(rejected)
        existing = dict(
            Structure.objects.filter(source=source, source_id__in=list(by_id)).values_list("source_id", "pk")
        )
        to_update = [Structure(pk=pk, geom=by_id[sid]) for sid, pk in existing.items()]
        Structure.objects.bulk_update(to_update, ["geom"], batch_size=BATCH_SIZE)
        result.updated = len(to_update)

        created = Structure.objects.bulk_create(
            [Structure(geom=geom, source=source, source_id=sid) for sid, geom in by_id.items() if sid not in existing],
            batch_size=BATCH_SIZE,
        )
        result.created = len(created)
    return result


def _text(props: dict[str, Any], *fields: str) -> str:
    """Join the non-blank values of fields with spaces. The county mixes nulls and empty strings."""
    return " ".join(v for f in fields if (v := " ".join(str(props.get(f) or "").split())))


def _address_fields(props: dict[str, Any]) -> dict[str, Any] | None:
    """Address model fields from an address point's attributes, or None if it has no street address."""
    number = _text(props, "STREET_NUMBER", "STREET_NUMBER_SUFFIX")
    street = _text(props, *STREET_FIELDS)
    if not number or not street:
        return None

    unit = _text(props, "UNIT")
    if unit:
        unit = f"{unit_type} {unit}" if (unit_type := _text(props, "UNITTYPE")) else f"#{unit}"
    jurisdiction = _text(props, "CITY")
    if jurisdiction == "UNINCORPORATED":
        jurisdiction = "UNINCORPORATED BOULDER COUNTY"
    zip_code = _text(props, "ZIPCODE")
    apn = _text(props, "PARCEL_NUMBER")
    return {
        "number": number,
        "street": street,
        "unit": unit,
        "jurisdiction": jurisdiction,
        "state": "CO",
        "zip_code": zip_code if re.fullmatch(r"\d{5}", zip_code) else "",  # also holds " " and "0"
        "county_fips": COUNTY_FIPS if apn else None,
        "county_apn": apn or None,
    }


ADDRESS_FIELDS = ("geom", "number", "street", "unit", "jurisdiction", "state", "zip_code", "county_fips", "county_apn")


def _matches(address: Address, fields: dict[str, Any]) -> bool:
    """Whether a stored address already has these field values. Points must match exactly."""
    return all(
        address.geom.equals_exact(value) if name == "geom" else getattr(address, name) == value
        for name, value in fields.items()
    )


def load_addresses(
    features: Iterable[dict[str, Any]], *, as_of: date | None = None, complete: bool = False
) -> LoadResult:
    """Upsert one address per county ADDRESS_ID and retire those the county has retired.

    An address is retired (tracked_to set to `as_of`, default today) when its feature says
    RETIRED, or, with `complete`, when no active feature has its ID. Pass `complete` only for
    features that are the whole layer, count-checked (fetch_addresses with no bbox): every current
    address missing from them is retired. An active feature that's rejected still counts as
    present, since the county still has the address. A retired address keeps its last active
    details; one that turns up active again is current again, keeping its tracked_from.

    New addresses are tracked from `as_of`. Run link_address_tracts afterwards.
    """
    as_of = as_of or timezone.localdate()
    layer = RejectedFeature.Layer.BOCO_ADDRESS_POINTS
    Reason = RejectedFeature.Reason
    by_id: dict[str, dict[str, Any]] = {}
    present: set[str] = set()  # IDs of every active feature, loaded or rejected
    retired: set[str] = set()  # IDs the county marks RETIRED
    rejected = []
    for feature in features:
        props = feature.get("properties") or {}
        address_id = _text(props, "ADDRESS_ID")
        if _text(props, "STATUS") == "RETIRED":
            # Only the ID matters: the address keeps its details from while it was active.
            if address_id:
                retired.add(address_id)
            continue
        if not address_id:
            rejected.append(rejects.reject(layer, feature, Reason.MISSING_ID))
            continue
        present.add(address_id)
        try:
            geom = point_from_geojson(feature.get("geometry"))
        except UnreadableGeometry as exc:
            rejected.append(rejects.reject(layer, feature, Reason.UNREADABLE_GEOMETRY, source_id=address_id, detail=str(exc)))
            continue
        if geom is None:
            rejected.append(rejects.reject(layer, feature, Reason.NOT_A_POINT, source_id=address_id))
            continue
        fields = _address_fields(props)
        if fields is None:
            rejected.append(rejects.reject(layer, feature, Reason.NO_STREET_ADDRESS, source_id=address_id))
            continue
        by_id[address_id] = fields | {"geom": geom}
    result = LoadResult(skipped=len(rejected))
    source = Address.Source.BOCO_ADDRESS_POINTS

    with transaction.atomic():
        rejects.record(rejected)
        ours = Address.objects.filter(source=source)
        existing = {
            a.source_id: a
            for a in ours.filter(source_id__in=list(by_id)).only("source_id", "tracked_to", *ADDRESS_FIELDS)
        }
        # Rewriting every row is most of a countywide load's time, and few change between runs.
        to_update = []
        for aid, address in existing.items():
            fields = by_id[aid]
            if address.tracked_to is None and _matches(address, fields):
                continue
            for name, value in fields.items():
                setattr(address, name, value)
            address.tracked_to = None
            to_update.append(address)
        Address.objects.bulk_update(to_update, [*ADDRESS_FIELDS, "tracked_to"], batch_size=BATCH_SIZE)
        result.updated = len(to_update)
        result.unchanged = len(existing) - len(to_update)

        created = Address.objects.bulk_create(
            [
                Address(source=source, source_id=aid, tracked_from=as_of, **fields)
                for aid, fields in by_id.items()
                if aid not in existing
            ],
            batch_size=BATCH_SIZE,
        )
        result.created = len(created)

        gone = ours.current().exclude(source_id__in=present) if complete else ours.current().filter(source_id__in=retired)
        result.retired = gone.update(tracked_to=as_of)
    return result


_LINK_ADDRESSES = """
    WITH best AS (
        SELECT a.id,
               COALESCE(
                   (SELECT i.tract_id
                      FROM core_tractidentifier i
                     WHERE i.scheme = 'county_apn' AND i.county_fips = a.county_fips
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
        cursor.execute(_LINK_ADDRESSES)
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
    job = JobRun.Job.ASSIGN_STRUCTURE_TRACTS
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
        cursor.execute(_ASSIGN.format(candidates=candidates), {"since": since, "min_share": MIN_TRACT_SHARE})
        result = AssignResult(changed=cursor.rowcount, full=since is None)
        JobRun.objects.create(job=job, started_at=started_at, full=result.full, rows_changed=result.changed)
    return result
