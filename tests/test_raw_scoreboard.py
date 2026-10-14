import copy
from typing import Any

import pytest

from nba_pipeline.schemas import SchemaDriftError
from nba_pipeline.schemas.raw_scoreboard import RawScoreboardResponse


def test_parses_recorded_final_day(scoreboard_final: dict[str, Any]) -> None:
    raw = RawScoreboardResponse.parse(scoreboard_final)
    assert raw.scoreboard.game_date == "2026-03-15"
    assert len(raw.scoreboard.games) == 7
    game = raw.scoreboard.games[0]
    assert game.game_id == "0022500976"
    assert game.game_status == 3
    assert game.home_team.team_tricode == "OKC"
    assert [p.score for p in game.home_team.periods] == [23, 24, 33, 36]


def test_parses_recorded_scheduled_day(scoreboard_scheduled: dict[str, Any]) -> None:
    raw = RawScoreboardResponse.parse(scoreboard_scheduled)
    assert all(g.game_status == 1 for g in raw.scoreboard.games)
    assert all(g.home_team.score == 0 for g in raw.scoreboard.games)


def test_unexpected_game_key_is_schema_drift(scoreboard_final: dict[str, Any]) -> None:
    payload = copy.deepcopy(scoreboard_final)
    payload["scoreboard"]["games"][0]["arenaName"] = "Paycom Center"
    with pytest.raises(SchemaDriftError) as exc:
        RawScoreboardResponse.parse(payload)
    assert exc.value.endpoint == "ScoreboardV3"
    assert "arenaName" in str(exc.value)


def test_missing_required_key_is_schema_drift(scoreboard_final: dict[str, Any]) -> None:
    payload = copy.deepcopy(scoreboard_final)
    del payload["scoreboard"]["games"][0]["homeTeam"]["score"]
    with pytest.raises(SchemaDriftError):
        RawScoreboardResponse.parse(payload)


def test_unconsumed_blocks_tolerate_drift(scoreboard_final: dict[str, Any]) -> None:
    payload = copy.deepcopy(scoreboard_final)
    payload["scoreboard"]["games"][0]["broadcasters"]["newThing"] = [1, 2, 3]
    payload["scoreboard"]["games"][0]["teamLeaders"]["homeLeaders"]["steals"] = 2.5
    RawScoreboardResponse.parse(payload)  # does not raise


def test_bad_game_id_shape_rejected(scoreboard_final: dict[str, Any]) -> None:
    payload = copy.deepcopy(scoreboard_final)
    payload["scoreboard"]["games"][0]["gameId"] = "22500976"
    with pytest.raises(SchemaDriftError):
        RawScoreboardResponse.parse(payload)
