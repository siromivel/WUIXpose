"""Mapbox Vector Tiles built by PostGIS (ST_AsMVT), one layer per tile request, plus a TileJSON
document per layer describing them.

The TileJSON is the contract with map clients: tile URL template, zoom range, attribution and
the properties each feature carries. Clients read it rather than hardcoding any of that.

Geometries are stored in STORAGE_SRID and tiles are in Web Mercator. Each layer filters with the
tile envelope transformed to STORAGE_SRID, rather than transforming every row to Web Mercator, so
the GiST index on geom finds the candidate rows.
"""

from dataclasses import dataclass

from django.conf import settings
from django.db import connection
from django.http import Http404, HttpResponse, JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_GET

from wuixpose.core import zones
from wuixpose.core.constants import (
    BOULDER_COUNTY_ATTRIBUTION,
    STORAGE_SRID,
    WEB_MERCATOR_SRID,
)
from wuixpose.core.models.tracts import TractIdentifier

MVT_CONTENT_TYPE = "application/vnd.mapbox-vector-tile"

# Placeholders for layer SQL, filled from render_tile's parameters. Every non-geometry column a
# layer selects becomes a tile property.
ENVELOPE_STORAGE = "ST_Transform(ST_TileEnvelope(%(z)s, %(x)s, %(y)s), %(storage_srid)s)"
MVT_GEOM = "ST_AsMVTGeom(ST_Transform({col}, %(web_mercator_srid)s), ST_TileEnvelope(%(z)s, %(x)s, %(y)s), 4096, 64, true)"


@dataclass(frozen=True)
class TileLayer:
    description: str
    # Below min_zoom a tile would carry thousands of polygons too small to see. Above max_zoom
    # clients overzoom the max_zoom tiles, which already hold full-detail geometry.
    min_zoom: int
    max_zoom: int
    # Feature properties and their TileJSON types (String, Number or Boolean), matching `sql`.
    fields: dict[str, str]
    attribution: str
    sql: str


LAYERS = {
    "tracts": TileLayer(
        description="Tracts: areas of land on which mitigation can be performed or delegated",
        min_zoom=12,
        max_zoom=16,
        fields={"apn": "String"},
        attribution=BOULDER_COUNTY_ATTRIBUTION,
        sql=f"""
            SELECT t.id,
                   (SELECT i.value
                      FROM core_tractidentifier i
                     WHERE i.tract_id = t.id AND i.scheme = %(apn_scheme)s AND i.tracked_to IS NULL
                     ORDER BY i.id
                     LIMIT 1) AS apn,
                   {MVT_GEOM.format(col="t.geom")} AS mvt_geom
              FROM core_tract t
             WHERE t.geom && {ENVELOPE_STORAGE}
        """,
    ),
    "structures": TileLayer(
        description="Structures: building footprints",
        min_zoom=13,
        max_zoom=16,
        fields={"tract_id": "Number"},
        attribution=BOULDER_COUNTY_ATTRIBUTION,
        sql=f"""
            SELECT s.id, s.tract_id, {MVT_GEOM.format(col="s.geom")} AS mvt_geom
              FROM core_structure s
             WHERE s.geom && {ENVELOPE_STORAGE}
        """,
    ),
    "zones": TileLayer(
        description="Zones: rings around each structure at set distances from its footprint",
        # A 100 ft ring is only a few pixels wide below this.
        min_zoom=15,
        max_zoom=16,
        fields={"structure_id": "Number", "tract_id": "Number", "ring_key": "String"},
        # Drawn from the county's footprints.
        attribution=BOULDER_COUNTY_ATTRIBUTION,
        sql=f"""
            SELECT z.id, z.structure_id, s.tract_id, z.ring_key, {MVT_GEOM.format(col="z.geom")} AS mvt_geom
              FROM core_zone z
              JOIN core_structure s ON s.id = z.structure_id
             WHERE z.rule_version = %(rule_version)s
               AND z.geom && {ENVELOPE_STORAGE}
        """,
    ),
}


def _cacheable(response: HttpResponse) -> HttpResponse:
    response["Cache-Control"] = f"public, max-age={settings.WUIXPOSE_TILE_CACHE_SECONDS}"
    return response


def _get_layer(name: str) -> TileLayer:
    try:
        return LAYERS[name]
    except KeyError:
        raise Http404 from None


def render_tile(layer_name: str, z: int, x: int, y: int) -> bytes:
    sql = f"""
        SELECT ST_AsMVT(rows, %(layer)s, 4096, 'mvt_geom', 'id')
          FROM ({LAYERS[layer_name].sql}) rows
         WHERE rows.mvt_geom IS NOT NULL
    """
    with connection.cursor() as cursor:
        cursor.execute(
            sql,
            {
                "z": z,
                "x": x,
                "y": y,
                "layer": layer_name,
                "storage_srid": STORAGE_SRID,
                "web_mercator_srid": WEB_MERCATOR_SRID,
                "rule_version": zones.RULE_VERSION,
                "apn_scheme": TractIdentifier.Scheme.COUNTY_APN,
            },
        )
        row = cursor.fetchone()
        assert row is not None  # an aggregate without GROUP BY always returns a row
        (tile,) = row
    return bytes(tile or b"")


@require_GET
def tile(request, layer: str, z: int, x: int, y: int):
    spec = _get_layer(layer)
    if z > spec.max_zoom or x >= 2**z or y >= 2**z:
        raise Http404
    if z < spec.min_zoom:
        return HttpResponse(status=204)

    body = render_tile(layer, z, x, y)
    if not body:
        return HttpResponse(status=204)
    return _cacheable(HttpResponse(body, content_type=MVT_CONTENT_TYPE))


@require_GET
def tilejson(request, layer: str):
    """TileJSON 3.0.0 for one layer: https://github.com/mapbox/tilejson-spec/tree/master/3.0.0"""
    spec = _get_layer(layer)
    # Built from the URL pattern so a route change can't leave the template stale. The host
    # comes from the request, so behind the Vite dev proxy it is the proxy's.
    sample = reverse("tile", kwargs={"layer": layer, "z": 0, "x": 0, "y": 0})
    template = request.build_absolute_uri(sample).replace("/0/0/0.mvt", "/{z}/{x}/{y}.mvt")
    return _cacheable(
        JsonResponse(
            {
                "tilejson": "3.0.0",
                "name": layer,
                "description": spec.description,
                "tiles": [template],
                "minzoom": spec.min_zoom,
                "maxzoom": spec.max_zoom,
                "attribution": spec.attribution,
                "vector_layers": [
                    {
                        "id": layer,
                        "fields": spec.fields,
                        "minzoom": spec.min_zoom,
                        "maxzoom": spec.max_zoom,
                    }
                ],
            }
        )
    )
