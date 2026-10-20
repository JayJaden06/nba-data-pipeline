"""ESPN ingestion: one scoreboard call per date, one summary call per game."""

from __future__ import annotations

from datetime import date

from nba_pipeline.ingest.client import ApiClient
from nba_pipeline.schemas.raw_espn import EspnScoreboard, EspnSummary

BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"


def fetch_scoreboard(client: ApiClient, game_date: date) -> EspnScoreboard:
    payload = client.get_json(f"{BASE}/scoreboard", {"dates": game_date.strftime("%Y%m%d")})
    return EspnScoreboard.parse(payload)


def fetch_summary(client: ApiClient, event_id: str) -> EspnSummary:
    return EspnSummary.parse(client.get_json(f"{BASE}/summary", {"event": event_id}))
