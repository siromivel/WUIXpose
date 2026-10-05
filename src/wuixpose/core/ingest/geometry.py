import json
from collections.abc import Iterable
from typing import Any

from django.contrib.gis.geos import GEOSGeometry, MultiPolygon, Polygon

from wuixpose.core.models.tracts import STORAGE_SRID


def multipolygon_from_geojson(geometry: dict[str, Any] | None) -> MultiPolygon | None:
    """Parse a GeoJSON geometry into a valid MultiPolygon, or None if nothing polygonal is left."""
    if not geometry:
        return None
    geom = GEOSGeometry(json.dumps(geometry), srid=STORAGE_SRID)
    return as_multipolygon([geom])


def as_multipolygon(geoms: Iterable[GEOSGeometry]) -> MultiPolygon | None:
    """Combine polygonal geometries into one valid MultiPolygon.

    County data has self-intersections and duplicate vertices; make_valid can turn those into
    a GeometryCollection holding stray lines or points, which are dropped here.
    """
    polygons: list[Polygon] = []
    for geom in geoms:
        if not geom.valid:
            geom = geom.make_valid()
        polygons.extend(_polygons(geom))
    if not polygons:
        return None
    multi = MultiPolygon(polygons, srid=STORAGE_SRID)
    if len(polygons) > 1 and not multi.valid:
        # Overlapping pieces (one parcel delivered as several touching polygons).
        multi = MultiPolygon(_polygons(multi.unary_union), srid=STORAGE_SRID)
    return multi


def _polygons(geom: GEOSGeometry) -> list[Polygon]:
    if isinstance(geom, Polygon):
        return [geom] if not geom.empty else []
    if geom.geom_type in ("MultiPolygon", "GeometryCollection"):
        return [p for part in geom for p in _polygons(part)]
    return []
