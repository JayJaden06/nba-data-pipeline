# Architecture

Short notes on the design decisions. Written to be read alongside the code.

## Shape of the pipeline

```
nba_api  ->  raw_* (Pydantic, strict)  ->  transform  ->  clean_* (Pydantic)  ->  upsert  ->  Postgres
                     |                                                              |
              SchemaDriftError                                              quality checks (step 3)
```

One run ingests one game date. The date is always explicit in the code path; "yesterday"
is only resolved at the CLI boundary. Backfill and nightly ingest therefore share one
function, `pipeline.ingest_date`, and re-running any date is safe.

## Two layers of Pydantic models

**raw_*** models mirror the payload exactly as `nba_api` returns it, with camelCase
aliases. Every block we consume is `extra="forbid"`. If the NBA adds, removes or renames
a field, validation fails before anything touches the database and the run fails with a
`SchemaDriftError` naming the endpoint and the offending keys. Blocks we do not consume
(game leaders, broadcasters) are typed loosely so churn there does not break ingestion.
The deliberate trade-off: an upstream change costs a one-line model edit and a failed
run, rather than silently loading wrong data.

**clean_*** models are the rows as stored. They are frozen, carry derived fields, and
are the only thing the load layer accepts. Nothing reaches an INSERT without passing
both layers.

## Why ScoreboardV3

The classic `ScoreboardV2` endpoint is deprecated in `nba_api` with known bad line-score
data for part of the 2025-26 season. V3 has the same information for all historical
dates and is what the library maintainers recommend. The recorded fixtures show the
exact shape.

## Idempotency and late data

Sports data arrives late and gets corrected. The pipeline is designed to be run again,
not to be run once correctly.

* **Keyed upserts.** `games` is keyed on `game_id`; later tables are keyed on
  `(game_id, team_id)` and `(game_id, player_id)`. `INSERT ... ON CONFLICT DO UPDATE`
  overwrites every column except `first_seen_at`.
* **Change detection.** Each clean row carries a SHA-256 of the source fields that
  matter. The upsert has a `WHERE games.source_payload_hash <> excluded.source_payload_hash`
  clause, so an identical payload touches no rows and `last_updated_at` is only bumped
  on real changes. The run summary reports inserted / updated / unchanged, which makes
  "did anything change?" visible in the logs.
* **Partial days.** Running at midnight ET while a West Coast game is still live stores
  it as `in_progress` with the live score. The next run overwrites it with the final.
  Nothing is dropped and nothing has to be deleted.
* **Postponed games.** The NBA keeps the same `game_id` when a game is rescheduled. The
  status text says `PPD` while the numeric status still says scheduled, so the text
  wins. When the game is played the same row is updated with the new `game_date`.
* **Scores are nullable.** The source reports 0-0 for games that have not started. The
  transform nulls scores until the game has started, and a check constraint requires
  non-null scores on any `final` row, so a scheduled game can never be mistaken for a
  0-0 final.
* **Teams discovered from data.** The 30 franchises are seeded by the first migration.
  Preseason games against non-NBA clubs (London Lions, `team_id` 50015) would violate the
  foreign key, so every team seen in a payload is registered first, with `is_nba=false`,
  and the run logs a warning. The game is loaded and flagged, never skipped.

## Loading

SQLAlchemy Core only. Table definitions in `load/tables.py` exist for building
statements; the schema itself is owned by hand-written SQL in Alembic migrations, so
what runs in Cloud SQL is exactly what is in the repo. No ORM sessions, no implicit
flushes.

## Rate limiting and retries

`stats.nba.com` throttles aggressively and sometimes returns HTML or an empty body
instead of JSON. `ingest.client.NbaApiClient` spaces calls by at least 0.6 s and retries
network errors and unparseable responses with exponential backoff and jitter, capped at
30 s. Programming errors are not retried. The clock and sleep function are injectable,
so the retry logic is unit-tested without waiting.

## Testing

Tests never hit the network. Each endpoint's payload is recorded once into
`tests/fixtures/` and replayed. Fixtures are chosen to cover the cases that matter: a
finished regular-season day, a not-yet-played preseason day, and a preseason day with a
non-NBA opponent. Edge cases that are hard to record (postponements, overtime,
corrections) are built by mutating a recorded payload in the test.

Integration tests run the migrations from scratch against the docker-compose Postgres
and assert the inserted / updated / unchanged counts across repeated upserts.

## Still to come

* `ingest_runs` and `quality_results` (step 3) will give every run a row and attach
  structured check results. `games` gains a nullable `ingest_run_id` then.
* Quality checks load-and-flag: a failing check writes to `quality_results` and surfaces
  in the API, it never drops rows.
