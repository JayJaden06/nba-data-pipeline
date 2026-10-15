"""Generic idempotent upsert used by every loader.

INSERT ... ON CONFLICT (key) DO UPDATE ... WHERE <any change column differs>, so an
identical row touches nothing and last_updated_at only moves on real changes. The
RETURNING clause reports (xmax = 0), which is true for freshly inserted rows.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from sqlalchemy import Column, Connection, Table, func, literal_column, or_
from sqlalchemy.dialects.postgresql import insert

_BOOKKEEPING = frozenset({"first_seen_at", "last_updated_at"})


@dataclass(frozen=True)
class UpsertResult:
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0

    @property
    def total(self) -> int:
        return self.inserted + self.updated + self.unchanged

    def __add__(self, other: UpsertResult) -> UpsertResult:
        return UpsertResult(
            self.inserted + other.inserted,
            self.updated + other.updated,
            self.unchanged + other.unchanged,
        )

    def as_tuple(self) -> tuple[int, int, int]:
        return (self.inserted, self.updated, self.unchanged)


def upsert_rows(
    conn: Connection,
    table: Table,
    rows: Sequence[BaseModel],
    *,
    key: Sequence[Column[Any]],
    change_cols: Sequence[str] = ("source_payload_hash",),
    stamp: dict[str, Any] | None = None,
) -> UpsertResult:
    """Upsert pydantic rows into `table`, keyed on `key`.

    A conflicting row is only updated when at least one of `change_cols` differs.
    `stamp` adds bookkeeping columns (e.g. ingest_run_id) to every row; they are written
    on insert and on update but never count as a change by themselves.
    """
    if not rows:
        return UpsertResult()

    key_names = {c.name for c in key}
    stmt = insert(table).values([r.model_dump(mode="python") | (stamp or {}) for r in rows])
    set_: dict[str, Any] = {
        c.name: getattr(stmt.excluded, c.name)
        for c in table.c
        if c.name not in key_names and c.name not in _BOOKKEEPING
    }
    if "last_updated_at" in table.c:
        set_["last_updated_at"] = func.now()
    changed = or_(*[table.c[name] != getattr(stmt.excluded, name) for name in change_cols])
    upsert: Any = stmt.on_conflict_do_update(
        index_elements=list(key), set_=set_, where=changed
    ).returning(literal_column("(xmax = 0)").label("inserted"))

    touched = conn.execute(upsert).scalars().all()
    inserted = sum(1 for t in touched if t)
    return UpsertResult(
        inserted=inserted, updated=len(touched) - inserted, unchanged=len(rows) - len(touched)
    )


def stamp_for_run(run_id: int | None) -> dict[str, Any] | None:
    return {"ingest_run_id": run_id} if run_id is not None else None
