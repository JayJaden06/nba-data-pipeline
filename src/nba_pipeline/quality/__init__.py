"""Data-quality checks.

Each check is a small class with a `name` and a `run(conn, ctx)` that executes
read-only SQL and returns one structured CheckResult. The runner executes every
registered check, turns exceptions into `error` results, and persists the lot.

A failing check never deletes or blocks data: the data stays loaded and the result row
is the flag. A `fail` or `error` does make the run exit non-zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

from sqlalchemy import Connection

from nba_pipeline.schemas.quality import CheckResult, CheckStatus

__all__ = ["CheckContext", "CheckResult", "CheckStatus", "QualityCheck"]


@dataclass(frozen=True)
class CheckContext:
    game_date: date  # the date that was ingested / is being checked
    today: date  # wall-clock date in US/Eastern, injectable for tests
    run_id: int | None = None
    ingest_errors: list[dict[str, Any]] = field(default_factory=list)
    source: str = "nba"  # minute precision differs by source; see TeamMinutesSum


class QualityCheck(Protocol):
    name: str

    def run(self, conn: Connection, ctx: CheckContext) -> CheckResult: ...
