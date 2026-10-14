"""raw BoxScoreTraditionalV3 -> players, team_game_stats, player_game_stats rows."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from nba_pipeline.schemas.clean_box_stats import (
    STAT_FIELDS,
    CleanPlayerGameStats,
    CleanTeamGameStats,
)
from nba_pipeline.schemas.clean_player import CleanPlayer
from nba_pipeline.schemas.raw_boxscore import (
    RawBoxPlayer,
    RawBoxScoreResponse,
    RawBoxTeam,
    RawStatLine,
)

_MINUTES = re.compile(r"^(\d+):([0-5]\d)$")


@dataclass(frozen=True)
class BoxScoreRows:
    game_id: str
    players: list[CleanPlayer]
    team_stats: list[CleanTeamGameStats]
    player_stats: list[CleanPlayerGameStats]


def minutes_to_seconds(minutes: str) -> int:
    """'240:00' -> 14400, '17:39' -> 1059, '' -> 0 (did not play)."""
    if minutes == "":
        return 0
    match = _MINUTES.match(minutes)
    if not match:
        raise ValueError(f"unparseable minutes {minutes!r}")
    return int(match.group(1)) * 60 + int(match.group(2))


def plus_minus_to_int(value: float) -> int:
    if value != int(value):
        raise ValueError(f"non-integral plusMinusPoints {value!r}")
    return int(value)


def _stat_values(line: RawStatLine) -> dict[str, Any]:
    values: dict[str, Any] = {clean: getattr(line, raw) for clean, raw in STAT_FIELDS}
    values["seconds_played"] = minutes_to_seconds(line.minutes)
    values["plus_minus"] = plus_minus_to_int(line.plus_minus_points)
    return values


def _hash(*parts: Any) -> str:
    blob = json.dumps(parts, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def to_player(player: RawBoxPlayer) -> CleanPlayer:
    return CleanPlayer(
        player_id=player.person_id,
        first_name=player.first_name,
        last_name=player.family_name,
        slug=player.player_slug,
    )


def to_team_game_stats(game_id: str, team: RawBoxTeam, *, is_home: bool) -> CleanTeamGameStats:
    stats = team.statistics.model_dump(mode="json")
    return CleanTeamGameStats(
        game_id=game_id,
        team_id=team.team_id,
        is_home=is_home,
        source_payload_hash=_hash(game_id, team.team_id, is_home, stats),
        **_stat_values(team.statistics),
    )


def to_player_game_stats(game_id: str, team_id: int, player: RawBoxPlayer) -> CleanPlayerGameStats:
    played = player.statistics.minutes != ""
    return CleanPlayerGameStats(
        game_id=game_id,
        player_id=player.person_id,
        team_id=team_id,
        starter=player.position != "",
        position=player.position or None,
        jersey=player.jersey_num or None,
        played=played,
        dnp_reason=None if played else (player.comment or None),
        source_payload_hash=_hash(game_id, team_id, player.model_dump(mode="json")),
        **_stat_values(player.statistics),
    )


def to_box_score_rows(raw: RawBoxScoreResponse) -> BoxScoreRows:
    box = raw.box_score_traditional
    players: list[CleanPlayer] = []
    team_stats: list[CleanTeamGameStats] = []
    player_stats: list[CleanPlayerGameStats] = []
    for team, is_home in ((box.home_team, True), (box.away_team, False)):
        team_stats.append(to_team_game_stats(box.game_id, team, is_home=is_home))
        for player in team.players:
            players.append(to_player(player))
            player_stats.append(to_player_game_stats(box.game_id, team.team_id, player))

    ids = [p.player_id for p in player_stats]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate player ids in box score for game {box.game_id}")
    return BoxScoreRows(box.game_id, players, team_stats, player_stats)
