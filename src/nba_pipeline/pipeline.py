"""Orchestration for one ingest run of one date."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import Engine

from nba_pipeline.ingest.client import NbaApiClient
from nba_pipeline.ingest.scoreboard import fetch_scoreboard
from nba_pipeline.load.games import UpsertResult, upsert_games
from nba_pipeline.load.teams import ensure_teams
from nba_pipeline.transform.games import to_clean_games
from nba_pipeline.transform.teams import teams_from_scoreboard

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestSummary:
    game_date: date
    games: UpsertResult
    teams_added: list[int] = field(default_factory=list)


def ingest_date(engine: Engine, client: NbaApiClient, game_date: date) -> IngestSummary:
    log.info("ingest start date=%s", game_date)
    raw = fetch_scoreboard(client, game_date)
    clean_teams = teams_from_scoreboard(raw)
    clean_games = to_clean_games(raw)
    log.info("scoreboard date=%s games=%d", game_date, len(clean_games))

    with engine.begin() as conn:
        teams_added = ensure_teams(conn, clean_teams)
        result = upsert_games(conn, clean_games)

    for team in clean_teams:
        if team.team_id in teams_added:
            log.warning(
                "registered unknown team id=%d %s is_nba=%s",
                team.team_id,
                team.full_name,
                team.is_nba,
            )
    log.info(
        "games upsert date=%s inserted=%d updated=%d unchanged=%d",
        game_date,
        result.inserted,
        result.updated,
        result.unchanged,
    )
    return IngestSummary(game_date=game_date, games=result, teams_added=teams_added)
