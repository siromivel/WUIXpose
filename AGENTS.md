# WUIXpose

Wildfire mitigation insight for homes in the wildland-urban interface. Django + GeoDjango backend
on Postgres/PostGIS, with a React + TypeScript + MapLibre map UI in `frontend/` built with Vite.
Favor boring, simple solutions; don't add dependencies or abstractions without asking.

`README.md` is the source of truth for the domain model and data rules. When you change how
something behaves, update the README in the same change.

## Tooling
- mise pins the Python and Node versions (`mise.toml`) and defines the project's tasks.
  Don't install tools globally or change versions directly; update `mise.toml`.
- uv manages Python dependencies and the virtualenv.
  - Add packages with `uv add <pkg>` (or `uv add --dev <pkg>`). Never use `pip install`.
  - Never edit `uv.lock` by hand.
- npm manages frontend dependencies, from `frontend/`. Never edit `package-lock.json` by hand.
- Settings come from environment variables, with `.env` at the repo root filling in any that
  aren't set (django-environ). `.env.example` lists them all. Never hardcode settings or secrets.

## Commands
Use mise tasks (`mise tasks` lists them). They run from the right directory and start the
database when they need it.
- Setup: `mise install`, then `mise run setup`
- Database only: `mise run db`; migrations: `mise run migrate`
- Dev servers: `mise run dev` (Django, :8000) and `mise run dev-frontend` (map UI, :5173)
- Before every commit: `mise run check` (everything CI runs)
- Individual checks: `mise run lint`, `typecheck`, `migrations-check`, `test`, `frontend-check`

One-off commands:
- `manage.py` lives in `src/wuixpose`, so run `uv run python manage.py <command>` from there.
- Run `uv run pytest -k <pattern>` from the repo root for a subset of tests.
- Load a small area of map data rather than the whole county:
  `uv run python manage.py ingest_boulder --bbox=-105.45,40.03,-105.30,40.09`

If a tool isn't on PATH, use `mise exec -- <command>`.

## Shell usage
- Run one simple command per call. Avoid compound bash chains (`&&`, `;`, pipes
  into further logic) and command substitutions like `$()`.
- Run tools explicitly or via `uv run` / `mise run` rather than through wrapper
  scripts or inline shell tricks.

## Database
- Local dev DB only (from `compose.yaml`). Never connect to or run commands against any
  non-local database.
- Never edit a migration that has already been applied; add a new one.
- `mise run migrations-check` must pass before committing.
- Never drop tables or run destructive SQL without asking first.
- `geom_updated_at` columns are maintained by database triggers (migration 0003). Never set
  them from Python; jobs rely on the triggers to find changed geometry.

## Geospatial (PostGIS / GeoDjango)
- Geometries are stored in SRID 4326 as (lon, lat), not (lat, lon). Use the `STORAGE_SRID`
  constant from `core/models/tracts.py`; don't hardcode 4326.
- Never buffer or measure directly on stored geometries; their units are degrees.
  - Distances and buffers: cast to `geography`, which works in meters (as `core/zones.py` does).
  - Areas: transform to equal-area EPSG:5070 (as `core/api.py` does).
  - Tests can verify distances in UTM 13N (EPSG:32613), as `test_zones.py` does.
- Keep spatial filters index-friendly: `ST_DWithin` rather than `ST_Distance < x`, and transform
  the query shape (e.g. a tile envelope) to 4326 rather than transforming every row
  (as `core/tiles.py` does).
- Zone rings live in `RINGS` in `core/zones.py`. Changing them means bumping `RULE_VERSION`.
- Tile layers are defined in `LAYERS` in `core/tiles.py`. The frontend reads each layer's
  TileJSON; never hardcode tile URLs or zoom ranges in the frontend.

## Conventions

### General
- Keep changes small and focused. Don't refactor or reformat unrelated code.
- Add or update tests with every behavior change. Bug fixes get a regression test.
- Comments explain *why*, not *what*.
- Never commit secrets, credentials or `.env` files.
- Small, focused commits with descriptive messages.

### Python / Django
- Follow PEP 8 naming. Ruff lints (`mise run lint`); pyright checks types (`mise run typecheck`).
- Type hints on all function signatures; avoid `Any` unless unavoidable.
- Business logic goes in plain service functions, not in views, model methods or management
  commands. Commands stay thin wrappers (see `build_zones`).
- Service functions live in feature modules under `core/`: `zones.py`, `tiles.py`, `ingest/`.
  Add a new module for a new feature rather than growing an unrelated one.
- Use the ORM. Raw SQL only when GeoDjango can't express a PostGIS query,
  and always parameterized, never string-formatted.
- Avoid N+1 queries: use `select_related` / `prefetch_related` when iterating relations.
- Datetimes are timezone-aware; use `django.utils.timezone.now()`.
- Tests use pytest with pytest-django; build data with `core/tests/factories.py`.
  Prefer small, fast tests over broad end-to-end ones.

### Frontend (TypeScript / React)
- TypeScript runs in strict mode. Don't loosen compiler options to get past an error; fix the types.
- No `any`; use `unknown` and narrow.
- ES modules, `const` by default, `async`/`await` over raw promise chains.
- Prefer named exports (Vite's `App.tsx` and config files are the exceptions).
- Validate external data (API responses, user input) at the boundary.
- Build-time settings come from `VITE_*` variables, with defaults in `frontend/src/config.ts`.

## Gotchas
<!-- Add entries here as agents trip over things. -->
