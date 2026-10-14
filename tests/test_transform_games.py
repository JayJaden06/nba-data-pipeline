import copy
from datetime import date
from typing import Any

import pytest

from nba_pipeline.schemas.clean_game import GameStatus, SeasonType
from nba_pipeline.schemas.raw_scoreboard import RawScoreboardResponse
from nba_pipeline.transform.games import (
    season_from_game_id,
    season_type_from_game_id,
    status_from,
    to_clean_games,
)


@pytest.mark.parametrize(
    ("game_id", "season", "season_type"),
    [
        ("0022500976", "2025-26", SeasonType.REGULAR),
        ("0012600003", "2026-27", SeasonType.PRESEASON),
        ("0042400101", "2024-25", SeasonType.PLAYOFFS),
        ("0052400001", "2024-25", SeasonType.PLAY_IN),
        ("0032400001", "2024-25", SeasonType.ALL_STAR),
    ],
)
def test_season_and_type_from_game_id(game_id: str, season: str, season_type: SeasonType) -> None:
    assert season_from_game_id(game_id) == season
    assert season_type_from_game_id(game_id) == season_type


def test_unknown_season_type_digit_raises() -> None:
    with pytest.raises(ValueError, match="season type"):
        season_type_from_game_id("0092500001")


@pytest.mark.parametrize(
    ("status_id", "text", "expected"),
    [
        (1, "7:30 pm ET", GameStatus.SCHEDULED),
        (2, "Q3 4:12", GameStatus.IN_PROGRESS),
        (3, "Final", GameStatus.FINAL),
        (3, "Final/OT", GameStatus.FINAL),
        (1, "PPD", GameStatus.POSTPONED),
        (3, "ppd", GameStatus.POSTPONED),
    ],
)
def test_status_mapping(status_id: int, text: str, expected: GameStatus) -> None:
    assert status_from(status_id, text) is expected


def test_unknown_status_id_raises() -> None:
    with pytest.raises(ValueError, match="gameStatus"):
        status_from(9, "???")


def test_final_day_transform(scoreboard_final: dict[str, Any]) -> None:
    games = to_clean_games(RawScoreboardResponse.parse(scoreboard_final))
    assert len(games) == 7
    assert [g.game_sequence for g in games] == list(range(1, 8))
    g = games[0]
    assert g.game_id == "0022500976"
    assert g.game_date == date(2026, 3, 15)
    assert g.season == "2025-26"
    assert g.season_type is SeasonType.REGULAR
    assert g.status is GameStatus.FINAL
    assert (g.home_team_id, g.away_team_id) == (1610612760, 1610612750)
    assert (g.home_score, g.away_score) == (116, 103)
    assert g.periods == 4
    assert g.national_tv == "ABC"
    assert len(g.source_payload_hash) == 64


def test_scheduled_day_has_null_scores(scoreboard_scheduled: dict[str, Any]) -> None:
    games = to_clean_games(RawScoreboardResponse.parse(scoreboard_scheduled))
    assert all(g.status is GameStatus.SCHEDULED for g in games)
    assert all(g.home_score is None and g.away_score is None for g in games)
    assert all(g.periods is None for g in games)
    assert {g.season for g in games} == {"2026-27"}
    assert {g.season_type for g in games} == {SeasonType.PRESEASON}


def test_postponed_game(scoreboard_scheduled: dict[str, Any]) -> None:
    payload = copy.deepcopy(scoreboard_scheduled)
    payload["scoreboard"]["games"][0]["gameStatusText"] = "PPD"
    games = to_clean_games(RawScoreboardResponse.parse(payload))
    assert games[0].status is GameStatus.POSTPONED
    assert games[0].home_score is None


def test_overtime_periods(scoreboard_final: dict[str, Any]) -> None:
    payload = copy.deepcopy(scoreboard_final)
    payload["scoreboard"]["games"][0]["period"] = 5
    payload["scoreboard"]["games"][0]["gameStatusText"] = "Final/OT"
    games = to_clean_games(RawScoreboardResponse.parse(payload))
    assert games[0].periods == 5


def test_hash_is_stable_and_sensitive(scoreboard_final: dict[str, Any]) -> None:
    a = to_clean_games(RawScoreboardResponse.parse(scoreboard_final))[0]
    b = to_clean_games(RawScoreboardResponse.parse(copy.deepcopy(scoreboard_final)))[0]
    assert a.source_payload_hash == b.source_payload_hash

    changed = copy.deepcopy(scoreboard_final)
    changed["scoreboard"]["games"][0]["homeTeam"]["score"] = 117
    c = to_clean_games(RawScoreboardResponse.parse(changed))[0]
    assert c.source_payload_hash != a.source_payload_hash

    # Leader stats churn after the fact; they must not count as a change.
    leaders = copy.deepcopy(scoreboard_final)
    leaders["scoreboard"]["games"][0]["teamLeaders"]["homeLeaders"]["points"] = 99.9
    d = to_clean_games(RawScoreboardResponse.parse(leaders))[0]
    assert d.source_payload_hash == a.source_payload_hash
