from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import Connection, RowMapping, select

from nba_pipeline.api.deps import Conn
from nba_pipeline.api.models import QualityResult, RowCounts, RunSummary
from nba_pipeline.load.tables import ingest_runs, quality_results

router = APIRouter(prefix="/runs", tags=["runs"])


def quality_for_run(conn: Connection, run_id: int) -> list[QualityResult]:
    rows = conn.execute(
        select(quality_results)
        .where(quality_results.c.run_id == run_id)
        .order_by(quality_results.c.result_id)
    ).mappings()
    return [
        QualityResult(
            check_name=r["check_name"],
            status=r["status"].value,
            details=r["details"],
            checked_at=r["checked_at"],
        )
        for r in rows
    ]


def _summary(conn: Connection, row: RowMapping) -> RunSummary:
    data: dict[str, Any] = dict(row)
    data["kind"] = row["kind"].value
    data["status"] = row["status"].value
    data["rows"] = RowCounts(
        inserted=row["rows_inserted"], updated=row["rows_updated"], unchanged=row["rows_unchanged"]
    )
    data["quality"] = quality_for_run(conn, row["run_id"])
    return RunSummary.model_validate(data)


def latest_run(conn: Connection, game_date: date | None = None) -> RunSummary | None:
    stmt = select(ingest_runs).order_by(ingest_runs.c.started_at.desc()).limit(1)
    if game_date is not None:
        stmt = stmt.where(ingest_runs.c.game_date == game_date)
    row = conn.execute(stmt).mappings().first()
    return _summary(conn, row) if row else None


@router.get("/latest", response_model=RunSummary)
def get_latest_run(conn: Conn) -> RunSummary:
    run = latest_run(conn)
    if run is None:
        raise HTTPException(404, "no runs recorded yet")
    return run


@router.get("/{game_date}", response_model=RunSummary)
def get_run_for_date(game_date: date, conn: Conn) -> RunSummary:
    run = latest_run(conn, game_date)
    if run is None:
        raise HTTPException(404, f"no run recorded for {game_date}")
    return run
