"""End-to-end ingest of one date against Postgres with a fake API client."""

import copy
import re
from collections.abc import Iterator
from datetime import date
from typing import Any

import pytest
from sqlalchemy import Engine, text

from nba_pipeline import cli, pipeline
from nba_pipeline.pipeline import ingest_date
from tests.conftest import FakeNbaApiClient, migrated_engine

pytestmark = pytest.mark.integration

MARCH_15 = date(2026, 3, 15)
MARCH_16 = date(2026, 3, 16)  # 'today' for the freshness check


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    yield from migrated_engine()


@pytest.fixture(autouse=True)
def empty_tables(engine: Engine) -> None:
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


def one_game_scoreboard(scoreboard_final: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(scoreboard_final)
    payload["scoreboard"]["games"] = payload["scoreboard"]["games"][:1]
    return payload


def test_full_day_success(
    engine: Engine, scoreboard_final: dict[str, Any], boxscore_final: dict[str, Any]
) -> None:
    client = FakeNbaApiClient(
        {
            ("ScoreboardV3", "2026-03-15"): one_game_scoreboard(scoreboard_final),
            ("BoxScoreTraditionalV3", "0022500976"): boxscore_final,
        }
    )
    summary = ingest_date(engine, client, MARCH_15, today=MARCH_16)  # type: ignore[arg-type]
    assert summary.ok
    assert summary.games.as_tuple() == (1, 0, 0)
    assert summary.box_scores_loaded == 1
    assert [c.status.value for c in summary.checks] == ["pass"] * 6
    with engine.connect() as conn:
        run = conn.execute(
            text(
                "SELECT status::text, games_total, box_scores_loaded, rows_inserted, errors "
                "FROM ingest_runs"
            )
        ).one()
        stamped = conn.execute(
            text("SELECT count(*) FROM games WHERE ingest_run_id = :r"), {"r": summary.run_id}
        ).scalar_one()
        n_results = conn.execute(
            text("SELECT count(*) FROM quality_results WHERE run_id = :r"), {"r": summary.run_id}
        ).scalar_one()
    assert tuple(run) == ("succeeded", 1, 1, summary.rows()[0], [])
    assert (stamped, n_results) == (1, 6)
    assert summary.team_stats.as_tuple() == (2, 0, 0)
    assert summary.players.inserted == summary.player_stats.inserted > 20
    assert [name for name, _ in client.calls] == ["ScoreboardV3", "BoxScoreTraditionalV3"]

    again = ingest_date(engine, client, MARCH_15, today=MARCH_16)  # type: ignore[arg-type]
    assert again.ok
    assert again.games.as_tuple() == (0, 0, 1)
    assert again.player_stats.as_tuple() == (0, 0, summary.player_stats.inserted)


def test_one_bad_game_does_not_stop_the_others(
    engine: Engine, scoreboard_final: dict[str, Any], boxscore_final: dict[str, Any]
) -> None:
    client = FakeNbaApiClient(
        {
            ("ScoreboardV3", "2026-03-15"): scoreboard_final,
            ("BoxScoreTraditionalV3", "0022500976"): boxscore_final,
        }
    )
    summary = ingest_date(engine, client, MARCH_15, today=MARCH_16)  # type: ignore[arg-type]
    assert not summary.ok
    assert summary.games.total == 7
    assert summary.box_scores_loaded == 1
    assert set(summary.failures) == {f"00225009{n}" for n in range(77, 83)}
    assert all(err.startswith("NbaApiError") for err in summary.failures.values())
    complete = next(c for c in summary.checks if c.check_name == "box_scores_complete")
    assert complete.status.value == "fail"
    assert complete.details["missing_final"] == sorted(summary.failures)
    with engine.connect() as conn:
        run = conn.execute(
            text(
                "SELECT status::text, box_scores_failed, jsonb_array_length(errors) "
                "FROM ingest_runs"
            )
        ).one()
    assert tuple(run) == ("failed", 6, 6)

    with engine.connect() as conn:
        n_games = conn.execute(text("SELECT count(*) FROM games")).scalar_one()
        n_team_rows = conn.execute(text("SELECT count(*) FROM team_game_stats")).scalar_one()
    assert (n_games, n_team_rows) == (7, 2)


def test_scheduled_games_are_not_fetched(
    engine: Engine, scoreboard_scheduled: dict[str, Any]
) -> None:
    client = FakeNbaApiClient({("ScoreboardV3", "2026-10-14"): scoreboard_scheduled})
    summary = ingest_date(engine, client, date(2026, 10, 14), today=date(2026, 10, 15))  # type: ignore[arg-type]
    assert summary.box_scores_loaded == 0 and not summary.failures
    assert [name for name, _ in client.calls] == ["ScoreboardV3"]
    by_name = {c.check_name: c for c in summary.checks}
    assert by_name["box_scores_complete"].status.value == "warn"  # games not played yet
    assert by_name["freshness"].status.value == "warn"  # no final games in the DB
    assert summary.ok  # warn never fails the run


def test_cli_exit_code_reflects_failures(
    monkeypatch: pytest.MonkeyPatch,
    engine: Engine,
    scoreboard_final: dict[str, Any],
    boxscore_final: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    payloads = {
        ("ScoreboardV3", "2026-03-15"): one_game_scoreboard(scoreboard_final),
        ("BoxScoreTraditionalV3", "0022500976"): boxscore_final,
    }
    monkeypatch.setattr(cli, "NbaApiClient", lambda **kw: FakeNbaApiClient(payloads))
    monkeypatch.setattr(pipeline, "today_et", lambda: MARCH_16)

    # Clean day: everything loads, six checks pass, exit 0.
    assert cli.main(["ingest", "--date", "2026-03-15"]) == 0
    out = capsys.readouterr().out
    assert re.search(r"run \d+: succeeded", out) and "quality: 6 pass" in out
    assert cli.main(["check", "--date", "2026-03-15"]) == 0
    assert re.search(r"check run \d+: succeeded", capsys.readouterr().out)

    # Six box scores unavailable: ingest failures and a failing check, exit 1.
    payloads[("ScoreboardV3", "2026-03-15")] = scoreboard_final
    assert cli.main(["ingest", "--date", "2026-03-15"]) == 1
    out = capsys.readouterr().out
    assert re.search(r"run \d+: failed", out)
    assert "box scores   loaded=1 failed=6" in out
    assert "FAILED 0022500977" in out
    assert "FAIL box_scores_complete" in out

    # The six final games without box scores are still in the DB, so a check-only run
    # fails too: a failing check never removes data, it just stays flagged.
    assert cli.main(["check", "--date", "2026-03-15"]) == 1
    assert re.search(r"check run \d+: failed", capsys.readouterr().out)
