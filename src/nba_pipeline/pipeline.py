"""Orchestration for one ingest run of one date.

1. Scoreboard -> teams (register unknown) + games, one transaction.
2. For every game that has started (in progress or final): box score -> players +
   team_game_stats + player_game_stats, one transaction per game. A failure in one
   game is recorded in the summary and does not stop the others.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError

from nba_pipeline.ingest.boxscore import fetch_boxscore
from nba_pipeline.ingest.client import NbaApiClient, NbaApiError
from nba_pipeline.ingest.scoreboard import fetch_scoreboard
from nba_pipeline.load.box_stats import upsert_player_game_stats, upsert_team_game_stats
from nba_pipeline.load.games import upsert_games
from nba_pipeline.load.players import upsert_players
from nba_pipeline.load.teams import ensure_teams
from nba_pipeline.load.upsert import UpsertResult
from nba_pipeline.schemas import SchemaDriftError
from nba_pipeline.schemas.clean_game import CleanGame, GameStatus
from nba_pipeline.transform.boxscore import BoxScoreRows, to_box_score_rows
from nba_pipeline.transform.games import to_clean_games
from nba_pipeline.transform.teams import teams_from_scoreboard

log = logging.getLogger(__name__)

BOX_SCORE_STATUSES = frozenset({GameStatus.IN_PROGRESS, GameStatus.FINAL})

# Errors that are isolated to one game: API gave up, payload drifted, a row failed
# validation or a database constraint. Anything else is a bug and propagates.
PER_GAME_ERRORS: tuple[type[Exception], ...] = (
    NbaApiError,
    SchemaDriftError,
    ValueError,
    IntegrityError,
)


@dataclass(frozen=True)
class IngestSummary:
    game_date: date
    games: UpsertResult
    teams_added: list[int] = field(default_factory=list)
    box_scores_loaded: int = 0
    players: UpsertResult = field(default_factory=UpsertResult)
    team_stats: UpsertResult = field(default_factory=UpsertResult)
    player_stats: UpsertResult = field(default_factory=UpsertResult)
    failures: dict[str, str] = field(default_factory=dict)  # game_id -> error

    @property
    def ok(self) -> bool:
        return not self.failures


def _check_matches_game(rows: BoxScoreRows, game: CleanGame) -> None:
    expected = {game.home_team_id, game.away_team_id}
    actual = {t.team_id for t in rows.team_stats}
    if actual != expected:
        raise ValueError(
            f"box score teams {sorted(actual)} do not match scoreboard {sorted(expected)}"
        )


def ingest_date(engine: Engine, client: NbaApiClient, game_date: date) -> IngestSummary:
    log.info("ingest start date=%s", game_date)
    raw = fetch_scoreboard(client, game_date)
    clean_teams = teams_from_scoreboard(raw)
    clean_games = to_clean_games(raw)
    log.info("scoreboard date=%s games=%d", game_date, len(clean_games))

    with engine.begin() as conn:
        teams_added = ensure_teams(conn, clean_teams)
        games_result = upsert_games(conn, clean_games)

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
                t = upsert_team_game_stats(conn, rows.team_stats)
                s = upsert_player_game_stats(conn, rows.player_stats)
        except PER_GAME_ERRORS as exc:
            log.exception("box score failed game_id=%s", game.game_id)
            failures[game.game_id] = f"{type(exc).__name__}: {str(exc).splitlines()[0]}"
            continue
        loaded += 1
        players, team_stats, player_stats = players + p, team_stats + t, player_stats + s
        log.info(
            "box score game_id=%s players=%s team_stats=%s player_stats=%s", game.game_id, p, t, s
        )

    summary = IngestSummary(
        game_date=game_date,
        games=games_result,
        teams_added=teams_added,
        box_scores_loaded=loaded,
        players=players,
        team_stats=team_stats,
        player_stats=player_stats,
        failures=failures,
    )
    log.info("ingest done date=%s ok=%s failures=%d", game_date, summary.ok, len(failures))
    return summary
