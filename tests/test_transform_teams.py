from typing import Any

from nba_pipeline.schemas.raw_scoreboard import RawScoreboardResponse
from nba_pipeline.transform.teams import nba_team_ids, teams_from_scoreboard


def test_nba_team_ids_are_the_30_franchises() -> None:
    ids = nba_team_ids()
    assert len(ids) == 30
    assert 1610612760 in ids  # OKC


def test_teams_are_distinct_and_flagged(scoreboard_final: dict[str, Any]) -> None:
    teams = teams_from_scoreboard(RawScoreboardResponse.parse(scoreboard_final))
    assert len(teams) == 14  # 7 games, 14 distinct teams
    assert len({t.team_id for t in teams}) == 14
    assert all(t.is_nba for t in teams)
    okc = next(t for t in teams if t.team_id == 1610612760)
    assert (okc.abbreviation, okc.city, okc.name, okc.full_name) == (
        "OKC",
        "Oklahoma City",
        "Thunder",
        "Oklahoma City Thunder",
    )


def test_non_nba_opponent_is_flagged(scoreboard_intl: dict[str, Any]) -> None:
    teams = teams_from_scoreboard(RawScoreboardResponse.parse(scoreboard_intl))
    lions = next(t for t in teams if t.team_id == 50015)
    assert not lions.is_nba
    assert (lions.abbreviation, lions.full_name) == ("LON", "London Lions")
    assert sum(1 for t in teams if not t.is_nba) == 1
