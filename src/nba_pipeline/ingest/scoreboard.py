"""Scoreboard ingestion: one call per date, returns the validated raw payload."""

from __future__ import annotations

from datetime import date
from typing import Any

from nba_api.stats.endpoints import ScoreboardV3

from nba_pipeline.ingest.client import ApiClient
from nba_pipeline.schemas.raw_scoreboard import RawScoreboardResponse


def fetch_scoreboard(client: ApiClient, game_date: date) -> RawScoreboardResponse:
    payload: dict[str, Any] = client.call(ScoreboardV3, game_date=game_date.isoformat())
    return RawScoreboardResponse.parse(payload)
