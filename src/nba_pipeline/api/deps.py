"""FastAPI dependencies: one read-only connection per request from the app's engine."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Query, Request
from sqlalchemy import Connection, Engine


def get_engine(request: Request) -> Engine:
    engine: Engine = request.app.state.engine
    return engine


def get_conn(engine: Annotated[Engine, Depends(get_engine)]) -> Iterator[Connection]:
    with engine.connect() as conn:
        yield conn


Conn = Annotated[Connection, Depends(get_conn)]

SeasonParam = Annotated[str, Query(pattern=r"^\d{4}-\d{2}$", description="Season, e.g. 2025-26")]
