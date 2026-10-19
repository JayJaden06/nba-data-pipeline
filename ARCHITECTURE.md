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

* **Keyed upserts.** `games` is keyed on `game_id`, `team_game_stats` on
  `(game_id, team_id)`, `player_game_stats` on `(game_id, player_id)`. One generic
  `INSERT ... ON CONFLICT DO UPDATE` helper (`load/upsert.py`) overwrites every column
  except `first_seen_at`.
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

## Box scores

One `BoxScoreTraditionalV3` call per game that has started (in progress or final).
Scheduled and postponed games are skipped. Each game is loaded in its own
transaction: players are registered first, then the two team rows, then the player
rows. A failure in one game (API gave up, payload drifted, a row failed validation or a
check constraint) is recorded in the run summary and the remaining games still load.
The CLI exits non-zero if any game failed, so the Cloud Run job shows as failed and
the next night's run picks the game up again.

Decisions in the stats tables:

* **Percentages are not stored.** They are derived from made and attempted when
  queried. Storing them would be a drift risk and a consistency risk for nothing.
* **Minutes are integer seconds.** The source gives `MM:SS` strings; anything that does
  not match is rejected. Regulation is 14400, each overtime adds 1500.
* **Did-not-play rows are kept.** Zero stats, `played = false`, and the reason text.
  Sums still hold and "who was on the roster but did not play" stays answerable.
* **Players hold identity only.** A player's team is on each `player_game_stats` row.
  "Current team" is derived from the most recent row when needed, never stored, so
  out-of-order backfills cannot leave it stale.
* **Internal consistency is enforced twice.** The clean model rejects made > attempted
  or rebounds that do not sum, and the same rules are check constraints in Postgres.

## Runs and quality checks

Every invocation inserts an `ingest_runs` row with status `running` before the first
API call and finalises it at the end, each in its own short transaction. If the process
dies, a `running` row older than an hour is visible as a stuck run. Every row written by
a run is stamped with its `ingest_run_id` (excluded from change detection, so a stamp
alone never counts as an update). `nba-pipeline check` records a run of kind `check`
with no ingest.

Six checks run at the end of every ingest and write one `quality_results` row each:

| check | fails when |
|---|---|
| `box_scores_complete` | a final game on the date has no box score (not-yet-final games warn) |
| `no_duplicate_player_rows` | more than one row per (game_id, player_id); guaranteed by the PK, verified anyway |
| `team_points_match_players` | team points differ from the sum of its players' points |
| `team_minutes_sum` | team seconds are not 14400 + 1500 per overtime, or players do not sum to the team, beyond 60 s |
| `schema_drift` | any payload in the run failed validation |
| `freshness` | newest final game is more than 2 days old and a later run found games; warns when later runs found none (offseason) |

Policy decisions:

* **A failing check never removes data.** The rows stay loaded; the result row is the
  flag and the API surfaces it.
* **`fail` and `error` fail the run and exit 1.** A nightly job that is green while
  team points do not match player points teaches people to stop looking. `warn` is the
  advisory level and exits 0.
* **One broken check never hides the others.** The runner turns an exception into an
  `error` result and continues.
* **Tolerances are explicit and recorded in `details`.** Sixty seconds on minutes
  absorbs the NBA's per-player rounding but still catches a missing player.

## Read API

FastAPI over the same tables, SQLAlchemy Core only, one read-only connection per request.

* **Response models are separate from storage models.** `api/models.py` adds derived
  fields (`MM:SS` minutes, shooting percentages, W/L, record) and hides bookkeeping
  columns. The pipeline's `clean_*` models can change without breaking API clients, and
  the other way round.
* **Derived values are computed at read time, never stored.** Percentages are `null`
  rather than `0.0` when there were no attempts, so a DNP never looks like an 0-for.
* **Explicit inputs.** `date` and `season` are required query parameters and malformed
  values are a 422. "No games that day" is an empty list; an unknown id is a 404.
* **Quality is visible where the data is.** `/runs/{date}` embeds that run's check
  results, and `/quality/{date}` follows the most recent run of either kind, so a
  `nba-pipeline check` after a fix is reflected immediately. `/health` reports
  `degraded` when the latest run failed.
* **No pagination yet.** The largest response is one team's or player's season.

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
and assert the inserted / updated / unchanged counts across repeated upserts. The
pipeline itself is tested end to end with a fake API client that serves the recorded
payloads, including a day where six of seven box scores fail.

## Still to come

* `ingest_runs` and `quality_results` (step 3) will give every run a row and attach
  structured check results. `games` gains a nullable `ingest_run_id` then.
* Quality checks load-and-flag: a failing check writes to `quality_results` and surfaces
  in the API, it never drops rows.
