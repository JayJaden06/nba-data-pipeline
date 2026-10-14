"""Clean model for one row of the `teams` table."""

from pydantic import BaseModel, ConfigDict, Field


class CleanTeam(BaseModel):
    model_config = ConfigDict(frozen=True)

    team_id: int
    abbreviation: str = Field(min_length=2, max_length=3)
    city: str
    name: str
    full_name: str
    is_nba: bool  # False for preseason opponents such as international clubs
