"""ingest_runs bookkeeping. Each call is its own short transaction so a run row exists
before any API call and is finalised even when the rest of the run blows up."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import Engine, func, insert, update

from nba_pipeline.load.tables import ingest_runs
from nba_pipeline.schemas.run import RunKind, RunStatus


def start_run(engine: Engine, game_date: date, kind: RunKind = RunKind.INGEST) -> int:
    stmt = (
        insert(ingest_runs)
        .values(game_date=game_date, kind=kind, status=RunStatus.RUNNING)
        .returning(ingest_runs.c.run_id)
    )
    with engine.begin() as conn:
        return int(conn.execute(stmt).scalar_one())


def finish_run(
    engine: Engine,
    run_id: int,
    status: RunStatus,
    *,
    games_total: int = 0,
    rows: tuple[int, int, int] = (0, 0, 0),
    box_scores_loaded: int = 0,
    box_scores_failed: int = 0,
    errors: list[dict[str, Any]] | None = None,
    summary: dict[str, Any] | None = None,
) -> None:
    stmt = (
        update(ingest_runs)
        .where(ingest_runs.c.run_id == run_id)
        .values(
            status=status,
            finished_at=func.now(),
            games_total=games_total,
            rows_inserted=rows[0],
            rows_updated=rows[1],
            rows_unchanged=rows[2],
            box_scores_loaded=box_scores_loaded,
            box_scores_failed=box_scores_failed,
            errors=errors or [],
            summary=summary or {},
        )
    )
    with engine.begin() as conn:
        conn.execute(stmt)
