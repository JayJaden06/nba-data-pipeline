"""Integration tests for each quality check against seeded, then deliberately broken, data."""

from collections.abc import Iterator
from datetime import date
from typing import Any

import pytest
from sqlalchemy import Engine, text

from nba_pipeline.pipeline import check_date, ingest_date
from nba_pipeline.quality import CheckContext, CheckStatus
from nba_pipeline.quality.box_checks import (
    BoxScoresComplete,
    NoDuplicatePlayerRows,
    TeamMinutesSum,
    TeamPointsMatchPlayers,
)
from nba_pipeline.quality.run_checks import Freshness, SchemaDrift
from nba_pipeline.quality.runner import run_checks
from nba_pipeline.sources import NbaSource
from tests.conftest import FakeNbaApiClient, migrated_engine

pytestmark = pytest.mark.integration

GAME_DATE = date(2026, 3, 15)
TODAY = date(2026, 3, 16)
GAME_ID = "0022500976"
OKC = 1610612760


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    yield from migrated_engine()


@pytest.fixture(autouse=True)
def seeded(
    engine: Engine, scoreboard_final: dict[str, Any], boxscore_final: dict[str, Any]
) -> None:
    """One final game with its box score loaded, via the real pipeline and a fake client."""
    with engine.begin() as conn:
        for table in (
            "quality_results",
            "player_game_stats",
            "team_game_stats",
            "players",
            "games",
            "ingest_runs",
        ):
            conn.execute(text(f"DELETE FROM {table}"))
    payload = {**scoreboard_final, "scoreboard": {**scoreboard_final["scoreboard"]}}
    payload["scoreboard"]["games"] = scoreboard_final["scoreboard"]["games"][:1]
    client = FakeNbaApiClient(
        {
            ("ScoreboardV3", "2026-03-15"): payload,
            ("BoxScoreTraditionalV3", GAME_ID): boxscore_final,
        }
    )
    summary = ingest_date(engine, NbaSource(client), GAME_DATE, today=TODAY)
    assert summary.ok


def ctx(**kw: Any) -> CheckContext:
    return CheckContext(**({"game_date": GAME_DATE, "today": TODAY} | kw))


def sql(engine: Engine, statement: str, **params: Any) -> None:
    with engine.begin() as conn:
        conn.execute(text(statement), params)


def test_baseline_all_pass(engine: Engine) -> None:
    with engine.connect() as conn:
        results = run_checks(conn, ctx())
    assert {r.check_name: r.status for r in results} == {
        "box_scores_complete": CheckStatus.PASS,
        "no_duplicate_player_rows": CheckStatus.PASS,
        "team_points_match_players": CheckStatus.PASS,
        "team_minutes_sum": CheckStatus.PASS,
        "schema_drift": CheckStatus.PASS,
        "freshness": CheckStatus.PASS,
    }
    assert all("message" in r.details for r in results)


def test_box_scores_complete(engine: Engine) -> None:
    sql(engine, "DELETE FROM player_game_stats; DELETE FROM team_game_stats")
    with engine.connect() as conn:
        r = BoxScoresComplete().run(conn, ctx())
    assert r.status is CheckStatus.FAIL
    assert r.details["missing_final"] == [GAME_ID]

    sql(engine, "UPDATE games SET status = 'in_progress' WHERE game_id = :g", g=GAME_ID)
    with engine.connect() as conn:
        r = BoxScoresComplete().run(conn, ctx())
    assert r.status is CheckStatus.WARN
    assert r.details == {"missing_final": [], "pending": [GAME_ID], "message": r.details["message"]}

    sql(engine, "UPDATE games SET status = 'postponed', home_score = NULL, away_score = NULL")
    with engine.connect() as conn:
        assert BoxScoresComplete().run(conn, ctx()).status is CheckStatus.PASS


def test_no_duplicate_player_rows_passes_by_construction(engine: Engine) -> None:
    with engine.connect() as conn:
        assert NoDuplicatePlayerRows().run(conn, ctx()).status is CheckStatus.PASS


def test_team_points_match_players(engine: Engine) -> None:
    sql(
        engine,
        "UPDATE player_game_stats SET pts = pts + 2 "
        "WHERE game_id = :g AND team_id = :t AND starter",
        g=GAME_ID,
        t=OKC,
    )
    with engine.connect() as conn:
        r = TeamPointsMatchPlayers().run(conn, ctx())
    assert r.status is CheckStatus.FAIL
    assert r.details["mismatches"] == [
        {"game_id": GAME_ID, "team_id": OKC, "team_pts": 116, "player_pts": 126}
    ]


def test_team_minutes_sum(engine: Engine) -> None:
    # A whole missing player (20 minutes) is outside the tolerance.
    sql(
        engine,
        "DELETE FROM player_game_stats WHERE game_id = :g AND team_id = :t AND player_id = 1629652",
        g=GAME_ID,
        t=OKC,
    )
    with engine.connect() as conn:
        r = TeamMinutesSum().run(conn, ctx())
    assert r.status is CheckStatus.FAIL
    (problem,) = r.details["problems"]
    assert problem["team_id"] == OKC and problem["expected"] == 14400
    assert problem["team_seconds"] - problem["player_seconds"] == 1059

    # Overtime: periods = 5 means 15900 expected seconds.
    sql(engine, "UPDATE games SET periods = 5 WHERE game_id = :g", g=GAME_ID)
    sql(engine, "UPDATE team_game_stats SET seconds_played = 15900 WHERE team_id <> :t", t=OKC)
    with engine.connect() as conn:
        r = TeamMinutesSum().run(conn, ctx())
    assert {p["team_id"] for p in r.details["problems"]} == {OKC, 1610612750}  # OKC still broken
    away = next(p for p in r.details["problems"] if p["team_id"] != OKC)
    assert away["expected"] == 15900 and away["team_seconds"] == 15900  # players sum is now short


def test_team_minutes_tolerates_rounding(engine: Engine) -> None:
    sql(engine, "UPDATE team_game_stats SET seconds_played = seconds_played + 45")
    with engine.connect() as conn:
        assert TeamMinutesSum().run(conn, ctx()).status is CheckStatus.PASS


def test_schema_drift_reads_run_errors(engine: Engine) -> None:
    errors = [
        {
            "game_id": "0022500977",
            "error": "SchemaDriftError: schema drift in BoxScoreTraditionalV3",
        },
        {"game_id": "0022500978", "error": "NbaApiError: gave up"},
    ]
    with engine.connect() as conn:
        r = SchemaDrift().run(conn, ctx(ingest_errors=errors))
    assert r.status is CheckStatus.FAIL
    assert [e["game_id"] for e in r.details["errors"]] == ["0022500977"]


def test_freshness(engine: Engine) -> None:
    with engine.connect() as conn:
        assert Freshness().run(conn, ctx()).status is CheckStatus.PASS
        assert Freshness().run(conn, ctx(today=date(2026, 3, 17))).status is CheckStatus.PASS
        stale = Freshness().run(conn, ctx(today=date(2026, 3, 20)))
    assert stale.status is CheckStatus.WARN  # no later runs found games: offseason/break
    assert stale.details["gap_days"] == 5

    sql(
        engine,
        "INSERT INTO ingest_runs (game_date, status, games_total) "
        "VALUES ('2026-03-18', 'succeeded', 4)",
    )
    with engine.connect() as conn:
        r = Freshness().run(conn, ctx(today=date(2026, 3, 20)))
    assert r.status is CheckStatus.FAIL  # games existed on 03-18 but no finals were loaded

    sql(engine, "DELETE FROM player_game_stats; DELETE FROM team_game_stats; DELETE FROM games")
    with engine.connect() as conn:
        assert Freshness().run(conn, ctx()).status is CheckStatus.WARN


def test_check_date_records_a_check_run(engine: Engine) -> None:
    sql(engine, "UPDATE player_game_stats SET pts = pts + 1 WHERE starter AND team_id = :t", t=OKC)
    run_id, results = check_date(engine, GAME_DATE, today=TODAY)
    assert {r.check_name for r in results if r.blocking} == {"team_points_match_players"}
    with engine.connect() as conn:
        run = conn.execute(
            text(
                "SELECT kind::text, status::text, finished_at IS NOT NULL "
                "FROM ingest_runs WHERE run_id = :r"
            ),
            {"r": run_id},
        ).one()
        stored = conn.execute(
            text(
                "SELECT check_name, status::text FROM quality_results "
                "WHERE run_id = :r ORDER BY check_name"
            ),
            {"r": run_id},
        ).all()
    assert tuple(run) == ("check", "failed", True)
    assert dict(stored)["team_points_match_players"] == "fail"
    assert len(stored) == 6
