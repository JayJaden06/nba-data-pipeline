"""raw ScoreboardV3 -> CleanGame rows."""

from __future__ import annotations

import hashlib
import json
from datetime import date

from nba_pipeline.schemas.clean_game import CleanGame, GameStatus, SeasonType
from nba_pipeline.schemas.raw_scoreboard import RawGame, RawScoreboardResponse

_SEASON_TYPE_BY_DIGIT = {
    "1": SeasonType.PRESEASON,
    "2": SeasonType.REGULAR,
    "3": SeasonType.ALL_STAR,
    "4": SeasonType.PLAYOFFS,
    "5": SeasonType.PLAY_IN,
}

_STATUS_BY_ID = {1: GameStatus.SCHEDULED, 2: GameStatus.IN_PROGRESS, 3: GameStatus.FINAL}


def season_from_game_id(game_id: str) -> str:
    """0022500976 -> 2025-26. Digits 4-5 are the two-digit starting year of the season."""
    start = 2000 + int(game_id[3:5])
    return f"{start}-{(start + 1) % 100:02d}"


def season_type_from_game_id(game_id: str) -> SeasonType:
    try:
        return _SEASON_TYPE_BY_DIGIT[game_id[2]]
    except KeyError as exc:
        raise ValueError(f"unknown season type digit in game_id {game_id!r}") from exc


def status_from(game_status: int, game_status_text: str) -> GameStatus:
    """Postponed games keep status id 1 but say PPD in the text, so the text wins."""
    if "PPD" in game_status_text.upper():
        return GameStatus.POSTPONED
    try:
        return _STATUS_BY_ID[game_status]
    except KeyError as exc:
        raise ValueError(f"unknown gameStatus {game_status!r} ({game_status_text!r})") from exc


def national_tv(game: RawGame) -> str | None:
    if not game.broadcasters:
        return None
    national = game.broadcasters.get("nationalBroadcasters") or []
    displays = [b.get("broadcastDisplay") for b in national if isinstance(b, dict)]
    joined = "/".join(d for d in displays if d)
    return joined or None


def payload_hash(game: RawGame) -> str:
    """Stable hash of the fields we store, so re-runs can detect that nothing changed."""
    subset = game.model_dump(
        mode="json",
        by_alias=True,
        exclude={"game_leaders", "team_leaders", "broadcasters"},
    )
    subset["nationalTv"] = national_tv(game)
    blob = json.dumps(subset, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def to_clean_game(game: RawGame, game_date: date, game_sequence: int) -> CleanGame:
    status = status_from(game.game_status, game.game_status_text)
    started = status in (GameStatus.IN_PROGRESS, GameStatus.FINAL)
    return CleanGame(
        game_id=game.game_id,
        game_date=game_date,
        season=season_from_game_id(game.game_id),
        season_type=season_type_from_game_id(game.game_id),
        status=status,
        status_text=game.game_status_text.strip(),
        home_team_id=game.home_team.team_id,
        away_team_id=game.away_team.team_id,
        home_score=game.home_team.score if started else None,
        away_score=game.away_team.score if started else None,
        periods=game.period if status is GameStatus.FINAL else None,
        national_tv=national_tv(game),
        game_sequence=game_sequence,
        source_payload_hash=payload_hash(game),
    )


def to_clean_games(raw: RawScoreboardResponse) -> list[CleanGame]:
    game_date = date.fromisoformat(raw.scoreboard.game_date)
    return [
        to_clean_game(game, game_date, seq)
        for seq, game in enumerate(raw.scoreboard.games, start=1)
    ]
