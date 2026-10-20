"""Raw models for ESPN's public NBA JSON (site.api.espn.com).

Two endpoints: `scoreboard?dates=YYYYMMDD` (a day's games) and `summary?event=ID` (one
game's box score). Both payloads are large and carry many blocks we never read (odds,
news, leaders, videos), so the strictness is placed where drift would corrupt data:

* the per-player box score row is extra="forbid";
* the stat column list (`keys`) must equal EXPECTED_STAT_KEYS exactly, because stats
  arrive as positional string arrays and a reordered or added column would silently
  shift every value;
* every field we read is required and typed.

Everything else is extra="ignore". Any mismatch raises SchemaDriftError before load.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from nba_pipeline.schemas import SchemaDriftError

SCOREBOARD = "ESPN scoreboard"
SUMMARY = "ESPN summary"

EXPECTED_STAT_KEYS: tuple[str, ...] = (
    "minutes",
    "points",
    "fieldGoalsMade-fieldGoalsAttempted",
    "threePointFieldGoalsMade-threePointFieldGoalsAttempted",
    "freeThrowsMade-freeThrowsAttempted",
    "rebounds",
    "assists",
    "turnovers",
    "steals",
    "blocks",
    "offensiveRebounds",
    "defensiveRebounds",
    "fouls",
    "plusMinus",
)


class Loose(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# --- scoreboard -----------------------------------------------------------------------


class EspnTeam(Loose):
    id: int
    abbreviation: str
    display_name: str = Field(alias="displayName")
    location: str
    name: str


class EspnCompetitor(Loose):
    id: int
    home_away: str = Field(alias="homeAway", pattern="^(home|away)$")
    team: EspnTeam
    score: str  # "116"; "0" before tip-off


class EspnCompetition(Loose):
    id: int
    competitors: list[EspnCompetitor] = Field(min_length=2, max_length=2)
    broadcasts: list[dict[str, Any]] = Field(default_factory=list)


class EspnStatusType(Loose):
    name: str  # STATUS_SCHEDULED, STATUS_IN_PROGRESS, STATUS_FINAL, STATUS_POSTPONED, ...
    state: str = Field(pattern="^(pre|in|post)$")
    completed: bool
    detail: str


class EspnStatus(Loose):
    period: int
    type: EspnStatusType


class EspnSeason(Loose):
    year: int  # the year the season ends: 2026 for 2025-26
    type: int  # 1 preseason, 2 regular, 3 postseason, 5 play-in


class EspnEvent(Loose):
    id: int
    date: datetime  # UTC tip-off time
    season: EspnSeason
    status: EspnStatus
    competitions: list[EspnCompetition] = Field(min_length=1, max_length=1)


class EspnScoreboard(Loose):
    events: list[EspnEvent]

    @classmethod
    def parse(cls, payload: dict[str, Any]) -> EspnScoreboard:
        try:
            return cls.model_validate(payload)
        except ValidationError as exc:
            raise SchemaDriftError(SCOREBOARD, exc) from exc


# --- summary (box score) --------------------------------------------------------------


class EspnPosition(Loose):
    abbreviation: str


class EspnAthlete(Loose):
    id: int
    display_name: str = Field(alias="displayName")
    jersey: str | None = None
    position: EspnPosition | None = None
    links: list[dict[str, Any]] = Field(default_factory=list)


class EspnAthleteRow(Strict):
    active: bool
    athlete: EspnAthlete
    starter: bool
    did_not_play: bool = Field(alias="didNotPlay")
    reason: str | None = None  # only meaningful when did_not_play
    ejected: bool
    stats: list[str]  # positional, aligned with EXPECTED_STAT_KEYS; [] for a DNP

    @field_validator("stats")
    @classmethod
    def _aligned(cls, stats: list[str]) -> list[str]:
        if stats and len(stats) != len(EXPECTED_STAT_KEYS):
            raise ValueError(f"expected {len(EXPECTED_STAT_KEYS)} stat cells, got {len(stats)}")
        return stats


class EspnStatGroup(Loose):
    keys: list[str]
    athletes: list[EspnAthleteRow]
    totals: list[str]

    @field_validator("keys")
    @classmethod
    def _expected_columns(cls, keys: list[str]) -> list[str]:
        if tuple(keys) != EXPECTED_STAT_KEYS:
            raise ValueError(f"stat columns changed: {keys}")
        return keys


class EspnTeamRef(Loose):
    id: int
    abbreviation: str


class EspnPlayersBlock(Loose):
    team: EspnTeamRef
    statistics: list[EspnStatGroup] = Field(min_length=1, max_length=1)


class EspnBoxTeam(Loose):
    team: EspnTeamRef
    home_away: str = Field(alias="homeAway", pattern="^(home|away)$")


class EspnBoxScore(Loose):
    teams: list[EspnBoxTeam] = Field(min_length=2, max_length=2)
    players: list[EspnPlayersBlock] = Field(min_length=2, max_length=2)


class EspnHeaderCompetition(Loose):
    id: int


class EspnHeader(Loose):
    id: int
    competitions: list[EspnHeaderCompetition] = Field(min_length=1, max_length=1)


class EspnSummary(Loose):
    header: EspnHeader
    boxscore: EspnBoxScore

    @classmethod
    def parse(cls, payload: dict[str, Any]) -> EspnSummary:
        try:
            return cls.model_validate(payload)
        except ValidationError as exc:
            raise SchemaDriftError(SUMMARY, exc) from exc
