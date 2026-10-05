"""Mapbox Vector Tiles built by PostGIS (ST_AsMVT), one layer per tile request.

Geometries are stored in 4326 and tiles are in Web Mercator (3857). Each layer filters with the
tile envelope transformed to 4326, rather than transforming every row to 3857, so the GiST index
on geom finds the candidate rows.
"""

from dataclasses import dataclass

from django.db import connection
from django.http import Http404, HttpResponse
from django.views.decorators.http import require_GET

MVT_CONTENT_TYPE = "application/vnd.mapbox-vector-tile"
MAX_ZOOM = 22

# Placeholders for layer SQL. Every non-geometry column a layer selects becomes a tile property.
ENVELOPE_4326 = "ST_Transform(ST_TileEnvelope(%(z)s, %(x)s, %(y)s), 4326)"
MVT_GEOM = "ST_AsMVTGeom(ST_Transform({col}, 3857), ST_TileEnvelope(%(z)s, %(x)s, %(y)s), 4096, 64, true)"


@dataclass(frozen=True)
class TileLayer:
    # Below this zoom a tile would carry thousands of polygons too small to see.
    min_zoom: int
    sql: str


LAYERS = {
    "tracts": TileLayer(
        min_zoom=12,
        sql=f"""
            SELECT t.id,
                   (SELECT i.value
                      FROM core_tractidentifier i
                     WHERE i.tract_id = t.id AND i.scheme = 'county_apn' AND i.valid_to IS NULL
                     ORDER BY i.id
                     LIMIT 1) AS apn,
                   {MVT_GEOM.format(col="t.geom")} AS mvt_geom
              FROM core_tract t
             WHERE t.geom && {ENVELOPE_4326}
        """,
    ),
    "structures": TileLayer(
        min_zoom=13,
        sql=f"""
            SELECT s.id, s.tract_id, {MVT_GEOM.format(col="s.geom")} AS mvt_geom
              FROM core_structure s
             WHERE s.geom && {ENVELOPE_4326}
        """,
    ),
}


def render_tile(layer_name: str, z: int, x: int, y: int) -> bytes:
    sql = f"""
        SELECT ST_AsMVT(rows, %(layer)s, 4096, 'mvt_geom', 'id')
          FROM ({LAYERS[layer_name].sql}) rows
         WHERE rows.mvt_geom IS NOT NULL
    """
    with connection.cursor() as cursor:
        cursor.execute(sql, {"z": z, "x": x, "y": y, "layer": layer_name})
        (tile,) = cursor.fetchone()
    return bytes(tile or b"")


@require_GET
def tile(request, layer: str, z: int, x: int, y: int):
    if layer not in LAYERS or z > MAX_ZOOM or x >= 2**z or y >= 2**z:
        raise Http404
    if z < LAYERS[layer].min_zoom:
        return HttpResponse(status=204)

    body = render_tile(layer, z, x, y)
    if not body:
        return HttpResponse(status=204)
    response = HttpResponse(body, content_type=MVT_CONTENT_TYPE)
    # Data only changes when an ingest runs.
    response["Cache-Control"] = "public, max-age=300"
    return response
