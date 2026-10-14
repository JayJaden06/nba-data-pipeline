"""Register teams referenced by a payload. Existing rows are never modified."""

from __future__ import annotations

from sqlalchemy import Connection
from sqlalchemy.dialects.postgresql import insert

from nba_pipeline.load.tables import teams
from nba_pipeline.schemas.clean_team import CleanTeam


def ensure_teams(conn: Connection, rows: list[CleanTeam]) -> list[int]:
    """Insert any unknown teams; return the ids that were newly added."""
    if not rows:
        return []
    stmt = (
        insert(teams)
        .values([r.model_dump(mode="python") for r in rows])
        .on_conflict_do_nothing(index_elements=[teams.c.team_id])
        .returning(teams.c.team_id)
    )
    return list(conn.execute(stmt).scalars().all())
