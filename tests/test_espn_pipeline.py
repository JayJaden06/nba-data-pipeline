"""End to end with the ESPN source against Postgres, plus the one-source-per-database guard."""

import copy
from collections.abc import Iterator
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from nba_pipeline import cli
from nba_pipeline.api.app import create_app
from nba_pipeline.load.meta import SourceMismatchError
from nba_pipeline.pipeline import check_date, ingest_date
from nba_pipeline.sources import EspnSource, NbaSource
from tests.conftest import TEST_DATABASE_URL, FakeNbaApiClient, migrated_engine

pytestmark = pytest.mark.integration

MARCH_15, MARCH_16 = date(2026, 3, 15), date(2026, 3, 16)
EVENT = "401810831"
OKC = 1610612760


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    yield from migrated_engine()


@pytest.fixture(autouse=True)
def empty(engine: Engine) -> None:
    with engine.begin() as conn:
        for t in (
            "quality_results",
            "player_game_stats",
            "team_game_stats",
            "players",
            "games",
            "ingest_runs",
            "pipeline_meta",
        ):
            conn.execute(text(f"DELETE FROM {t}"))
        conn.execute(text("DELETE FROM teams WHERE NOT is_nba"))


def one_game(sb: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(sb)
    payload["events"] = [e for e in payload["events"] if e["id"] == EVENT]
    return payload


def espn_client(sb: dict[str, Any], summary: dict[str, Any]) -> FakeNbaApiClient:
    return FakeNbaApiClient({("scoreboard", "20260315"): one_game(sb), ("summary", EVENT): summary})


def test_espn_day_end_to_end(
    engine: Engine, espn_scoreboard_final: dict[str, Any], espn_summary_final: dict[str, Any]
) -> None:
    client = espn_client(espn_scoreboard_final, espn_summary_final)
    summary = ingest_date(engine, EspnSource(client), MARCH_15, today=MARCH_16)
    assert summary.ok, summary.failures or [c for c in summary.checks if c.blocking]
    assert summary.source == "espn"
    assert summary.games.as_tuple() == (1, 0, 0)
    assert summary.team_stats.as_tuple() == (2, 0, 0)
    assert summary.player_stats.inserted == 27
    assert [c.status.value for c in summary.checks] == ["pass"] * 6
    minutes = next(c for c in summary.checks if c.check_name == "team_minutes_sum")
    assert minutes.details["source_precision"] == "whole minutes (ESPN)"

    again = ingest_date(engine, EspnSource(client), MARCH_15, today=MARCH_16)
    assert again.ok and again.player_stats.as_tuple() == (0, 0, 27)

    with engine.connect() as conn:
        source = conn.execute(text("SELECT value FROM pipeline_meta WHERE key='source'"))
        runs = conn.execute(text("SELECT DISTINCT source FROM ingest_runs")).scalars().all()
    assert source.scalar_one() == "espn" and runs == ["espn"]

    # The API is source-agnostic: team ids are the NBA's, game ids are ESPN's.
    with TestClient(create_app(TEST_DATABASE_URL)) as api:
        detail = api.get(f"/games/{EVENT}").json()
        assert (detail["home"]["abbreviation"], detail["home_score"]) == ("OKC", 116)
        assert detail["box_score"][0]["minutes"] == "240:00"
        okc = api.get(f"/teams/{OKC}/games", params={"season": "2025-26"}).json()
        assert okc["record"] == "1-0"


def test_non_nba_opponent_is_loaded_and_flagged(
    engine: Engine, espn_scoreboard_intl: dict[str, Any], espn_summary_intl: dict[str, Any]
) -> None:
    sb = copy.deepcopy(espn_scoreboard_intl)
    sb["events"] = [e for e in sb["events"] if e["id"] == "401914130"]
    client = FakeNbaApiClient(
        {("scoreboard", "20261012"): sb, ("summary", "401914130"): espn_summary_intl}
    )
    summary = ingest_date(engine, EspnSource(client), date(2026, 10, 12), today=date(2026, 10, 13))
    assert summary.ok, summary.failures
    assert summary.teams_added == [134478]
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT abbreviation, full_name, is_nba FROM teams WHERE team_id = 134478")
        ).one()
    assert tuple(row) == ("LON", "London Lions", False)


def test_one_source_per_database(
    engine: Engine,
    espn_scoreboard_final: dict[str, Any],
    espn_summary_final: dict[str, Any],
    scoreboard_final: dict[str, Any],
) -> None:
    espn = espn_client(espn_scoreboard_final, espn_summary_final)
    assert ingest_date(engine, EspnSource(espn), MARCH_15, today=MARCH_16).ok

    nba = FakeNbaApiClient({("ScoreboardV3", "2026-03-15"): scoreboard_final})
    with pytest.raises(SourceMismatchError, match="holds 'espn' data; refusing to load 'nba'"):
        ingest_date(engine, NbaSource(nba), MARCH_15, today=MARCH_16)
    assert nba.calls == []  # refused before any API call

    with engine.connect() as conn:
        games = conn.execute(text("SELECT count(*) FROM games")).scalar_one()
        last = conn.execute(
            text(
                "SELECT source, status::text, errors->0->>'error' FROM ingest_runs "
                "ORDER BY run_id DESC LIMIT 1"
            )
        ).one()
    assert games == 1  # nothing from the NBA was loaded
    assert last[0] == "nba" and last[1] == "failed" and "SourceMismatchError" in last[2]

    # check-only runs pick up the database's source.
    run_id, results = check_date(engine, MARCH_15, today=MARCH_16)
    with engine.connect() as conn:
        assert (
            conn.execute(
                text("SELECT source FROM ingest_runs WHERE run_id = :r"), {"r": run_id}
            ).scalar_one()
            == "espn"
        )
    assert not any(r.blocking for r in results)


def test_cli_source_flag_and_refusal_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    engine: Engine,
    espn_scoreboard_final: dict[str, Any],
    espn_summary_final: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    from nba_pipeline import pipeline

    client = espn_client(espn_scoreboard_final, espn_summary_final)
    monkeypatch.setattr(cli, "NbaApiClient", lambda **kw: client)
    monkeypatch.setattr(pipeline, "today_et", lambda: MARCH_16)

    assert cli.main(["ingest", "--date", "2026-03-15", "--source", "espn"]) == 0
    assert "(espn): succeeded" in capsys.readouterr().out

    assert cli.main(["ingest", "--date", "2026-03-15", "--source", "nba"]) == 2
    assert "refused:" in capsys.readouterr().err
