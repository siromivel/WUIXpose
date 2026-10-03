# WUIXpose

[![CI](https://github.com/siromivel/wuixpose/actions/workflows/ci.yml/badge.svg)](https://github.com/siromivel/wuixpose/actions/workflows/ci.yml)

Wildfire mitigation insight for homes in the wildland-urban interface (WUI), built from public
satellite imagery (Sentinel-2).

## Domain model

- **Tract**: any defined area of land under management on which mitigation can be performed or
  delegated. For the MVP, a residential lot. County parcel numbers (APNs) are stored separately
  as `TractIdentifier` rows, because they change over time and a tract can have several or none.
- **Structure**: a building, identified by its footprint, usually within one tract.
- **Zone**: a ring around a structure (for example 0–5 ft from the footprint), computed in code.
  Zones aren't clipped to tract boundaries, since a structure's outer rings often extend onto
  neighboring land.

## Stack

Python 3.13, Django 5.2 with GeoDjango, Django REST Framework, PostgreSQL 17 + PostGIS, Redis,
managed with [uv](https://docs.astral.sh/uv/).

## Local development

Prerequisites: uv, Docker, and the GDAL/GEOS libraries that GeoDjango loads
(`brew install gdal` on macOS, `apt install gdal-bin` on Debian/Ubuntu).

```bash
docker compose up -d     # Postgres/PostGIS on :5432, Redis on :6379
uv sync                  # create .venv and install dependencies

cd src/wuixpose
uv run python manage.py migrate
uv run python manage.py runserver
```

Check that it's up: `curl localhost:8000/health/` should return `{"status": "ok"}`.

## Checks

Run these from the repo root. CI runs the same ones on every push to `main` and every pull request.

```bash
uv run ruff check                                                     # lint
uv run pytest                                                         # tests (needs the database)
(cd src/wuixpose && uv run python manage.py makemigrations --check --dry-run)  # migrations match models
```

## Layout

```
src/wuixpose/
  config/   settings, URLs, ASGI/WSGI
  core/     models (tracts, structures), views, migrations
```
