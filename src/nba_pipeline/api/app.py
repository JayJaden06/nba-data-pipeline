"""FastAPI read service over the pipeline's tables.

uv run uvicorn nba_pipeline.api.app:app --reload
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from nba_pipeline.api.routes import games, health, players, quality, runs, teams
from nba_pipeline.config import get_settings
from nba_pipeline.db import get_engine


def create_app(database_url: str | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = get_engine(database_url or get_settings().database_url)
        try:
            yield
        finally:
            app.state.engine.dispose()

    app = FastAPI(
        title="nba-pipeline",
        version="0.1.0",
        description="Read API over nightly NBA games, box scores, runs and quality checks.",
        lifespan=lifespan,
    )
    for router in (
        health.router,
        runs.router,
        quality.router,
        games.router,
        players.router,
        teams.router,
    ):
        app.include_router(router)
    return app


app = create_app()
