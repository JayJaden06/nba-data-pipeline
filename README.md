# nba-pipeline

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
| 3 | Quality checks, `ingest_runs`, `quality_results` | next |
| 4 | FastAPI read service | |
| 5 | Dockerfile, Cloud Run job, Scheduler/Pub/Sub, CI | |
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
2026-03-15: 7 games (inserted=7 updated=0 unchanged=0); teams added=0
  box scores loaded=7 failed=0
  players      inserted=181 updated=0 unchanged=0
  team stats   inserted=14 updated=0 unchanged=0
  player stats inserted=181 updated=0 unchanged=0
```

Run it again and every row reports `unchanged`. The exit status is 1 if any game failed
to load, so a scheduler can alert on it. Omit `--date` to ingest yesterday
(US/Eastern). Connection settings come from `DATABASE_URL` or a `.env` file; see
`.env.example`.

## Development

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest                                    # unit tests, no network, no database
DATABASE_URL=postgresql+psycopg://nba:nba@localhost:5432/nba uv run pytest -m integration
```

Tests never call the NBA API. Payloads are recorded once into `tests/fixtures/` and
replayed. Integration tests need the docker-compose Postgres and rebuild the schema from
the migrations on every run.

## Layout

```
src/nba_pipeline/
  ingest/      nba_api clients (scoreboard, boxscore), shared throttled client
  schemas/     Pydantic models: raw_* (as received, strict) and clean_* (as stored)
  transform/   raw -> clean: status mapping, minutes -> seconds, payload hashing
  load/        one generic hash-guarded upsert; loaders per table
  quality/     data-quality checks (step 3)
  api/         FastAPI app (step 4)
  pipeline.py  one ingest run of one date: scoreboard, then one box score per game
  cli.py       nba-pipeline ingest --date YYYY-MM-DD
migrations/    Alembic, raw SQL, owns the schema
tests/         pytest, recorded fixtures in tests/fixtures/
infra/         Cloud Run / Scheduler / Pub/Sub (step 5)
```
