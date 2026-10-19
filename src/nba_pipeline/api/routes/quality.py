from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from nba_pipeline.api.deps import Conn
from nba_pipeline.api.models import QualityReport
from nba_pipeline.api.routes.runs import quality_for_run
from nba_pipeline.load.tables import quality_results

router = APIRouter(prefix="/quality", tags=["quality"])

_SEVERITY = {"pass": 0, "warn": 1, "fail": 2, "error": 3}


@router.get("/{game_date}", response_model=QualityReport)
def get_quality_for_date(game_date: date, conn: Conn) -> QualityReport:
    """Results from the most recent run (ingest or check) that checked this date."""
    latest = conn.execute(
        select(quality_results.c.run_id, func.max(quality_results.c.checked_at).label("at"))
        .where(quality_results.c.game_date == game_date)
        .group_by(quality_results.c.run_id)
        .order_by(func.max(quality_results.c.checked_at).desc())
        .limit(1)
    ).first()
    if latest is None:
        raise HTTPException(404, f"no quality results for {game_date}")
    results = quality_for_run(conn, latest.run_id)
    overall = max(results, key=lambda r: _SEVERITY[r.status]).status
    return QualityReport(
        game_date=game_date,
        run_id=latest.run_id,
        checked_at=latest.at,
        overall=overall,
        results=results,
    )
