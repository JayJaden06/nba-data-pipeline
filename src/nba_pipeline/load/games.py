"""Idempotent upsert of CleanGame rows into `games`, keyed on game_id."""

from __future__ import annotations

from sqlalchemy import Connection

from nba_pipeline.load.tables import games
from nba_pipeline.load.upsert import UpsertResult, upsert_rows
from nba_pipeline.schemas.clean_game import CleanGame

__all__ = ["UpsertResult", "upsert_games"]


def upsert_games(conn: Connection, rows: list[CleanGame]) -> UpsertResult:
    return upsert_rows(conn, games, rows, key=[games.c.game_id])
