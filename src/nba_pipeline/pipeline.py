"""Orchestration for one ingest run of one date.

0. Insert an ingest_runs row (status running) before any API call.
1. Scoreboard -> teams (register unknown) + games, one transaction.
2. For every game that has started (in progress or final): box score -> players +
   team_game_stats + player_game_stats, one transaction per game. A failure in one
   game is recorded and does not stop the others.
3. Run every quality check and persist the results under this run.
4. Finalise the run row. The run is `failed` if any game failed to load or any check
   is fail/error; data is never removed because of a failing check.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError

from nba_pipeline.ingest.boxscore import fetch_boxscore
from nba_pipeline.ingest.client import NbaApiClient, NbaApiError
from nba_pipeline.ingest.scoreboard import fetch_scoreboard
from nba_pipeline.load.box_stats import upsert_player_game_stats, upsert_team_game_stats
from nba_pipeline.load.games import upsert_games
from nba_pipeline.load.players import upsert_players
from nba_pipeline.load.runs import finish_run, start_run
from nba_pipeline.load.teams import ensure_teams
from nba_pipeline.load.upsert import UpsertResult
from nba_pipeline.quality import CheckContext, CheckResult
from nba_pipeline.quality.runner import run_and_record
from nba_pipeline.schemas import SchemaDriftError
from nba_pipeline.schemas.clean_game import CleanGame, GameStatus
from nba_pipeline.schemas.run import RunKind, RunStatus
from nba_pipeline.transform.boxscore import BoxScoreRows, to_box_score_rows
from nba_pipeline.transform.games import to_clean_games
from nba_pipeline.transform.teams import teams_from_scoreboard

log = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
BOX_SCORE_STATUSES = frozenset({GameStatus.IN_PROGRESS, GameStatus.FINAL})

# Errors that are isolated to one game: API gave up, payload drifted, a row failed
# validation or a database constraint. Anything else is a bug and propagates.
PER_GAME_ERRORS: tuple[type[Exception], ...] = (
    NbaApiError,
    SchemaDriftError,
    ValueError,
    IntegrityError,
)


def today_et() -> date:
    return datetime.now(tz=UTC).astimezone(ET).date()


@dataclass(frozen=True)
class IngestSummary:
    run_id: int
    game_date: date
    games: UpsertResult
    teams_added: list[int] = field(default_factory=list)
    box_scores_loaded: int = 0
    players: UpsertResult = field(default_factory=UpsertResult)
    team_stats: UpsertResult = field(default_factory=UpsertResult)
    player_stats: UpsertResult = field(default_factory=UpsertResult)
    failures: dict[str, str] = field(default_factory=dict)  # game_id -> error
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures and not any(c.blocking for c in self.checks)

    @property
    def status(self) -> RunStatus:
        return RunStatus.SUCCEEDED if self.ok else RunStatus.FAILED

    def rows(self) -> tuple[int, int, int]:
        total = self.games + self.players + self.team_stats + self.player_stats
        return total.as_tuple()

    def errors(self) -> list[dict[str, str]]:
        return [{"game_id": g, "error": e} for g, e in self.failures.items()]

    def counts(self) -> dict[str, dict[str, int]]:
        return {
            name: {"inserted": r.inserted, "updated": r.updated, "unchanged": r.unchanged}
            for name, r in (
                ("games", self.games),
                ("players", self.players),
                ("team_game_stats", self.team_stats),
                ("player_game_stats", self.player_stats),
            )
        }


def _check_matches_game(rows: BoxScoreRows, game: CleanGame) -> None:
    expected = {game.home_team_id, game.away_team_id}
    actual = {t.team_id for t in rows.team_stats}
    if actual != expected:
        raise ValueError(
            f"box score teams {sorted(actual)} do not match scoreboard {sorted(expected)}"
        )


def ingest_date(
    engine: Engine, client: NbaApiClient, game_date: date, *, today: date | None = None
) -> IngestSummary:
    run_id = start_run(engine, game_date)
    log.info("ingest start run_id=%d date=%s", run_id, game_date)
    try:
        summary = _ingest(engine, client, game_date, run_id, today or today_et())
    except Exception as exc:
        finish_run(
            engine,
            run_id,
            RunStatus.FAILED,
            errors=[{"stage": "ingest", "error": f"{type(exc).__name__}: {exc}"}],
        )
        raise
    finish_run(
        engine,
        run_id,
        summary.status,
        games_total=summary.games.total,
        rows=summary.rows(),
        box_scores_loaded=summary.box_scores_loaded,
        box_scores_failed=len(summary.failures),
        errors=summary.errors(),
        summary={"tables": summary.counts(), "teams_added": summary.teams_added},
    )
    log.info("ingest done run_id=%d date=%s status=%s", run_id, game_date, summary.status)
    return summary


def _ingest(
    engine: Engine, client: NbaApiClient, game_date: date, run_id: int, today: date
) -> IngestSummary:
    raw = fetch_scoreboard(client, game_date)
    clean_teams = teams_from_scoreboard(raw)
    clean_games = to_clean_games(raw)
    log.info("scoreboard date=%s games=%d", game_date, len(clean_games))

    with engine.begin() as conn:
        teams_added = ensure_teams(conn, clean_teams)
        games_result = upsert_games(conn, clean_games, run_id=run_id)
    for team in clean_teams:
        if team.team_id in teams_added:
            log.warning(
                "registered unknown team id=%d %s is_nba=%s",
                team.team_id,
                team.full_name,
                team.is_nba,
            )
    log.info("games upsert date=%s %s", game_date, games_result)

    players = team_stats = player_stats = UpsertResult()
    loaded = 0
    failures: dict[str, str] = {}
    for game in clean_games:
        if game.status not in BOX_SCORE_STATUSES:
            log.info("skip box score game_id=%s status=%s", game.game_id, game.status)
            continue
        try:
            rows = to_box_score_rows(fetch_boxscore(client, game.game_id))
            _check_matches_game(rows, game)
            with engine.begin() as conn:
                p = upsert_players(conn, rows.players)
                t = upsert_team_game_stats(conn, rows.team_stats, run_id=run_id)
                s = upsert_player_game_stats(conn, rows.player_stats, run_id=run_id)
        except PER_GAME_ERRORS as exc:
            log.exception("box score failed game_id=%s", game.game_id)
            failures[game.game_id] = f"{type(exc).__name__}: {str(exc).splitlines()[0]}"
            continue
        loaded += 1
        players, team_stats, player_stats = players + p, team_stats + t, player_stats + s
        log.info("box score game_id=%s players=%s team=%s player=%s", game.game_id, p, t, s)

    ctx = CheckContext(
        game_date=game_date,
        today=today,
        run_id=run_id,
        ingest_errors=[{"game_id": g, "error": e} for g, e in failures.items()],
    )
    with engine.begin() as conn:
        checks = run_and_record(conn, ctx)

    return IngestSummary(
        run_id=run_id,
        game_date=game_date,
        games=games_result,
        teams_added=teams_added,
        box_scores_loaded=loaded,
        players=players,
        team_stats=team_stats,
        player_stats=player_stats,
        failures=failures,
        checks=checks,
    )


def check_date(
    engine: Engine, game_date: date, *, today: date | None = None
) -> tuple[int, list[CheckResult]]:
    """Run the quality checks for a date without ingesting; recorded as a `check` run."""
    run_id = start_run(engine, game_date, kind=RunKind.CHECK)
    ctx = CheckContext(game_date=game_date, today=today or today_et(), run_id=run_id)
    try:
        with engine.begin() as conn:
            results = run_and_record(conn, ctx)
    except Exception as exc:
        finish_run(engine, run_id, RunStatus.FAILED, errors=[{"stage": "check", "error": str(exc)}])
        raise
    status = RunStatus.FAILED if any(r.blocking for r in results) else RunStatus.SUCCEEDED
    finish_run(engine, run_id, status, summary={"checks": [r.status.value for r in results]})
    return run_id, results
