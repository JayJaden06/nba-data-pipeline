"""ESPN payloads -> the same clean models the nba_api path produces.

Ids. Games and players keep ESPN's ids: the NBA's ids can't be looked up from a cloud
runner, and a database never mixes sources (see load/meta.py). The 30 franchises are
mapped onto the NBA's team ids and tricodes, so a team means the same thing in every
database and the API's /teams/{id} is source-independent. Other clubs (preseason
opponents) keep ESPN's id and are flagged is_nba=false.

Precision. ESPN reports whole minutes per player, so seconds_played is minutes x 60 and
a player's figure can be up to 30 s off. Team minutes and team plus/minus are blank at
ESPN; both are fully determined by the score and the number of periods.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

from nba_pipeline.schemas.clean_box_stats import CleanPlayerGameStats, CleanTeamGameStats
from nba_pipeline.schemas.clean_game import CleanGame, GameStatus, SeasonType
from nba_pipeline.schemas.clean_player import CleanPlayer
from nba_pipeline.schemas.clean_team import CleanTeam
from nba_pipeline.schemas.raw_espn import (
    EXPECTED_STAT_KEYS,
    EspnAthleteRow,
    EspnCompetitor,
    EspnEvent,
    EspnScoreboard,
    EspnSummary,
    EspnTeam,
)
from nba_pipeline.transform.boxscore import BoxScoreRows

ET = ZoneInfo("America/New_York")
REGULATION_SECONDS = 14400
OVERTIME_SECONDS = 1500

# ESPN team id -> (ESPN abbreviation, NBA tricode, NBA team id). Built from ESPN's
# /teams list and nba_api's bundled static teams; ids 1-30 are the franchises.
ESPN_TEAMS: dict[int, tuple[str, str, int]] = {
    1: ("ATL", "ATL", 1610612737),
    2: ("BOS", "BOS", 1610612738),
    3: ("NO", "NOP", 1610612740),
    4: ("CHI", "CHI", 1610612741),
    5: ("CLE", "CLE", 1610612739),
    6: ("DAL", "DAL", 1610612742),
    7: ("DEN", "DEN", 1610612743),
    8: ("DET", "DET", 1610612765),
    9: ("GS", "GSW", 1610612744),
    10: ("HOU", "HOU", 1610612745),
    11: ("IND", "IND", 1610612754),
    12: ("LAC", "LAC", 1610612746),
    13: ("LAL", "LAL", 1610612747),
    14: ("MIA", "MIA", 1610612748),
    15: ("MIL", "MIL", 1610612749),
    16: ("MIN", "MIN", 1610612750),
    17: ("BKN", "BKN", 1610612751),
    18: ("NY", "NYK", 1610612752),
    19: ("ORL", "ORL", 1610612753),
    20: ("PHI", "PHI", 1610612755),
    21: ("PHX", "PHX", 1610612756),
    22: ("POR", "POR", 1610612757),
    23: ("SAC", "SAC", 1610612758),
    24: ("SA", "SAS", 1610612759),
    25: ("OKC", "OKC", 1610612760),
    26: ("UTAH", "UTA", 1610612762),
    27: ("WSH", "WAS", 1610612764),
    28: ("TOR", "TOR", 1610612761),
    29: ("MEM", "MEM", 1610612763),
    30: ("CHA", "CHA", 1610612766),
}

_SEASON_TYPES = {
    1: SeasonType.PRESEASON,
    2: SeasonType.REGULAR,
    3: SeasonType.PLAYOFFS,
    5: SeasonType.PLAY_IN,
}
_POSTPONED_NAMES = frozenset({"STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_SUSPENDED"})


def team_id(espn_id: int) -> int:
    """NBA team id for a franchise; ESPN's own id for anyone else."""
    mapped = ESPN_TEAMS.get(espn_id)
    return mapped[2] if mapped else espn_id


def _hash(*parts: Any) -> str:
    blob = json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


# --- scoreboard -----------------------------------------------------------------------


def to_clean_team(team: EspnTeam) -> CleanTeam:
    mapped = ESPN_TEAMS.get(team.id)
    return CleanTeam(
        team_id=mapped[2] if mapped else team.id,
        abbreviation=mapped[1] if mapped else team.abbreviation,
        city=team.location,
        name=team.name,
        full_name=team.display_name,
        is_nba=mapped is not None,
    )


def season_label(year: int) -> str:
    """ESPN labels a season by the year it ends: 2026 -> '2025-26'."""
    return f"{year - 1}-{year % 100:02d}"


def season_type(espn_type: int) -> SeasonType:
    try:
        return _SEASON_TYPES[espn_type]
    except KeyError as exc:
        raise ValueError(f"unknown ESPN season type {espn_type}") from exc


def status_from(event: EspnEvent) -> GameStatus:
    t = event.status.type
    if t.name in _POSTPONED_NAMES:
        return GameStatus.POSTPONED
    if t.state == "pre":
        return GameStatus.SCHEDULED
    if t.state == "in":
        return GameStatus.IN_PROGRESS
    return GameStatus.FINAL if t.completed else GameStatus.POSTPONED


def _side(event: EspnEvent, home_away: str) -> EspnCompetitor:
    return next(c for c in event.competitions[0].competitors if c.home_away == home_away)


def national_tv(event: EspnEvent) -> str | None:
    names: list[str] = []
    for b in event.competitions[0].broadcasts:
        if b.get("market") == "national":
            names.extend(str(n) for n in b.get("names") or [])
    return "/".join(names) or None


def to_clean_game(event: EspnEvent, game_sequence: int) -> CleanGame:
    status = status_from(event)
    started = status in (GameStatus.IN_PROGRESS, GameStatus.FINAL)
    home, away = _side(event, "home"), _side(event, "away")
    return CleanGame(
        game_id=str(event.id),
        game_date=event.date.astimezone(ET).date(),
        season=season_label(event.season.year),
        season_type=season_type(event.season.type),
        status=status,
        status_text=event.status.type.detail,
        home_team_id=team_id(home.team.id),
        away_team_id=team_id(away.team.id),
        home_score=int(home.score) if started else None,
        away_score=int(away.score) if started else None,
        periods=event.status.period if status is GameStatus.FINAL else None,
        national_tv=national_tv(event),
        game_sequence=game_sequence,
        source_payload_hash=_hash(
            event.id,
            event.date,
            event.status.model_dump(),
            event.season.model_dump(),
            [c.model_dump() for c in event.competitions[0].competitors],
            national_tv(event),
        ),
    )


def games_from_scoreboard(raw: EspnScoreboard) -> list[CleanGame]:
    return [to_clean_game(e, seq) for seq, e in enumerate(raw.events, start=1)]


def teams_from_scoreboard(raw: EspnScoreboard) -> list[CleanTeam]:
    seen: dict[int, CleanTeam] = {}
    for e in raw.events:
        for c in e.competitions[0].competitors:
            team = to_clean_team(c.team)
            seen.setdefault(team.team_id, team)
    return list(seen.values())


def scoreboard_day(raw: EspnScoreboard, game_date: date) -> EspnScoreboard:
    """Keep only games whose Eastern-time date is `game_date`.

    ESPN's `dates=` filter is close to, but not exactly, the Eastern-time date the NBA
    uses; filtering here keeps a re-run of a date idempotent.
    """
    events = [e for e in raw.events if e.date.astimezone(ET).date() == game_date]
    return raw.model_copy(update={"events": events})


# --- summary (box score) --------------------------------------------------------------


def _split(cell: str) -> tuple[int, int]:
    made, attempted = cell.split("-")
    return int(made), int(attempted)


def _int(cell: str) -> int:
    return int(cell.lstrip("+"))


def _minutes(cell: str) -> int:
    """Whole minutes. ESPN shows "--" for a player who appeared but for under 30 seconds
    (rounds to 0): he played, with 0 recorded minutes. "--" anywhere else still fails."""
    return 0 if cell == "--" else _int(cell)


def stat_values(cells: list[str], *, include_minutes_and_pm: bool) -> dict[str, int]:
    v = dict(zip(EXPECTED_STAT_KEYS, cells, strict=True))
    fgm, fga = _split(v["fieldGoalsMade-fieldGoalsAttempted"])
    fg3m, fg3a = _split(v["threePointFieldGoalsMade-threePointFieldGoalsAttempted"])
    ftm, fta = _split(v["freeThrowsMade-freeThrowsAttempted"])
    out = {
        "fgm": fgm,
        "fga": fga,
        "fg3m": fg3m,
        "fg3a": fg3a,
        "ftm": ftm,
        "fta": fta,
        "oreb": _int(v["offensiveRebounds"]),
        "dreb": _int(v["defensiveRebounds"]),
        "reb": _int(v["rebounds"]),
        "ast": _int(v["assists"]),
        "stl": _int(v["steals"]),
        "blk": _int(v["blocks"]),
        "tov": _int(v["turnovers"]),
        "pf": _int(v["fouls"]),
        "pts": _int(v["points"]),
    }
    if include_minutes_and_pm:
        out["seconds_played"] = _minutes(v["minutes"]) * 60
        out["plus_minus"] = _int(v["plusMinus"])
    return out


_ZERO = dict.fromkeys(
    ("fgm", "fga", "fg3m", "fg3a", "ftm", "fta", "oreb", "dreb", "reb",
     "ast", "stl", "blk", "tov", "pf", "pts", "seconds_played", "plus_minus"),
    0,
)  # fmt: skip


def _slug(row: EspnAthleteRow) -> str:
    for link in row.athlete.links:
        m = re.search(r"/player/_/id/\d+/([a-z0-9-]+)", str(link.get("href", "")))
        if m:
            return m.group(1)
    return re.sub(r"[^a-z0-9]+", "-", row.athlete.display_name.lower()).strip("-")


def to_player(row: EspnAthleteRow) -> CleanPlayer:
    first, _, last = row.athlete.display_name.partition(" ")
    return CleanPlayer(
        player_id=row.athlete.id, first_name=first, last_name=last or first, slug=_slug(row)
    )


def to_player_game_stats(game_id: str, team: int, row: EspnAthleteRow) -> CleanPlayerGameStats:
    played = not row.did_not_play and bool(row.stats)
    values = stat_values(row.stats, include_minutes_and_pm=True) if played else dict(_ZERO)
    position = row.athlete.position.abbreviation if row.athlete.position else None
    return CleanPlayerGameStats(
        game_id=game_id,
        player_id=row.athlete.id,
        team_id=team,
        starter=row.starter,
        position=position if row.starter else None,
        jersey=row.athlete.jersey or None,
        played=played,
        dnp_reason=None if played else (row.reason or None),
        source_payload_hash=_hash(game_id, team, row.model_dump(mode="json")),
        **values,
    )


def to_box_score_rows(raw: EspnSummary, game: CleanGame) -> BoxScoreRows:
    """Box score rows for `game`; scores and periods come from the scoreboard row."""
    if str(raw.header.id) != game.game_id:
        raise ValueError(f"summary is for event {raw.header.id}, expected {game.game_id}")
    if game.home_score is None or game.away_score is None:
        raise ValueError(f"game {game.game_id} has not started; no box score to load")

    home_away = {t.team.id: t.home_away for t in raw.boxscore.teams}
    periods = game.periods or 4
    team_seconds = REGULATION_SECONDS + OVERTIME_SECONDS * max(0, periods - 4)

    players: list[CleanPlayer] = []
    team_stats: list[CleanTeamGameStats] = []
    player_stats: list[CleanPlayerGameStats] = []
    for block in raw.boxscore.players:
        group = block.statistics[0]
        tid = team_id(block.team.id)
        is_home = home_away[block.team.id] == "home"
        own, opp = (
            (game.home_score, game.away_score) if is_home else (game.away_score, game.home_score)
        )
        totals = stat_values(group.totals, include_minutes_and_pm=False)
        if game.status is GameStatus.FINAL and totals["pts"] != own:
            raise ValueError(
                f"team {tid} box score totals {totals['pts']} pts != final score {own}"
            )
        team_stats.append(
            CleanTeamGameStats(
                game_id=game.game_id,
                team_id=tid,
                is_home=is_home,
                seconds_played=team_seconds,
                plus_minus=own - opp,
                source_payload_hash=_hash(game.game_id, tid, group.totals, team_seconds, own, opp),
                **totals,
            )
        )
        for row in group.athletes:
            players.append(to_player(row))
            player_stats.append(to_player_game_stats(game.game_id, tid, row))

    ids = [p.player_id for p in player_stats]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate player ids in box score for game {game.game_id}")
    team_stats.sort(key=lambda t: not t.is_home)  # home first, like the NBA path
    return BoxScoreRows(game.game_id, players, team_stats, player_stats)
