"""Upserts for team_game_stats (game_id, team_id) and player_game_stats (game_id, player_id)."""

from __future__ import annotations

from sqlalchemy import Connection

from nba_pipeline.load.tables import player_game_stats, team_game_stats
from nba_pipeline.load.upsert import UpsertResult, stamp_for_run, upsert_rows
from nba_pipeline.schemas.clean_box_stats import CleanPlayerGameStats, CleanTeamGameStats


def upsert_team_game_stats(
    conn: Connection, rows: list[CleanTeamGameStats], *, run_id: int | None = None
) -> UpsertResult:
    return upsert_rows(
        conn,
        team_game_stats,
        rows,
        key=[team_game_stats.c.game_id, team_game_stats.c.team_id],
        stamp=stamp_for_run(run_id),
    )


def upsert_player_game_stats(
    conn: Connection, rows: list[CleanPlayerGameStats], *, run_id: int | None = None
) -> UpsertResult:
    return upsert_rows(
        conn,
        player_game_stats,
        rows,
        key=[player_game_stats.c.game_id, player_game_stats.c.player_id],
        stamp=stamp_for_run(run_id),
    )
