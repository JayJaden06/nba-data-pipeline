# nba-pipeline

[![CI](https://github.com/JayJaden06/nba-data-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/JayJaden06/nba-data-pipeline/actions/workflows/ci.yml)
[![Nightly ingest](https://github.com/JayJaden06/nba-data-pipeline/actions/workflows/nightly.yml/badge.svg)](https://github.com/JayJaden06/nba-data-pipeline/actions/workflows/nightly.yml)

A production-style NBA data pipeline. Every night it pulls the previous day's games from
`nba_api`, validates every record against Pydantic schemas, upserts into Postgres, runs
data-quality checks, and exposes the results through a small FastAPI service.

Built as an internal data product would be: idempotent re-runs, late-data handling,
schema-drift detection, recorded fixtures for tests, and a one-command local setup.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the design decisions.

## Status

| Step | Scope | State |
|------|-------|-------|
| 1 | Scaffolding, Postgres, migrations, scoreboard -> `games` end to end | done |
| 2 | Team and player box scores -> `players`, `team_game_stats`, `player_game_stats` | done |
| 3 | Six quality checks, `ingest_runs`, `quality_results`, `nba-pipeline check` | done |
| 4 | FastAPI read service, seven endpoints | done |
| 5 | CI, Docker image, isolated test database | done |
| 5b | ESPN as a second source; nightly ingest on GitHub Actions into hosted Postgres | done |
| 6 | Season backfill, play-by-play | next |
| 6 | Season backfill, play-by-play | |

## Quick start (about five minutes)

Requirements: Docker, [uv](https://docs.astral.sh/uv/). uv installs Python 3.12 itself.

```bash
git clone <this repo> && cd nba-pipeline
docker compose up -d                 # Postgres 16 on localhost:5432 (nba/nba)
uv sync                              # creates .venv with Python 3.12 and all deps
uv run alembic upgrade head          # creates tables, seeds the 30 NBA teams
uv run nba-pipeline ingest --date 2026-03-15
```

Expected output:

```
2026-03-15 run 1: succeeded
  games        inserted=7 updated=0 unchanged=0 (total=7, teams added=0)
  box scores   loaded=7 failed=0
  players      inserted=181 updated=0 unchanged=0
  team stats   inserted=14 updated=0 unchanged=0
  player stats inserted=181 updated=0 unchanged=0
  quality: 6 pass
```

Run it again and every row reports `unchanged`. Every run writes a row to
`ingest_runs` and six rows to `quality_results`. The exit status is 1 if any game
failed to load or any check reports `fail` or `error`, so a scheduler can alert on it;
`warn` exits 0. `nba-pipeline check --date 2026-03-15` re-runs the checks without
ingesting. Omit `--date` to ingest yesterday
(US/Eastern). Connection settings come from `DATABASE_URL` or a `.env` file; see
`.env.example`.

## Sources

| source | where it works | precision | used for |
|---|---|---|---|
| `nba` (`nba_api`, default) | home connections only | minutes to the second | local development |
| `espn` (ESPN public JSON) | anywhere, including GitHub Actions | whole minutes | the nightly job |

```bash
uv run nba-pipeline ingest --date 2026-03-15 --source espn
```

Each database holds one source. ESPN and the NBA use different game and player ids, so
the first ingest claims the database and the other source is refused with exit code 2.
Use a separate database per source. Team ids are the NBA's in both, so `/teams/{id}`
means the same team everywhere. On the same game the two sources agree on every stat;
a test in CI checks it.

## Nightly ingest

[`.github/workflows/nightly.yml`](.github/workflows/nightly.yml) runs at 07:00 Eastern
on GitHub's servers. It migrates the hosted database, ingests yesterday from ESPN, then
re-ingests the day before to pick up stat corrections. Each run's summary, including the
quality checks, is on its page under **Actions**. A failed game or check turns the run
red. It can also be run by hand for any date from **Actions → Nightly ingest → Run
workflow**.

Setup, once:

1. Create a free Postgres database, e.g. a [Neon](https://neon.tech) project. No card is
   needed. Copy its connection string.
2. Store it in the repository's `production` environment. That environment only accepts
   the `main` branch, so pull requests can never read it:

   ```bash
   gh secret set NEON_DATABASE_URL --env production
   ```

   Paste the connection string when prompted. It is never echoed or logged.
3. Run the workflow once by hand to confirm.

Until the secret is set, the scheduled run skips with a notice instead of failing.

## Read API

```bash
uv run uvicorn nba_pipeline.api.app:app --reload     # http://localhost:8000/docs
```

| Endpoint | Returns |
|---|---|
| `GET /health` | database reachability and the latest run; `degraded` if that run failed |
| `GET /runs/latest`, `GET /runs/{date}` | run summary with row counts, errors and its quality results |
| `GET /quality/{date}` | results from the most recent run that checked the date, plus the worst status |
| `GET /games?date=YYYY-MM-DD` | games on a date with teams and scores (`date` is required) |
| `GET /games/{game_id}` | one game with both box scores, starters first |
| `GET /players/{id}/games?season=2025-26` | a player's game log, newest first, with season totals |
| `GET /teams/{id}/games?season=2025-26` | a team's games with W/L, record and team stats |

Minutes are returned as `MM:SS` and shooting percentages are derived, `null` when there
were no attempts.

## Development

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest                                    # unit tests; integration tests skip
TEST_DATABASE_URL=postgresql+psycopg://nba:nba@localhost:5432/nba_test uv run pytest
```

Tests never call the NBA API. Payloads are recorded once into `tests/fixtures/` and
replayed. Integration tests rebuild the schema from the migrations on every run, so
they only run against `TEST_DATABASE_URL`, and refuse any database whose name does not
end in `_test`. Docker Compose creates `nba_test` the first time the volume is created;
on an older volume, run `docker compose exec postgres createdb -U nba nba_test`.

CI runs the same lint, type-check and test steps on every pull request against a
Postgres service container, and builds the Docker image.

## Docker

One image runs every workload:

```bash
docker build -t nba-pipeline .
docker run --rm -e DATABASE_URL=... --entrypoint alembic nba-pipeline upgrade head
docker run --rm -e DATABASE_URL=... nba-pipeline ingest --date 2026-03-15
docker run --rm -p 8000:8000 -e DATABASE_URL=... --entrypoint uvicorn nba-pipeline   nba_pipeline.api.app:app --host 0.0.0.0 --port 8000
```

From a container, reach the docker-compose database at `host.docker.internal`.

## Layout

```
src/nba_pipeline/
  ingest/      nba_api clients (scoreboard, boxscore), shared throttled client
  schemas/     Pydantic models: raw_* (as received, strict) and clean_* (as stored)
  transform/   raw -> clean: status mapping, minutes -> seconds, payload hashing
  load/        one generic hash-guarded upsert; loaders per table
  quality/     six checks, each returning a structured CheckResult; runner persists them
  api/         FastAPI app: response models, one router per resource
  pipeline.py  one ingest run of one date: scoreboard, then one box score per game
  cli.py       nba-pipeline ingest|check --date YYYY-MM-DD
migrations/    Alembic, raw SQL, owns the schema
tests/         pytest, recorded fixtures in tests/fixtures/
infra/         docker-compose init scripts
```
