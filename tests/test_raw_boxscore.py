import copy
from typing import Any

import pytest

from nba_pipeline.schemas import SchemaDriftError
from nba_pipeline.schemas.raw_boxscore import RawBoxScoreResponse


def test_parses_recorded_game(boxscore_final: dict[str, Any]) -> None:
    raw = RawBoxScoreResponse.parse(boxscore_final)
    box = raw.box_score_traditional
    assert box.game_id == "0022500976"
    assert (box.home_team_id, box.away_team_id) == (1610612760, 1610612750)
    assert box.home_team.statistics.points == 116
    assert box.home_team.statistics.minutes == "240:00"
    assert len(box.home_team.players) == 13
    dort = box.home_team.players[0]
    assert (dort.family_name, dort.position, dort.statistics.minutes) == ("Dort", "F", "17:39")


def test_parses_overtime_game(boxscore_ot: dict[str, Any]) -> None:
    box = RawBoxScoreResponse.parse(boxscore_ot).box_score_traditional
    assert box.home_team.statistics.minutes == "265:00"


def test_new_stat_column_is_schema_drift(boxscore_final: dict[str, Any]) -> None:
    payload = copy.deepcopy(boxscore_final)
    payload["boxScoreTraditional"]["homeTeam"]["statistics"]["dunks"] = 7
    with pytest.raises(SchemaDriftError) as exc:
        RawBoxScoreResponse.parse(payload)
    assert exc.value.endpoint == "BoxScoreTraditionalV3"
    assert "dunks" in str(exc.value)


def test_missing_player_field_is_schema_drift(boxscore_final: dict[str, Any]) -> None:
    payload = copy.deepcopy(boxscore_final)
    del payload["boxScoreTraditional"]["awayTeam"]["players"][3]["statistics"]["points"]
    with pytest.raises(SchemaDriftError):
        RawBoxScoreResponse.parse(payload)


def test_wrong_type_is_schema_drift(boxscore_final: dict[str, Any]) -> None:
    payload = copy.deepcopy(boxscore_final)
    payload["boxScoreTraditional"]["homeTeam"]["players"][0]["statistics"]["points"] = "three"
    with pytest.raises(SchemaDriftError):
        RawBoxScoreResponse.parse(payload)
