"""Persist quality check results."""

from __future__ import annotations

from datetime import date

from sqlalchemy import Connection, insert

from nba_pipeline.load.tables import quality_results
from nba_pipeline.schemas.quality import CheckResult


def write_results(
    conn: Connection, run_id: int, game_date: date, results: list[CheckResult]
) -> None:
    if not results:
        return
    conn.execute(
        insert(quality_results),
        [
            {
                "run_id": run_id,
                "game_date": game_date,
                "check_name": r.check_name,
                "status": r.status,
                "details": r.details,
            }
            for r in results
        ],
    )
