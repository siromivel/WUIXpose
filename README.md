# WUIXpose

[![CI](https://github.com/siromivel/wuixpose/actions/workflows/ci.yaml/badge.svg)](https://github.com/siromivel/wuixpose/actions/workflows/ci.yaml)

Wildfire mitigation insight for homes in the wildland-urban interface (WUI), built from public
satellite imagery (Sentinel-2).

## Domain model

- **Tract**: any defined area of land under management on which mitigation can be performed or
  delegated. For the MVP, a residential lot. County parcel numbers (APNs) are stored separately
  as `TractIdentifier` rows, because they change over time and a tract can have several or none.
- **Structure**: a building, identified by its footprint, usually within one tract.
- **Zone**: a ring around a structure at a set distance from its footprint: zone 1 is 0–5 ft,
  zone 2 is 5–30 ft and zone 3 is 30–100 ft. The rings are defined in code (`RINGS` in
  `core/zones.py`) and stored per structure. Zones aren't clipped to tract boundaries, since a
  structure's outer rings often extend onto neighboring land, nor to each other, so the zones of
  nearby structures overlap. The map shades each spot once, as the zone nearest its own structure:
  ground 5 ft from one building and 50 ft from another shows as zone 1.

## Data

`manage.py ingest_boulder` loads two Boulder County layers, both published under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/):

- [Parcels](https://opendata-bouldercounty.hub.arcgis.com/datasets/parcels) (countywide, Assessor's
  Office) become tracts, keyed by parcel number. Features sharing a parcel number are merged.
- [Building footprints](https://gis-bouldercounty.opendata.arcgis.com/datasets/648641d4e2a94a7abb967d507814e959_0)
  (unincorporated county only, Land Use) become structures, keyed by the county's structure ID.
  Demolished footprints are skipped.

Re-running updates geometry in place. A parcel number is tracked from the day it was first loaded
(`tracked_from`), which is WUIXpose's date, not the county's date of record. Parcels or structures
that disappear from the county data are not yet removed or retired.

A structure is assigned to the tract holding at least 90% of its footprint, and left without one
otherwise. `manage.py assign_structure_tracts` does the assignment and reconsiders only structures
whose own geometry, or a nearby tract's, changed since its last run; database triggers record those
changes (`geom_updated_at`) whatever writes them. The ingest runs it when it finishes. Pass `--full`
to reconsider everything, e.g. after changing the 90% rule.

`manage.py build_zones` draws each structure's zones, redrawing only those whose footprint changed
since its last run. The ingest runs it too. To change the rings, edit `RINGS` and bump
`RULE_VERSION`: the next run builds every structure's zones under the new version and keeps the
old rows, and the map serves the new ones.

## Stack

Python 3.13, Django 5.2 with GeoDjango, Django REST Framework, PostgreSQL 17 + PostGIS, Redis,
managed with [uv](https://docs.astral.sh/uv/). The map UI is React + TypeScript with
[MapLibre GL JS](https://maplibre.org/), built with Vite. Map shapes reach the browser as vector
tiles that PostGIS builds (`ST_AsMVT`) and Django serves.

## Local development

Prerequisites: uv, Node 22, Docker, and the GDAL/GEOS libraries that GeoDjango loads
(`brew install gdal` on macOS, `apt install gdal-bin` on Debian/Ubuntu).

```bash
cp .env.example .env     # local settings: DEBUG on, defaults matching compose.yaml
docker compose up -d     # Postgres/PostGIS on :5432, Redis on :6379
uv sync                  # create .venv and install dependencies

cd src/wuixpose
uv run python manage.py migrate
uv run python manage.py runserver
```

Check that it's up: `curl localhost:8000/health/` should return `{"status": "ok"}`.

Load map data (in another terminal, from `src/wuixpose`). The whole county takes a while; a bounding box (WGS 84
`min_lon,min_lat,max_lon,max_lat`) loads one area, for example around Gold Hill and Sunshine
Canyon:

```bash
uv run python manage.py ingest_boulder --bbox=-105.45,40.03,-105.30,40.09
uv run python manage.py ingest_boulder        # everything
```

Then start the map UI, which proxies `/api` and `/tiles` to Django on :8000:

```bash
cd frontend
npm install
npm run dev              # http://localhost:5173
```

Lot lines appear from zoom 12, structures from zoom 13 and zones from zoom 15.

## API

| Path | Returns |
| --- | --- |
| `/tiles/{tracts,structures,zones}.json` | [TileJSON](https://github.com/mapbox/tilejson-spec/tree/master/3.0.0): tile URL template, zoom range, attribution, feature properties |
| `/tiles/{tracts,structures,zones}/{z}/{x}/{y}.mvt` | Vector tiles; feature ids are model ids. Zone tiles hold every structure's rings, overlaps included |
| `/api/summary/` | Counts and the bounding box of loaded tracts |
| `/api/tracts/<id>/` | County parcel numbers, acreage, structure ids |
| `/api/structures/<id>/` | Source ID, tract and its county parcel numbers, footprint square feet |

Map clients should read a layer's TileJSON rather than hardcode its URL or zoom range; the
frontend does. Layers are defined in one place, `LAYERS` in `core/tiles.py`.

## Configuration

Settings come from environment variables, with `.env` at the repo root filling in any that
aren't set. `.env.example` lists them all.

- `DJANGO_DEBUG` defaults to off. With it off, `DJANGO_SECRET_KEY` is required and
  `DJANGO_ALLOWED_HOSTS` (comma-separated) defaults to none.
- `POSTGRES_*` and `REDIS_URL` default to the `compose.yaml` services.
- `WUIXPOSE_TILE_CACHE_SECONDS` sets `Cache-Control` on tiles and TileJSON (default 300).
- `WUIXPOSE_INGEST_USER_AGENT` identifies ingest requests to county GIS servers.

The frontend reads `VITE_*` variables at build time for the basemap style, imagery tiles and
default map center; `frontend/.env.example` lists them, and `frontend/src/config.ts` holds the
defaults.

## Checks

Run these from the repo root. CI runs the same ones on every push to `main` and every pull request.

```bash
uv run ruff check                                                     # lint
uv run pytest                                                         # tests (needs the database)
(cd src/wuixpose && uv run python manage.py makemigrations --check --dry-run)  # migrations match models
(cd frontend && npm run lint && npm run build)                        # frontend lint, types, bundle
```

## Layout

```
src/wuixpose/
  config/   settings, URLs, ASGI/WSGI
  core/     models (tracts, structures, zones), migrations
    ingest/   ArcGIS REST client, geometry cleanup, Boulder County loaders
    zones.py  ring definitions and the job that draws them
    tiles.py  vector tiles
    api.py    JSON endpoints
frontend/   React + MapLibre map UI
```
