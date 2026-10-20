"""ESPN source: parsing, drift detection, transforms, and agreement with the NBA source."""

import copy
import unicodedata
from datetime import date
from typing import Any

import pytest

from nba_pipeline.schemas import SchemaDriftError
from nba_pipeline.schemas.clean_game import CleanGame, GameStatus, SeasonType
from nba_pipeline.schemas.raw_boxscore import RawBoxScoreResponse
from nba_pipeline.schemas.raw_espn import EspnScoreboard, EspnSummary
from nba_pipeline.transform import boxscore as nba_box
from nba_pipeline.transform import espn

OKC, MIN, POR = 1610612760, 1610612750, 1610612757
EVENT = "401810831"  # MIN @ OKC, 2026-03-15; NBA game 0022500976


def final_game(sb: dict[str, Any], event_id: str = EVENT) -> CleanGame:
    games = espn.games_from_scoreboard(EspnScoreboard.parse(sb))
    return next(g for g in games if g.game_id == event_id)


# --- parsing and drift ----------------------------------------------------------------


def test_parses_recorded_payloads(
    espn_scoreboard_final: dict[str, Any], espn_summary_final: dict[str, Any]
) -> None:
    sb = EspnScoreboard.parse(espn_scoreboard_final)
    assert len(sb.events) == 7
    summary = EspnSummary.parse(espn_summary_final)
    assert summary.header.id == int(EVENT)
    assert [len(p.statistics[0].athletes) for p in summary.boxscore.players] == [14, 13]


def test_reordered_stat_columns_are_drift(espn_summary_final: dict[str, Any]) -> None:
    payload = copy.deepcopy(espn_summary_final)
    keys = payload["boxscore"]["players"][0]["statistics"][0]["keys"]
    keys[1], keys[2] = keys[2], keys[1]
    with pytest.raises(SchemaDriftError, match="stat columns changed"):
        EspnSummary.parse(payload)


def test_new_field_on_player_row_is_drift(espn_summary_final: dict[str, Any]) -> None:
    payload = copy.deepcopy(espn_summary_final)
    payload["boxscore"]["players"][0]["statistics"][0]["athletes"][0]["dunks"] = 3
    with pytest.raises(SchemaDriftError) as exc:
        EspnSummary.parse(payload)
    assert exc.value.endpoint == "ESPN summary"


def test_short_stat_row_is_drift(espn_summary_final: dict[str, Any]) -> None:
    payload = copy.deepcopy(espn_summary_final)
    payload["boxscore"]["players"][0]["statistics"][0]["athletes"][0]["stats"].pop()
    with pytest.raises(SchemaDriftError):
        EspnSummary.parse(payload)


def test_unread_blocks_may_change(espn_scoreboard_final: dict[str, Any]) -> None:
    payload = copy.deepcopy(espn_scoreboard_final)
    payload["events"][0]["competitions"][0]["odds"] = {"anything": True}
    payload["events"][0]["newThing"] = [1, 2]
    EspnScoreboard.parse(payload)  # does not raise


# --- scoreboard transform -------------------------------------------------------------


def test_final_game(espn_scoreboard_final: dict[str, Any]) -> None:
    g = final_game(espn_scoreboard_final)
    assert g.game_date == date(2026, 3, 15)
    assert (g.season, g.season_type, g.status) == ("2025-26", SeasonType.REGULAR, GameStatus.FINAL)
    assert (g.home_team_id, g.away_team_id) == (OKC, MIN)  # mapped onto NBA team ids
    assert (g.home_score, g.away_score, g.periods) == (116, 103, 4)
    assert g.national_tv == "ABC"


def test_scheduled_day(espn_scoreboard_scheduled: dict[str, Any]) -> None:
    games = espn.games_from_scoreboard(EspnScoreboard.parse(espn_scoreboard_scheduled))
    assert len(games) == 11
    assert {g.status for g in games} == {GameStatus.SCHEDULED}
    assert all(g.home_score is None and g.periods is None for g in games)
    assert {g.season for g in games} == {"2026-27"}


def test_team_mapping(espn_scoreboard_final: dict[str, Any]) -> None:
    teams = {
        t.team_id: t
        for t in espn.teams_from_scoreboard(EspnScoreboard.parse(espn_scoreboard_final))
    }
    assert len(teams) == 14 and all(t.is_nba for t in teams.values())
    assert teams[1610612744].abbreviation == "GSW"  # ESPN "GS"
    assert teams[1610612762].abbreviation == "UTA"  # ESPN "UTAH"
    assert teams[1610612752].abbreviation == "NYK"  # ESPN "NY"
    assert len(espn.ESPN_TEAMS) == 30
    assert len({v[2] for v in espn.ESPN_TEAMS.values()}) == 30


def test_non_nba_opponent_keeps_espn_id(espn_scoreboard_intl: dict[str, Any]) -> None:
    teams = {
        t.team_id: t for t in espn.teams_from_scoreboard(EspnScoreboard.parse(espn_scoreboard_intl))
    }
    lions = teams[134478]
    assert (lions.abbreviation, lions.full_name, lions.is_nba) == ("LON", "London Lions", False)
    assert teams[POR].is_nba


@pytest.mark.parametrize(
    ("name", "state", "completed", "expected"),
    [
        ("STATUS_SCHEDULED", "pre", False, GameStatus.SCHEDULED),
        ("STATUS_IN_PROGRESS", "in", False, GameStatus.IN_PROGRESS),
        ("STATUS_HALFTIME", "in", False, GameStatus.IN_PROGRESS),
        ("STATUS_FINAL", "post", True, GameStatus.FINAL),
        ("STATUS_POSTPONED", "post", False, GameStatus.POSTPONED),
        ("STATUS_CANCELED", "post", False, GameStatus.POSTPONED),
        ("STATUS_POSTPONED", "pre", False, GameStatus.POSTPONED),
    ],
)
def test_status_mapping(
    espn_scoreboard_final: dict[str, Any],
    name: str,
    state: str,
    completed: bool,
    expected: GameStatus,
) -> None:
    payload = copy.deepcopy(espn_scoreboard_final)
    payload["events"][0]["status"]["type"].update(name=name, state=state, completed=completed)
    event = EspnScoreboard.parse(payload).events[0]
    assert espn.status_from(event) is expected


def test_season_types() -> None:
    assert espn.season_label(2026) == "2025-26"
    assert espn.season_label(2000) == "1999-00"
    assert espn.season_type(3) is SeasonType.PLAYOFFS
    assert espn.season_type(5) is SeasonType.PLAY_IN
    with pytest.raises(ValueError, match="season type"):
        espn.season_type(4)


def test_day_filter_uses_eastern_date(espn_scoreboard_final: dict[str, Any]) -> None:
    payload = copy.deepcopy(espn_scoreboard_final)
    # 03:30 UTC on the 16th is 23:30 Eastern on the 15th: same game day.
    payload["events"][0]["date"] = "2026-03-16T03:30Z"
    # 05:00 UTC on the 16th is 01:00 Eastern on the 16th: a different game day.
    payload["events"][1]["date"] = "2026-03-16T05:00Z"
    raw = espn.scoreboard_day(EspnScoreboard.parse(payload), date(2026, 3, 15))
    assert len(raw.events) == 6
    assert str(raw.events[0].id) == payload["events"][0]["id"]


# --- box score transform --------------------------------------------------------------


def test_box_score(
    espn_scoreboard_final: dict[str, Any], espn_summary_final: dict[str, Any]
) -> None:
    rows = espn.to_box_score_rows(
        EspnSummary.parse(espn_summary_final), final_game(espn_scoreboard_final)
    )
    home, away = rows.team_stats
    assert (home.team_id, home.is_home, home.pts, home.plus_minus, home.seconds_played) == (
        OKC,
        True,
        116,
        13,
        14400,
    )
    assert (away.team_id, away.is_home, away.pts, away.plus_minus) == (MIN, False, 103, -13)
    for team in rows.team_stats:
        mine = [p for p in rows.player_stats if p.team_id == team.team_id]
        assert sum(p.pts for p in mine) == team.pts
        assert sum(p.reb for p in mine) == team.reb
        assert sum(1 for p in mine if p.starter) == 5
        assert all(p.position for p in mine if p.starter)
        assert not any(p.position for p in mine if not p.starter)

    randle = next(p for p in rows.player_stats if p.player_id == 3064514)
    assert (randle.pts, randle.seconds_played, randle.plus_minus, randle.jersey) == (
        32,
        2100,
        -5,
        "30",
    )
    dnps = [p for p in rows.player_stats if not p.played]
    assert dnps and all(p.seconds_played == 0 and p.pts == 0 for p in dnps)
    assert all(p.dnp_reason for p in dnps)
    assert all(p.dnp_reason is None for p in rows.player_stats if p.played)

    sga = next(p for p in rows.players if p.last_name == "Gilgeous-Alexander")
    assert (sga.first_name, sga.slug) == ("Shai", "shai-gilgeous-alexander")


def test_overtime_box_score(espn_summary_ot: dict[str, Any]) -> None:
    sb = EspnScoreboard.parse(load_scoreboard("20261013"))
    game = next(g for g in espn.games_from_scoreboard(sb) if g.game_id == "401908621")
    assert game.periods == 5
    rows = espn.to_box_score_rows(EspnSummary.parse(espn_summary_ot), game)
    assert {t.seconds_played for t in rows.team_stats} == {15900}


def test_totals_must_match_final_score(
    espn_scoreboard_final: dict[str, Any], espn_summary_final: dict[str, Any]
) -> None:
    game = final_game(espn_scoreboard_final).model_copy(update={"home_score": 117})
    with pytest.raises(ValueError, match="final score"):
        espn.to_box_score_rows(EspnSummary.parse(espn_summary_final), game)


def test_summary_for_another_game_rejected(
    espn_scoreboard_final: dict[str, Any], espn_summary_final: dict[str, Any]
) -> None:
    game = final_game(espn_scoreboard_final, "401810832")
    with pytest.raises(ValueError, match="expected 401810832"):
        espn.to_box_score_rows(EspnSummary.parse(espn_summary_final), game)


def test_sub_30_second_appearance(espn_scoreboard_final: dict[str, Any]) -> None:
    """Recorded from a live run: Mo Bamba appeared for UTA with minutes "--"."""
    from tests.conftest import load_fixture

    summary = EspnSummary.parse(load_fixture("espn_summary_401810837.json"))
    rows = espn.to_box_score_rows(summary, final_game(espn_scoreboard_final, "401810837"))
    bamba = next(
        p
        for p in rows.player_stats
        if p.player_id == next(pl.player_id for pl in rows.players if pl.last_name == "Bamba")
    )
    assert (bamba.played, bamba.seconds_played, bamba.pts, bamba.dnp_reason) == (True, 0, 0, None)


def test_placeholder_outside_minutes_still_fails(
    espn_scoreboard_final: dict[str, Any], espn_summary_final: dict[str, Any]
) -> None:
    payload = copy.deepcopy(espn_summary_final)
    row = next(
        a for a in payload["boxscore"]["players"][0]["statistics"][0]["athletes"] if a["stats"]
    )
    row["stats"][1] = "--"  # points
    with pytest.raises(ValueError, match="invalid literal"):
        espn.to_box_score_rows(EspnSummary.parse(payload), final_game(espn_scoreboard_final))


# --- the two sources agree ------------------------------------------------------------


def _norm(name: str) -> str:
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return plain.lower().replace(".", "").removesuffix(" jr").strip()


STATS = ("fgm", "fga", "fg3m", "fg3a", "ftm", "fta", "oreb", "dreb", "reb",
         "ast", "stl", "blk", "tov", "pf", "pts", "plus_minus")  # fmt: skip


def test_espn_and_nba_agree_on_the_same_game(
    boxscore_final: dict[str, Any],
    espn_scoreboard_final: dict[str, Any],
    espn_summary_final: dict[str, Any],
) -> None:
    """Same game, two sources: every stat matches; minutes differ only by rounding."""
    nba = nba_box.to_box_score_rows(RawBoxScoreResponse.parse(boxscore_final))
    esp = espn.to_box_score_rows(
        EspnSummary.parse(espn_summary_final), final_game(espn_scoreboard_final)
    )

    for n_team, e_team in zip(nba.team_stats, esp.team_stats, strict=True):
        assert n_team.team_id == e_team.team_id and n_team.is_home == e_team.is_home
        assert {s: getattr(n_team, s) for s in STATS} == {s: getattr(e_team, s) for s in STATS}
        assert n_team.seconds_played == e_team.seconds_played

    nba_names = {p.player_id: _norm(f"{p.first_name} {p.last_name}") for p in nba.players}
    esp_names = {p.player_id: _norm(f"{p.first_name} {p.last_name}") for p in esp.players}
    nba_by_name = {nba_names[p.player_id]: p for p in nba.player_stats}
    esp_by_name = {esp_names[p.player_id]: p for p in esp.player_stats}
    assert set(nba_by_name) == set(esp_by_name)
    assert len(nba_by_name) == 27

    for name, n in nba_by_name.items():
        e = esp_by_name[name]
        assert (n.team_id, n.starter, n.played) == (e.team_id, e.starter, e.played), name
        assert {s: getattr(n, s) for s in STATS} == {s: getattr(e, s) for s in STATS}, name
        assert abs(n.seconds_played - e.seconds_played) <= 30, name


def load_scoreboard(day: str) -> dict[str, Any]:
    from tests.conftest import load_fixture

    return load_fixture(f"espn_scoreboard_{day}.json")
