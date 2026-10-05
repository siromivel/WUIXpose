from django.contrib.gis.geos import MultiPolygon, Polygon

from wuixpose.core.models.tracts import STORAGE_SRID

# A spot in the Boulder County foothills; tests build shapes relative to it.
ORIGIN = (-105.40, 40.05)


def box(x0: float, y0: float, x1: float, y1: float) -> list[list[float]]:
    """A closed ring for the rectangle offset from ORIGIN by (x0, y0)-(x1, y1) degrees."""
    ox, oy = ORIGIN
    return [[ox + x0, oy + y0], [ox + x1, oy + y0], [ox + x1, oy + y1], [ox + x0, oy + y1], [ox + x0, oy + y0]]


def feature(props: dict, *rings: list[list[float]]) -> dict:
    """A GeoJSON Feature: one ring is a Polygon, several are a MultiPolygon."""
    if len(rings) == 1:
        geometry = {"type": "Polygon", "coordinates": [rings[0]]}
    else:
        geometry = {"type": "MultiPolygon", "coordinates": [[r] for r in rings]}
    return {"type": "Feature", "geometry": geometry, "properties": props}


def multipolygon(ring: list[list[float]]) -> MultiPolygon:
    return MultiPolygon(Polygon(ring), srid=STORAGE_SRID)
