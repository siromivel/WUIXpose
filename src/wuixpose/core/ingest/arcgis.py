"""Read features from an ArcGIS REST MapServer/FeatureServer layer, one page at a time."""

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from typing import Any

from django.conf import settings

logger = logging.getLogger(__name__)

FetchJson = Callable[[str, dict[str, str]], dict[str, Any]]


class ArcGISError(RuntimeError):
    pass


def fetch_json(url: str, params: dict[str, str], *, attempts: int = 3, timeout: float = 120) -> dict[str, Any]:
    """GET url?params as JSON, retrying transient network errors with backoff."""
    full_url = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(full_url, headers={"User-Agent": settings.WUIXPOSE_INGEST_USER_AGENT})
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = json.load(response)
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == attempts:
                raise ArcGISError(f"{url}: {exc}") from exc
            wait = 2**attempt
            logger.warning("%s failed (%s), retrying in %ss", url, exc, wait)
            time.sleep(wait)
            continue
        # ArcGIS reports query errors with HTTP 200 and an "error" object.
        if "error" in body:
            raise ArcGISError(f"{url}: {body['error']}")
        return body
    raise AssertionError("unreachable")


def iter_features(
    layer_url: str,
    *,
    where: str = "1=1",
    out_fields: tuple[str, ...] = ("*",),
    bbox: tuple[float, float, float, float] | None = None,
    page_size: int = 2000,
    fetch: FetchJson = fetch_json,
) -> Iterator[dict[str, Any]]:
    """Yield GeoJSON features (lon/lat, SRID 4326) from a layer, paging by OBJECTID.

    bbox is (min_lon, min_lat, max_lon, max_lat) and keeps features that intersect it.
    The server reprojects to 4326 itself (outSR), so no client-side transform is needed.
    """
    params = {
        "where": where,
        "outFields": ",".join(out_fields),
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "geojson",
        # A stable order is required for offset paging to neither skip nor repeat rows.
        "orderByFields": "OBJECTID",
        "resultRecordCount": str(page_size),
    }
    if bbox is not None:
        params |= {
            "geometry": ",".join(str(v) for v in bbox),
            "geometryType": "esriGeometryEnvelope",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
        }

    offset = 0
    while True:
        page = fetch(f"{layer_url}/query", params | {"resultOffset": str(offset)})
        features = page.get("features", [])
        yield from features
        offset += len(features)
        # The GeoJSON flavor puts this flag at the top level on some servers and under
        # "properties" on others.
        more = page.get("exceededTransferLimit") or page.get("properties", {}).get("exceededTransferLimit")
        if not features or not more:
            return
