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

from wuixpose.core.constants import STORAGE_SRID

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


def _filter_params(where: str, bbox: tuple[float, float, float, float] | None) -> dict[str, str]:
    params = {"where": where}
    if bbox is not None:
        params |= {
            "geometry": ",".join(str(v) for v in bbox),
            "geometryType": "esriGeometryEnvelope",
            "inSR": str(STORAGE_SRID),
            "spatialRel": "esriSpatialRelIntersects",
        }
    return params


def count_features(
    layer_url: str,
    *,
    where: str = "1=1",
    bbox: tuple[float, float, float, float] | None = None,
    fetch: FetchJson = fetch_json,
) -> int:
    """How many features match where and bbox, as the server counts them."""
    body = fetch(f"{layer_url}/query", _filter_params(where, bbox) | {"returnCountOnly": "true", "f": "json"})
    return int(body["count"])


def iter_features(
    layer_url: str,
    *,
    where: str = "1=1",
    out_fields: tuple[str, ...] = ("*",),
    bbox: tuple[float, float, float, float] | None = None,
    page_size: int = 2000,
    check_count: bool = False,
    fetch: FetchJson = fetch_json,
) -> Iterator[dict[str, Any]]:
    """Yield GeoJSON features (lon/lat, STORAGE_SRID) from a layer, paging by OBJECTID.

    bbox is (min_lon, min_lat, max_lon, max_lat) and keeps features that intersect it.
    The server reprojects to STORAGE_SRID itself (outSR), so no client-side transform is needed.

    With check_count, the server's count is fetched first and ArcGISError raised after the last
    page if the pages didn't add up to it. Paging ends at the first empty or final-looking page, so
    without the check a short response passes for the end of the layer. Use it when a missing
    feature means something, as when a load retires what it didn't see. The layer changing
    mid-fetch also fails the check; running again is the fix.
    """
    params = _filter_params(where, bbox) | {
        "outFields": ",".join(out_fields),
        "returnGeometry": "true",
        "outSR": str(STORAGE_SRID),
        "f": "geojson",
        # A stable order is required for offset paging to neither skip nor repeat rows.
        "orderByFields": "OBJECTID",
        "resultRecordCount": str(page_size),
    }
    expected = count_features(layer_url, where=where, bbox=bbox, fetch=fetch) if check_count else None

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
            break

    if expected is not None and offset != expected:
        raise ArcGISError(f"{layer_url}: got {offset} features but the server counts {expected}")
