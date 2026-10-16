# WUIXpose

[![CI](https://github.com/siromivel/wuixpose/actions/workflows/ci.yaml/badge.svg)](https://github.com/siromivel/wuixpose/actions/workflows/ci.yaml)

Wildfire mitigation insight for homes in the wildland-urban interface (WUI), built from public
satellite imagery (Sentinel-2).

## Domain model

- **Tract**: any defined area of land under management on which mitigation can be performed or
  delegated. For the MVP, a residential lot. County parcel numbers (APNs) are stored separately
  as `TractIdentifier` rows, because they change over time and a tract can have several or none.
- **Structure**: a building, identified by its footprint, usually within one tract.
- **Address**: a site address (number, street, unit) at a point, as the county's addressing
  authority keeps it. Belongs to a tract; a lot can have many (an apartment complex) or none.
- **Zone**: a ring around a structure at a set distance from its footprint: zone 1 is 0–5 ft,
  zone 2 is 5–30 ft and zone 3 is 30–100 ft. The rings are defined in code (`RINGS` in
  `core/zones.py`) and stored per structure. Zones aren't clipped to tract boundaries, since a
  structure's outer rings often extend onto neighboring land, nor to each other, so the zones of
  nearby structures overlap. The map shades each spot once, as the zone nearest its own structure:
  ground 5 ft from one building and 50 ft from another shows as zone 1.

## Data

`manage.py ingest_boulder` loads three Boulder County layers, all published under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/):

- [Parcels](https://opendata-bouldercounty.hub.arcgis.com/datasets/parcels) (countywide, Assessor's
  Office) become tracts, keyed by parcel number. Features sharing a parcel number are merged.
- [Building footprints](https://gis-bouldercounty.opendata.arcgis.com/datasets/648641d4e2a94a7abb967d507814e959_0)
  (unincorporated county only, Land Use) become structures, keyed by the county's structure ID.
  Demolished footprints are skipped.
- [Address points](https://opendata-bouldercounty.hub.arcgis.com/datasets/687530b74ad54686a98f50337574596f)
  (countywide, Assessor's Office) become addresses, keyed by the county's address ID. Only active
  addresses with a house number and street are loaded. The county notes a backlog of new
  developments not yet addressed.

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

An address belongs to the tract currently carrying the county parcel number on the address record.
When no tract does (about 3% of addresses, mostly where the county replatted and the address
kept the old number), it belongs to the one tract under its point, if exactly one; stacked condo
parcels under a point leave it without one. The parcel number comes first because rural address
points can sit on a neighbor's lot at the driveway. Every ingest relinks all addresses (about a
second for the whole county). Addresses aren't linked to structures yet.

Retired addresses are kept, with `tracked_to` set to the day an ingest found them retired, and left
out of the API. The county marks some `RETIRED` but deletes most outright, so a countywide ingest
(no `--bbox`) also retires every address missing from the layer. That fetch is checked against the
server's count first, so a short response fails the ingest rather than retiring what it missed. An
address that reappears is current again. Retired addresses keep their last details and tract.

Addresses carry the county's jurisdiction ("Unincorporated Boulder County", "Longmont"), not the
USPS mailing city, which the county layer doesn't publish: a Gold Hill address shows as
unincorporated though its mail goes to Boulder.

### Address search

`/api/search/?q=` finds current addresses from what a person types, tolerating typos, partial input
and different spellings. Each address stores a `search_text`: its number, street, unit,
jurisdiction, state and ZIP, normalized (`core/search.py`). Queries are normalized the same way, so
"South Boulder Road" and "S BOULDER RD" are the same words on both sides:

- Spelled-out directionals, street types and ordinals become the county's abbreviations ("NORTH" →
  "N", "AVENUE" → "AVE", "SECOND" → "2ND"), as do "MOUNT", "SAINT" and "FORT". "CR" becomes
  "COUNTY RD".
- Unit designators are dropped, so "#206", "APT 206", "UNIT 206" and "STE 206" all match.
- Apostrophes and periods are removed and other punctuation splits words.

The word table and its test cases (`core/tests/test_search.py`) are the spec. Matching is
Postgres trigram word similarity (`pg_trgm`, GIN-indexed), with a boost for addresses whose house
number starts with the number typed. Queries under three characters return nothing. The ingest
writes `search_text` and rewrites it whenever it differs, so a change to the normalization reaches
stored addresses on the next ingest. A bounding-box ingest only reaches addresses in its box.

The jurisdiction is in `search_text`, so a mailing city can still match: "1172 Valley Ln, Boulder,
CO 80302" finds the unincorporated address. A side effect is that "boulder" matches most of the
county, which makes broad queries like "south boulder road" take a few hundred milliseconds
instead of one or two.

The county has a few addresses that are exact duplicates (separate address points with the same
number, street, unit and parcel). Search returns each of them.

## Stack

Python, Django 5.2 with GeoDjango, Django REST Framework, PostgreSQL 17 + PostGIS and Redis,
with dependencies managed by [uv](https://docs.astral.sh/uv/). The map UI is React + TypeScript
with [MapLibre GL JS](https://maplibre.org/), built with Vite. Map shapes reach the browser as
vector tiles that PostGIS builds (`ST_AsMVT`) and Django serves. [mise](https://mise.jdx.dev/)
pins the Python and Node versions (`mise.toml`) and defines the project's tasks.

## Local development

Prerequisites: mise, uv, Docker and the GDAL/GEOS libraries that GeoDjango loads
(`brew install gdal` on macOS, `apt install gdal-bin` on Debian/Ubuntu). mise installs Python and
Node.

```bash
cp .env.example .env     # local settings: DEBUG on, defaults matching compose.yaml
mise install             # Python and Node, at the versions in mise.toml
mise run setup           # Python and frontend dependencies
mise run migrate         # starts Postgres/PostGIS (:5432) and Redis (:6379), then migrates
mise run dev             # Django on :8000
```

Check that it's up: `curl localhost:8000/health/` should return `{"status": "ok"}`.

`mise tasks` lists every task. Tasks that need the database (`dev`, `migrate`, `migrations-check`,
`test`) start it first and wait until it's healthy; `mise run db` starts it on its own.

Load map data (in another terminal, from `src/wuixpose`). The whole county takes a while; a bounding box (WGS 84
`min_lon,min_lat,max_lon,max_lat`) loads one area, for example around Gold Hill and Sunshine
Canyon:

```bash
uv run python manage.py ingest_boulder --bbox=-105.45,40.03,-105.30,40.09
uv run python manage.py ingest_boulder        # everything
```

Then start the map UI, which proxies `/api` and `/tiles` to Django on :8000:

```bash
mise run dev-frontend    # http://localhost:5173
```

Lot lines appear from zoom 12, structures from zoom 13 and zones from zoom 15. The search box in
the panel finds an address, flies the map there and selects its lot.

## API

| Path | Returns |
| --- | --- |
| `/tiles/{tracts,structures,zones}.json` | [TileJSON](https://github.com/mapbox/tilejson-spec/tree/master/3.0.0): tile URL template, zoom range, attribution, feature properties |
| `/tiles/{tracts,structures,zones}/{z}/{x}/{y}.mvt` | Vector tiles; feature ids are model ids. Zone tiles hold every structure's rings, overlaps included |
| `/api/summary/` | Counts and the bounding box of loaded tracts |
| `/api/tracts/<id>/` | Addresses, county parcel numbers, acreage, structure ids |
| `/api/structures/<id>/` | Source ID, tract and its addresses and county parcel numbers, footprint square feet |
| `/api/search/?q=` | Up to 10 current addresses best matching `q`, best first, each with its point and tract (see [Address search](#address-search)) |

Map clients should read a layer's TileJSON rather than hardcode its URL or zoom range; the
frontend does. Layers are defined in one place, `LAYERS` in `core/tiles.py`.

The frontend checks every response against its expected shape before using it (`frontend/src/api.ts`,
built from the checks in `frontend/src/validate.ts`). A response that doesn't match fails with a
message naming the field, rather than breaking somewhere later in the UI.

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

`mise run check` runs everything CI runs on every push to `main` and every pull request. Each
check is also its own task, and CI runs these same tasks, starting the database from
`compose.yaml` as local development does:

```bash
mise run lint              # Python lint (ruff)
mise run typecheck         # Python types (pyright)
mise run migrations-check  # migrations match models (starts the database)
mise run test              # Python tests (starts the database)
mise run frontend-check    # frontend lint, types and bundle
mise run frontend-test     # frontend tests (Vitest)
```

## Layout

```
src/wuixpose/
  config/   settings, URLs, ASGI/WSGI
  core/     models (tracts, structures, addresses, zones), migrations
    ingest/   ArcGIS REST client, geometry cleanup, Boulder County loaders
    zones.py  ring definitions and the job that draws them
    tiles.py  vector tiles
    search.py address normalization and search
    display.py address formatting for display
    api.py    JSON endpoints
frontend/   React + MapLibre map UI
```
