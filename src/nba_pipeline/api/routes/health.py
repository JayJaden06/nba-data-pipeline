from __future__ import annotations

from fastapi import APIRouter, Response, status
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from nba_pipeline.api.deps import Conn
from nba_pipeline.api.models import Health
from nba_pipeline.api.routes.runs import latest_run

router = APIRouter(tags=["health"])


@router.get("/health", response_model=Health)
def health(conn: Conn, response: Response) -> Health:
    try:
        conn.execute(text("SELECT 1"))
    except OperationalError:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return Health(status="degraded", database="unreachable", latest_run=None)
    run = latest_run(conn)
    ok = run is not None and run.status == "succeeded"
    return Health(status="ok" if ok else "degraded", database="ok", latest_run=run)
