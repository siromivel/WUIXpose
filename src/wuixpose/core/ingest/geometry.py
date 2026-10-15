import json
from collections.abc import Iterable
from typing import Any

# The stubs' OGRGeometry predates set_3d and set_measured (Django 5.1), so it's left untyped.
from django.contrib.gis.gdal import (
    GDALException,
    OGRGeometry,  # pyright: ignore[reportAttributeAccessIssue]
)
from django.contrib.gis.geos import (
    GEOSGeometry,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
)
from django.contrib.gis.geos.error import GEOSException

from wuixpose.core.models.tracts import STORAGE_SRID


class UnreadableGeometry(ValueError):
    """GeoJSON that can't be built into a geometry, or that make_valid can't repair."""


def multipolygon_from_geojson(geometry: dict[str, Any] | None) -> MultiPolygon | None:
    """Parse a GeoJSON geometry into a valid 2D MultiPolygon, or None if nothing polygonal is left.

    Raises UnreadableGeometry for what can't be repaired at all, such as unclosed rings, missing
    coordinates or an unknown type, so one bad feature doesn't take down the whole load.
    """
    if not geometry:
        return None
    try:
        ogr = OGRGeometry(json.dumps(geometry), srs=STORAGE_SRID)
        # Geometry columns are 2D; heights or measures from a provider would fail the insert.
        ogr.set_3d(False)
        ogr.set_measured(False)
        return as_multipolygon([ogr.geos])
    except (GDALException, GEOSException, ValueError) as exc:
        raise UnreadableGeometry(f"{type(exc).__name__}: {exc}") from exc


def point_from_geojson(geometry: dict[str, Any] | None) -> Point | None:
    """Parse a GeoJSON Point (or a MultiPoint of one) into a 2D Point, or None if there isn't one.

    Raises UnreadableGeometry for GeoJSON that can't be built into a geometry, as
    multipolygon_from_geojson does.
    """
    if not geometry:
        return None
    try:
        ogr = OGRGeometry(json.dumps(geometry), srs=STORAGE_SRID)
        ogr.set_3d(False)
        ogr.set_measured(False)
        geom = ogr.geos
    except (GDALException, GEOSException, ValueError) as exc:
        raise UnreadableGeometry(f"{type(exc).__name__}: {exc}") from exc
    if isinstance(geom, MultiPoint) and len(geom) == 1:
        geom = geom[0]
    if not isinstance(geom, Point) or geom.empty:
        return None
    return geom


def as_multipolygon(geoms: Iterable[GEOSGeometry]) -> MultiPolygon | None:
    """Combine polygonal geometries into one valid MultiPolygon.

    County data has self-intersections and duplicate vertices; make_valid can turn those into
    a GeometryCollection holding stray lines or points, which are dropped here.
    """
    polygons: list[Polygon] = []
    for geom in geoms:
        if not geom.valid:
            # make_valid (Django 4.1+) is missing from the stubs.
            geom = geom.make_valid()  # pyright: ignore[reportAttributeAccessIssue]
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
