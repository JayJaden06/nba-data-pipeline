"""Idempotent upsert of CleanGame rows into `games`, keyed on game_id.

Re-running a date is safe:
  * new game_id        -> inserted
  * changed payload    -> updated, last_updated_at bumped
  * identical payload  -> untouched (the ON CONFLICT ... WHERE clause skips it)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, func, literal_column
from sqlalchemy.dialects.postgresql import insert

from nba_pipeline.load.tables import games
from nba_pipeline.schemas.clean_game import CleanGame


@dataclass(frozen=True)
class UpsertResult:
    inserted: int
    updated: int
    unchanged: int

    @property
    def total(self) -> int:
        return self.inserted + self.updated + self.unchanged


def upsert_games(conn: Connection, rows: list[CleanGame]) -> UpsertResult:
    if not rows:
        return UpsertResult(0, 0, 0)

    values = [r.model_dump(mode="python") for r in rows]
    stmt = insert(games).values(values)
    update_cols = {
        c.name: getattr(stmt.excluded, c.name)
        for c in games.c
        if c.name not in ("game_id", "first_seen_at", "last_updated_at")
    }
    update_cols["last_updated_at"] = func.now()
    upsert: Any = stmt.on_conflict_do_update(
        index_elements=[games.c.game_id],
        set_=update_cols,
        where=games.c.source_payload_hash != stmt.excluded.source_payload_hash,
    ).returning(literal_column("(xmax = 0)").label("inserted"))

    touched = conn.execute(upsert).scalars().all()
    inserted = sum(1 for t in touched if t)
    updated = len(touched) - inserted
    return UpsertResult(inserted=inserted, updated=updated, unchanged=len(rows) - len(touched))
