"""Clean model for one row of the `games` table."""

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class GameStatus(StrEnum):
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    FINAL = "final"
    POSTPONED = "postponed"


class SeasonType(StrEnum):
    """Derived from the third digit of game_id."""

    PRESEASON = "preseason"  # 001xxxxxxx
    REGULAR = "regular"  # 002xxxxxxx
    ALL_STAR = "all_star"  # 003xxxxxxx
    PLAYOFFS = "playoffs"  # 004xxxxxxx
    PLAY_IN = "play_in"  # 005xxxxxxx


class CleanGame(BaseModel):
    model_config = ConfigDict(frozen=True)

    game_id: str = Field(pattern=r"^\d{10}$")
    game_date: date
    season: str = Field(pattern=r"^\d{4}-\d{2}$")  # 2025-26
    season_type: SeasonType
    status: GameStatus
    status_text: str
    home_team_id: int
    away_team_id: int
    home_score: int | None  # None until the game starts; never 0 for a scheduled game
    away_score: int | None
    periods: int | None  # 4 = regulation, 5+ = OT; None until final
    national_tv: str | None
    game_sequence: int
    source_payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
