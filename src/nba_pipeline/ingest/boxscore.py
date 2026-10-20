"""Box score ingestion: one call per game, returns the validated raw payload."""

from __future__ import annotations

from typing import Any

from nba_api.stats.endpoints import BoxScoreTraditionalV3

from nba_pipeline.ingest.client import ApiClient
from nba_pipeline.schemas.raw_boxscore import RawBoxScoreResponse


def fetch_boxscore(client: ApiClient, game_id: str) -> RawBoxScoreResponse:
    payload: dict[str, Any] = client.call(BoxScoreTraditionalV3, game_id=game_id)
    return RawBoxScoreResponse.parse(payload)
