"""Response models for the read API.

Kept separate from the clean_* models on purpose: the API can add derived fields
(minutes string, percentages, W/L) and hide bookkeeping without touching the pipeline's
storage contract.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel

STAT_COLUMNS = (
    "fgm", "fga", "fg3m", "fg3a", "ftm", "fta",
    "oreb", "dreb", "reb", "ast", "stl", "blk", "tov", "pf", "pts",
)  # fmt: skip


# --- runs and quality ---------------------------------------------------------------


class RowCounts(BaseModel):
    inserted: int
    updated: int
    unchanged: int


class QualityResult(BaseModel):
    check_name: str
    status: Literal["pass", "warn", "fail", "error"]
    details: dict[str, Any]
    checked_at: datetime


class RunSummary(BaseModel):
    run_id: int
    game_date: date
    kind: Literal["ingest", "check"]
    status: Literal["running", "succeeded", "failed"]
    started_at: datetime
    finished_at: datetime | None
    games_total: int
    box_scores_loaded: int
    box_scores_failed: int
    rows: RowCounts
    errors: list[dict[str, Any]]
    quality: list[QualityResult]


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    database: Literal["ok", "unreachable"]
    latest_run: RunSummary | None


class QualityReport(BaseModel):
    game_date: date
    run_id: int
    checked_at: datetime
    overall: Literal["pass", "warn", "fail", "error"]
    results: list[QualityResult]


# --- games and stats ------------------------------------------------------------------


class TeamRef(BaseModel):
    team_id: int
    abbreviation: str
    full_name: str


class PlayerRef(BaseModel):
    player_id: int
    name: str
    slug: str


class Game(BaseModel):
    game_id: str
    game_date: date
    season: str
    season_type: str
    status: str
    home: TeamRef
    away: TeamRef
    home_score: int | None
    away_score: int | None
    periods: int | None
    national_tv: str | None
    last_updated_at: datetime


class StatLine(BaseModel):
    seconds_played: int
    minutes: str  # "35:12", derived from seconds_played
    fgm: int
    fga: int
    fg3m: int
    fg3a: int
    ftm: int
    fta: int
    oreb: int
    dreb: int
    reb: int
    ast: int
    stl: int
    blk: int
    tov: int
    pf: int
    pts: int
    plus_minus: int
    fg_pct: float | None  # None when there were no attempts
    fg3_pct: float | None
    ft_pct: float | None

    @classmethod
    def from_row(cls, row: Mapping[Any, Any]) -> StatLine:
        return cls(**stat_fields(row))


class PlayerLine(StatLine):
    player_id: int
    name: str
    starter: bool
    position: str | None
    played: bool
    dnp_reason: str | None


class TeamBoxScore(StatLine):
    team: TeamRef
    is_home: bool
    players: list[PlayerLine]  # starters first, then bench by seconds played


class GameDetail(Game):
    box_score: list[TeamBoxScore] | None  # None until a box score is loaded; home first


class PlayerGameLine(StatLine):
    game_id: str
    game_date: date
    team: TeamRef
    opponent: TeamRef
    is_home: bool
    starter: bool
    played: bool
    dnp_reason: str | None
    result: Literal["W", "L"] | None  # None unless the game is final


class PlayerGames(BaseModel):
    player: PlayerRef
    season: str
    games: list[PlayerGameLine]  # newest first
    totals: StatLine  # over games played


class TeamGameLine(BaseModel):
    game_id: str
    game_date: date
    status: str
    opponent: TeamRef
    is_home: bool
    result: Literal["W", "L"] | None
    team_score: int | None
    opponent_score: int | None
    stats: StatLine | None  # None until the box score is loaded


class TeamGames(BaseModel):
    team: TeamRef
    season: str
    record: str  # "41-27", final games only
    games: list[TeamGameLine]  # newest first


# --- derived-field helpers ------------------------------------------------------------


def minutes_str(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}"


def pct(made: int, attempted: int) -> float | None:
    return round(made / attempted, 3) if attempted else None


def stat_fields(row: Mapping[Any, Any]) -> dict[str, Any]:
    """Pull the stat columns out of a row mapping and add the derived fields."""
    fields: dict[str, Any] = {c: row[c] for c in STAT_COLUMNS}
    fields["seconds_played"] = row["seconds_played"]
    fields["plus_minus"] = row["plus_minus"]
    fields["minutes"] = minutes_str(row["seconds_played"])
    fields["fg_pct"] = pct(row["fgm"], row["fga"])
    fields["fg3_pct"] = pct(row["fg3m"], row["fg3a"])
    fields["ft_pct"] = pct(row["ftm"], row["fta"])
    return fields


def result_for(team_score: int | None, opponent_score: int | None, status: str) -> str | None:
    if status != "final" or team_score is None or opponent_score is None:
        return None
    return "W" if team_score > opponent_score else "L"
