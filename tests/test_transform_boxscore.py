import copy
from typing import Any

import pytest
from pydantic import ValidationError

from nba_pipeline.schemas.raw_boxscore import RawBoxScoreResponse
from nba_pipeline.transform.boxscore import (
    minutes_to_seconds,
    plus_minus_to_int,
    to_box_score_rows,
)


@pytest.mark.parametrize(
    ("minutes", "seconds"),
    [("240:00", 14400), ("265:00", 15900), ("17:39", 1059), ("0:00", 0), ("", 0)],
)
def test_minutes_to_seconds(minutes: str, seconds: int) -> None:
    assert minutes_to_seconds(minutes) == seconds


@pytest.mark.parametrize("bad", ["17", "17:60", "17:3", "PT17M39S", "abc"])
def test_minutes_to_seconds_rejects_garbage(bad: str) -> None:
    with pytest.raises(ValueError, match="minutes"):
        minutes_to_seconds(bad)


def test_plus_minus_must_be_integral() -> None:
    assert plus_minus_to_int(-6.0) == -6
    with pytest.raises(ValueError, match="plusMinus"):
        plus_minus_to_int(2.5)


def test_rows_for_regulation_game(boxscore_final: dict[str, Any]) -> None:
    rows = to_box_score_rows(RawBoxScoreResponse.parse(boxscore_final))
    assert rows.game_id == "0022500976"

    home, away = rows.team_stats
    assert (home.team_id, home.is_home, home.pts, home.seconds_played) == (
        1610612760,
        True,
        116,
        14400,
    )
    assert (away.team_id, away.is_home, away.pts) == (1610612750, False, 103)
    assert home.plus_minus == 13 and away.plus_minus == -13

    assert (
        len(rows.players)
        == len(rows.player_stats)
        == 13 + len(boxscore_final["boxScoreTraditional"]["awayTeam"]["players"])
    )
    assert len({p.player_id for p in rows.player_stats}) == len(rows.player_stats)

    for team in rows.team_stats:
        mine = [p for p in rows.player_stats if p.team_id == team.team_id]
        assert sum(1 for p in mine if p.starter) == 5
        assert sum(p.pts for p in mine) == team.pts
        assert sum(p.seconds_played for p in mine) == team.seconds_played
        assert sum(p.reb for p in mine) == team.reb


def test_dnp_player(boxscore_final: dict[str, Any]) -> None:
    rows = to_box_score_rows(RawBoxScoreResponse.parse(boxscore_final))
    dnps = [p for p in rows.player_stats if not p.played]
    assert dnps, "fixture should contain DNPs"
    for p in dnps:
        assert p.seconds_played == 0 and p.pts == 0 and not p.starter
        assert p.dnp_reason and p.dnp_reason.startswith(("DNP", "DND", "NWT"))
    played = [p for p in rows.player_stats if p.played]
    assert all(p.dnp_reason is None for p in played)


def test_starter_fields(boxscore_final: dict[str, Any]) -> None:
    rows = to_box_score_rows(RawBoxScoreResponse.parse(boxscore_final))
    dort = next(p for p in rows.player_stats if p.player_id == 1629652)
    assert (dort.starter, dort.position, dort.jersey, dort.seconds_played) == (
        True,
        "F",
        None,
        1059,
    )
    bench = next(p for p in rows.player_stats if not p.starter and p.played)
    assert bench.position is None


def test_overtime_minutes(boxscore_ot: dict[str, Any]) -> None:
    rows = to_box_score_rows(RawBoxScoreResponse.parse(boxscore_ot))
    assert {t.seconds_played for t in rows.team_stats} == {15900}


def test_player_identity(boxscore_final: dict[str, Any]) -> None:
    rows = to_box_score_rows(RawBoxScoreResponse.parse(boxscore_final))
    sga = next(p for p in rows.players if p.player_id == 1628983)
    assert (sga.first_name, sga.last_name, sga.slug) == (
        "Shai",
        "Gilgeous-Alexander",
        "shai-gilgeous-alexander",
    )


def test_inconsistent_stats_rejected(boxscore_final: dict[str, Any]) -> None:
    payload = copy.deepcopy(boxscore_final)
    stats = payload["boxScoreTraditional"]["homeTeam"]["players"][0]["statistics"]
    stats["fieldGoalsMade"] = stats["fieldGoalsAttempted"] + 1
    with pytest.raises(ValidationError, match="made exceeds attempted"):
        to_box_score_rows(RawBoxScoreResponse.parse(payload))


def test_duplicate_player_rejected(boxscore_final: dict[str, Any]) -> None:
    payload = copy.deepcopy(boxscore_final)
    players = payload["boxScoreTraditional"]["homeTeam"]["players"]
    players.append(copy.deepcopy(players[0]))
    with pytest.raises(ValueError, match="duplicate player"):
        to_box_score_rows(RawBoxScoreResponse.parse(payload))


def test_hash_changes_only_on_stored_fields(boxscore_final: dict[str, Any]) -> None:
    a = to_box_score_rows(RawBoxScoreResponse.parse(boxscore_final))
    payload = copy.deepcopy(boxscore_final)
    payload["boxScoreTraditional"]["homeTeam"]["players"][0]["statistics"]["points"] = 5
    b = to_box_score_rows(RawBoxScoreResponse.parse(payload))
    assert a.team_stats[0].source_payload_hash == b.team_stats[0].source_payload_hash
    assert a.player_stats[0].source_payload_hash != b.player_stats[0].source_payload_hash
    assert a.player_stats[1].source_payload_hash == b.player_stats[1].source_payload_hash
