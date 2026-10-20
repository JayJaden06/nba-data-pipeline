"""Clean models for `team_game_stats` and `player_game_stats`.

Percentages are not stored; they are derived from made/attempted when queried.
Minutes are stored as integer seconds.
"""

from pydantic import BaseModel, ConfigDict, Field, model_validator

from nba_pipeline.schemas.clean_game import GAME_ID_PATTERN

# (clean column, raw RawStatLine field) for the 15 counting stats, in table order.
STAT_FIELDS: tuple[tuple[str, str], ...] = (
    ("fgm", "field_goals_made"),
    ("fga", "field_goals_attempted"),
    ("fg3m", "three_pointers_made"),
    ("fg3a", "three_pointers_attempted"),
    ("ftm", "free_throws_made"),
    ("fta", "free_throws_attempted"),
    ("oreb", "rebounds_offensive"),
    ("dreb", "rebounds_defensive"),
    ("reb", "rebounds_total"),
    ("ast", "assists"),
    ("stl", "steals"),
    ("blk", "blocks"),
    ("tov", "turnovers"),
    ("pf", "fouls_personal"),
    ("pts", "points"),
)


class StatLine(BaseModel):
    model_config = ConfigDict(frozen=True)

    seconds_played: int = Field(ge=0)
    fgm: int = Field(ge=0)
    fga: int = Field(ge=0)
    fg3m: int = Field(ge=0)
    fg3a: int = Field(ge=0)
    ftm: int = Field(ge=0)
    fta: int = Field(ge=0)
    oreb: int = Field(ge=0)
    dreb: int = Field(ge=0)
    reb: int = Field(ge=0)
    ast: int = Field(ge=0)
    stl: int = Field(ge=0)
    blk: int = Field(ge=0)
    tov: int = Field(ge=0)
    pf: int = Field(ge=0)
    pts: int = Field(ge=0)
    plus_minus: int

    @model_validator(mode="after")
    def _internally_consistent(self) -> "StatLine":
        if self.fgm > self.fga or self.fg3m > self.fg3a or self.ftm > self.fta:
            raise ValueError("made exceeds attempted")
        if self.fg3m > self.fgm or self.fg3a > self.fga:
            raise ValueError("three-pointers exceed field goals")
        if self.reb != self.oreb + self.dreb:
            raise ValueError("rebounds_total != offensive + defensive")
        return self


class CleanTeamGameStats(StatLine):
    game_id: str = Field(pattern=GAME_ID_PATTERN)
    team_id: int
    is_home: bool
    source_payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class CleanPlayerGameStats(StatLine):
    game_id: str = Field(pattern=GAME_ID_PATTERN)
    player_id: int
    team_id: int
    starter: bool
    position: str | None  # starting position only
    jersey: str | None
    played: bool
    dnp_reason: str | None  # None when the player played
    source_payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _dnp_consistent(self) -> "CleanPlayerGameStats":
        if not self.played and self.seconds_played != 0:
            raise ValueError("did not play but has minutes")
        if self.starter and not self.played:
            raise ValueError("starter marked as did not play")
        return self
