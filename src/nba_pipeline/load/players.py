"""Upsert player identities. Names and slugs are refreshed when they change upstream."""

from __future__ import annotations

from sqlalchemy import Connection

from nba_pipeline.load.tables import players
from nba_pipeline.load.upsert import UpsertResult, upsert_rows
from nba_pipeline.schemas.clean_player import CleanPlayer


def upsert_players(conn: Connection, rows: list[CleanPlayer]) -> UpsertResult:
    # Dedupe: the same player can appear in several box scores within one run.
    unique = list({r.player_id: r for r in rows}.values())
    return upsert_rows(
        conn,
        players,
        unique,
        key=[players.c.player_id],
        change_cols=("first_name", "last_name", "slug"),
    )
