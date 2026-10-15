# WUIXpose

Wildfire-risk exposure tool for WUI properties. Django (Python) backend,
Node [frontend/tooling], Postgres + PostGIS. Favor boring, simple solutions;
don't add dependencies or abstractions without asking.

<!-- Human note: task names below assume mise.toml defines dev, test, lint and setup.
     Adjust to match. HTML comments like this are stripped before agents see them. -->

## Tooling
- mise manages tool versions (Python, uv, Node) and env vars via `mise.toml`.
  Don't install tools globally or change versions directly; update `mise.toml`.
- uv manages Python dependencies and the virtualenv.
  - Add packages with `uv add <pkg>` (or `uv add --dev <pkg>`). Never use `pip install`.
  - Never edit `uv.lock` by hand.
- Node dependencies: [`npm install <pkg>`]. Never edit the lockfile by hand.
- Env vars (e.g. `DATABASE_URL`) come from mise. Never hardcode them.

## Commands
Prefer mise tasks for project workflows:
- Setup: `mise install`, then `mise run setup`
- Dev server: `mise run dev`
- Tests: `mise run test` (run before every commit)
- Lint/format: `mise run lint`

For one-off Python commands, use `uv run`:
- `uv run python manage.py <command>`
- `uv run pytest -k <pattern>` to run a subset of tests
- `uv run python --version` to check the environment

If a tool isn't on PATH, use `mise exec -- <command>`.

## Shell usage
- Run one simple command per call. Avoid compound bash chains (`&&`, `;`, pipes
  into further logic) and command substitutions like `$()`.
- Run tools explicitly or via `uv run` / `mise run` rather than through wrapper
  scripts or inline shell tricks.

## Database
- Local dev DB only. Never connect to or run commands against any non-local database.
- Never edit a migration that has already been applied; add a new one.
- `uv run python manage.py makemigrations --check` must pass before committing.
- Never drop tables or run destructive SQL without asking first.

## Geospatial (PostGIS / GeoDjango)
- Store geometries in EPSG:4326. Coordinates are (lon, lat), not (lat, lon).
- For distance, area or buffers, use geography types or transform to a projected
  CRS (EPSG:32613, UTM 13N, for Colorado). Never measure in degrees.
- Use `ST_DWithin` (index-friendly) for proximity filters, not `ST_Distance < x`.
- Every geometry column used in spatial queries needs a GiST index.

## Conventions

### General
- Keep changes small and focused. Don't refactor or reformat unrelated code.
- Add or update tests with every behavior change. Bug fixes get a regression test.
- Comments explain *why*, not *what*.
- Never commit secrets, credentials or `.env` files.
- Small, focused commits with descriptive messages.

### Python / Django
- Follow PEP 8 naming. Formatting and linting come from `mise run lint`; don't hand-format.
- Type hints on all function signatures; avoid `Any` unless unavoidable.
- Keep views and models thin. Business logic goes in plain service functions,
  not in views or model methods.
- Service functions live in each app's `services/` package: one module per model
  for entity logic (`services/tracts.py`), plus use-case modules for workflows
  spanning several models (`services/exposure_assessment.py`).
- Use the ORM. Raw SQL only when GeoDjango can't express a PostGIS query,
  and always parameterized, never string-formatted.
- Avoid N+1 queries: use `select_related` / `prefetch_related` when iterating relations.
- Datetimes are timezone-aware (`USE_TZ = True`); use `django.utils.timezone.now()`.
- Settings come from env vars, never hardcoded per environment.
- Tests use pytest; prefer small, fast unit tests over broad end-to-end ones.

### Node / TypeScript
- TypeScript in strict mode. No `any`; use `unknown` and narrow.
- ES modules, `const` by default, `async`/`await` over raw promise chains.
- Prefer named exports over default exports.
- Validate external data (API responses, user input) at the boundary.

## Gotchas
<!-- Add entries here as agents trip over things. -->
