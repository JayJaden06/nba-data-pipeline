"""One source of record per database.

ESPN and the NBA use different ids for games and players, so mixing them in one
database would create duplicate games and split player histories. The first ingest
claims the database for its source; any later ingest from the other source is refused.
"""

from __future__ import annotations

from sqlalchemy import Connection, select
from sqlalchemy.dialects.postgresql import insert

from nba_pipeline.load.tables import pipeline_meta


class SourceMismatchError(RuntimeError):
    def __init__(self, database_source: str, requested: str) -> None:
        self.database_source = database_source
        self.requested = requested
        super().__init__(
            f"this database holds {database_source!r} data; refusing to load {requested!r}. "
            "Use a separate database per source."
        )


def get_source(conn: Connection) -> str | None:
    value: str | None = conn.execute(
        select(pipeline_meta.c.value).where(pipeline_meta.c.key == "source")
    ).scalar_one_or_none()
    return value


def claim_source(conn: Connection, source: str) -> None:
    """Record `source` for an unclaimed database; raise if it belongs to another."""
    conn.execute(
        insert(pipeline_meta)
        .values(key="source", value=source)
        .on_conflict_do_nothing(index_elements=[pipeline_meta.c.key])
    )
    current = get_source(conn)
    if current != source:
        raise SourceMismatchError(current or "?", source)
