"""Raw models for BoxScoreTraditionalV3 (nba_api.stats.endpoints.BoxScoreTraditionalV3).

Same conventions as raw_scoreboard: camelCase aliases, extra="forbid" everywhere we
consume, SchemaDriftError on any mismatch.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic.alias_generators import to_camel

from nba_pipeline.schemas import SchemaDriftError

ENDPOINT = "BoxScoreTraditionalV3"


class RawModel(BaseModel):
    model_config = ConfigDict(extra="forbid", alias_generator=to_camel, populate_by_name=True)


class RawAggregateLine(RawModel):
    """Counting stats shared by the team total, starters, bench, and every player."""

    minutes: str  # "240:00", "17:39", or "" for a player who did not play
    field_goals_made: int
    field_goals_attempted: int
    field_goals_percentage: float
    three_pointers_made: int
    three_pointers_attempted: int
    three_pointers_percentage: float
    free_throws_made: int
    free_throws_attempted: int
    free_throws_percentage: float
    rebounds_offensive: int
    rebounds_defensive: int
    rebounds_total: int
    assists: int
    steals: int
    blocks: int
    turnovers: int
    fouls_personal: int
    points: int


class RawStatLine(RawAggregateLine):
    """Team total and per-player lines also carry plus/minus; starters/bench do not."""

    plus_minus_points: float  # arrives as 13.0; the transform requires it to be integral


class RawBoxPlayer(RawModel):
    person_id: int
    first_name: str
    family_name: str
    name_i: str  # "L. Dort"
    player_slug: str
    position: str  # "F" / "G" / "C" for starters, "" for the bench
    comment: str  # "" or a DNP / DND / NWT reason
    jersey_num: str
    statistics: RawStatLine


class RawBoxTeam(RawModel):
    team_id: int
    team_city: str
    team_name: str
    team_tricode: str
    team_slug: str
    players: list[RawBoxPlayer]
    statistics: RawStatLine
    starters: RawAggregateLine
    bench: RawAggregateLine


class RawBoxScore(RawModel):
    game_id: str = Field(pattern=r"^\d{10}$")
    away_team_id: int
    home_team_id: int
    home_team: RawBoxTeam
    away_team: RawBoxTeam


class RawBoxScoreResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meta: dict[str, Any]
    box_score_traditional: RawBoxScore = Field(alias="boxScoreTraditional")

    @classmethod
    def parse(cls, payload: dict[str, Any]) -> "RawBoxScoreResponse":
        try:
            return cls.model_validate(payload)
        except ValidationError as exc:
            raise SchemaDriftError(ENDPOINT, exc) from exc
