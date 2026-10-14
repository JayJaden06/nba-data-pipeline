"""Raw models for the ScoreboardV3 endpoint (nba_api.stats.endpoints.ScoreboardV3).

Field names are snake_case; aliases are generated as camelCase to match the payload.
Every model we consume is extra="forbid": a new or renamed key upstream raises a
ValidationError, which is wrapped as SchemaDriftError before anything is loaded.

Blocks we do not consume (leaders, broadcasters) are typed loosely so that churn
there does not break ingestion.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic.alias_generators import to_camel

from nba_pipeline.schemas import SchemaDriftError

ENDPOINT = "ScoreboardV3"


class RawModel(BaseModel):
    model_config = ConfigDict(extra="forbid", alias_generator=to_camel, populate_by_name=True)


class RawPeriod(RawModel):
    period: int
    period_type: str  # REGULAR or OVERTIME
    score: int


class RawTeam(RawModel):
    team_id: int
    team_name: str
    team_city: str
    team_tricode: str
    team_slug: str
    wins: int
    losses: int
    score: int  # 0 before tip-off, not null
    seed: int
    in_bonus: str | None = None
    timeouts_remaining: int
    periods: list[RawPeriod]


class RawGame(RawModel):
    game_id: str = Field(pattern=r"^\d{10}$")
    game_code: str
    game_status: int  # 1 scheduled, 2 in progress, 3 final
    game_status_text: str  # Final / 7:30 pm ET / PPD
    period: int
    game_clock: str
    game_time_utc: datetime = Field(alias="gameTimeUTC")
    game_et: datetime
    regulation_periods: int
    series_game_number: str
    game_label: str
    game_sub_label: str
    series_text: str
    if_necessary: bool
    series_conference: str
    po_round_desc: str
    game_subtype: str
    is_neutral: bool
    game_leaders: dict[str, Any] | None = None
    team_leaders: dict[str, Any] | None = None
    broadcasters: dict[str, Any] | None = None
    home_team: RawTeam
    away_team: RawTeam


class RawScoreboard(RawModel):
    game_date: str  # YYYY-MM-DD
    league_id: str
    league_name: str
    games: list[RawGame]


class RawScoreboardResponse(BaseModel):
    """Envelope exactly as nba_api returns it. Saved to disk as the test fixture."""

    model_config = ConfigDict(extra="forbid")

    meta: dict[str, Any]
    scoreboard: RawScoreboard

    @classmethod
    def parse(cls, payload: dict[str, Any]) -> "RawScoreboardResponse":
        try:
            return cls.model_validate(payload)
        except ValidationError as exc:
            raise SchemaDriftError(ENDPOINT, exc) from exc
