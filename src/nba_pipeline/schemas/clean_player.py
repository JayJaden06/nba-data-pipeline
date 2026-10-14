"""Clean model for one row of the `players` table. Identity only; team is per game."""

from pydantic import BaseModel, ConfigDict


class CleanPlayer(BaseModel):
    model_config = ConfigDict(frozen=True)

    player_id: int
    first_name: str
    last_name: str
    slug: str
