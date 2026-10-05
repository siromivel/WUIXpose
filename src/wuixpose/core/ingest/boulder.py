"""Load Boulder County parcels (as tracts) and building footprints (as structures).

Both layers are published by Boulder County under CC BY 4.0:
- Parcels, countywide, from the Assessor's Office.
- Building footprints, unincorporated county only, from Land Use. Cities keep their own.
"""

import logging
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from django.contrib.gis.geos import GEOSGeometry
from django.db import connection, transaction

from wuixpose.core.ingest.arcgis import iter_features
from wuixpose.core.ingest.geometry import as_multipolygon, multipolygon_from_geojson
from wuixpose.core.models import Structure, Tract
from wuixpose.core.models.tracts import TractIdentifier

logger = logging.getLogger(__name__)

COUNTY_FIPS = "08013"
PARCELS_URL = "https://maps.bouldercounty.org/arcgis/rest/services/Emap/BOCO_Parcels/MapServer/0"
FOOTPRINTS_URL = "https://maps.bouldercounty.org/arcgis/rest/services/PARCELS/BUILDINGS_STRUCTURE_FOOTPRINT/MapServer/0"
# Credit required by CC BY 4.0 wherever this data is shown. HTML, as map clients render it.
ATTRIBUTION = (
    'Parcels and footprints: <a href="https://opendata-bouldercounty.hub.arcgis.com/">Boulder County</a>, '
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
    skipped: int = 0  # no usable ID or geometry

    def __str__(self) -> str:
        return f"{self.created} created, {self.updated} updated, {self.skipped} skipped"


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


def _group_by_key(features: Iterable[dict[str, Any]], key_field: str) -> tuple[dict[str, GEOSGeometry], int]:
    """Merge features sharing an ID into one MultiPolygon per ID.

    The county splits some parcels into several features (a lot cut by a road, say) that share
    one parcel number, so the ID, not the feature, is the unit.
    """
    pieces: dict[str, list[GEOSGeometry]] = defaultdict(list)
    skipped = 0
    for feature in features:
        key = ((feature.get("properties") or {}).get(key_field) or "").strip()
        geom = multipolygon_from_geojson(feature.get("geometry"))
        if not key or geom is None:
            skipped += 1
            continue
        pieces[key].append(geom)

    merged = {}
    for key, geoms in pieces.items():
        geom = geoms[0] if len(geoms) == 1 else as_multipolygon(geoms)
        if geom is None:
            skipped += 1
            continue
        merged[key] = geom
    return merged, skipped


def load_tracts(features: Iterable[dict[str, Any]]) -> LoadResult:
    """Upsert one tract per parcel number, matched through its current county APN identifier."""
    by_apn, skipped = _group_by_key(features, "PARCEL_NO")
    result = LoadResult(skipped=skipped)

    with transaction.atomic():
        existing = dict(
            TractIdentifier.objects.filter(
                scheme=TractIdentifier.Scheme.COUNTY_APN,
                county_fips=COUNTY_FIPS,
                valid_to__isnull=True,
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
                )
                for apn, tract in zip(new_apns, tracts, strict=True)
            ],
            batch_size=BATCH_SIZE,
        )
        result.created = len(tracts)
    return result


def load_structures(features: Iterable[dict[str, Any]]) -> LoadResult:
    """Upsert one structure per county StructureID."""
    by_id, skipped = _group_by_key(features, "StructureID")
    result = LoadResult(skipped=skipped)
    source = Structure.Source.BOCO_FOOTPRINTS

    with transaction.atomic():
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


def assign_structure_tracts() -> int:
    """Set each structure's tract by footprint overlap (see MIN_TRACT_SHARE). Returns rows changed.

    Areas are compared in degrees, which is fine for a ratio between shapes a few meters apart.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            WITH best AS (
                SELECT s.id AS structure_id,
                       (SELECT t.id
                          FROM core_tract t
                         WHERE t.geom && s.geom
                           AND ST_Intersects(t.geom, s.geom)
                           AND ST_Area(ST_Intersection(t.geom, s.geom)) >= %s * ST_Area(s.geom)
                         ORDER BY ST_Area(ST_Intersection(t.geom, s.geom)) DESC, t.id
                         LIMIT 1) AS tract_id
                  FROM core_structure s
            )
            UPDATE core_structure s
               SET tract_id = best.tract_id
              FROM best
             WHERE best.structure_id = s.id
               AND s.tract_id IS DISTINCT FROM best.tract_id
            """,
            [MIN_TRACT_SHARE],
        )
        return cursor.rowcount
