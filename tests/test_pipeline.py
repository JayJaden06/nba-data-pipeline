"""End-to-end ingest of one date against Postgres with a fake API client."""

import copy
import os
from collections.abc import Iterator
from datetime import date
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text

from nba_pipeline import cli
from nba_pipeline.pipeline import ingest_date
from tests.conftest import FakeNbaApiClient

pytestmark = pytest.mark.integration

DATABASE_URL = os.environ.get("DATABASE_URL")
MARCH_15 = date(2026, 3, 15)


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    if not DATABASE_URL:
        pytest.skip("DATABASE_URL not set")
    cfg = Config("alembic.ini")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    eng = create_engine(DATABASE_URL, future=True)
    yield eng
    eng.dispose()


@pytest.fixture(autouse=True)
def empty_tables(engine: Engine) -> None:
    with engine.begin() as conn:
        for table in ("player_game_stats", "team_game_stats", "players", "games"):
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
    summary = ingest_date(engine, client, MARCH_15)  # type: ignore[arg-type]
    assert summary.ok
    assert summary.games.as_tuple() == (1, 0, 0)
    assert summary.box_scores_loaded == 1
    assert summary.team_stats.as_tuple() == (2, 0, 0)
    assert summary.players.inserted == summary.player_stats.inserted > 20
    assert [name for name, _ in client.calls] == ["ScoreboardV3", "BoxScoreTraditionalV3"]

    again = ingest_date(engine, client, MARCH_15)  # type: ignore[arg-type]
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
    summary = ingest_date(engine, client, MARCH_15)  # type: ignore[arg-type]
    assert not summary.ok
    assert summary.games.total == 7
    assert summary.box_scores_loaded == 1
    assert set(summary.failures) == {f"00225009{n}" for n in range(77, 83)}
    assert all(err.startswith("NbaApiError") for err in summary.failures.values())

    with engine.connect() as conn:
        n_games = conn.execute(text("SELECT count(*) FROM games")).scalar_one()
        n_team_rows = conn.execute(text("SELECT count(*) FROM team_game_stats")).scalar_one()
    assert (n_games, n_team_rows) == (7, 2)


def test_scheduled_games_are_not_fetched(
    engine: Engine, scoreboard_scheduled: dict[str, Any]
) -> None:
    client = FakeNbaApiClient({("ScoreboardV3", "2026-10-14"): scoreboard_scheduled})
    summary = ingest_date(engine, client, date(2026, 10, 14))  # type: ignore[arg-type]
    assert summary.ok and summary.box_scores_loaded == 0
    assert [name for name, _ in client.calls] == ["ScoreboardV3"]


def test_cli_exit_code_reflects_failures(
    monkeypatch: pytest.MonkeyPatch,
    engine: Engine,
    scoreboard_final: dict[str, Any],
    boxscore_final: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    payloads = {
        ("ScoreboardV3", "2026-03-15"): scoreboard_final,
        ("BoxScoreTraditionalV3", "0022500976"): boxscore_final,
    }
    monkeypatch.setattr(cli, "NbaApiClient", lambda **kw: FakeNbaApiClient(payloads))
    assert cli.main(["ingest", "--date", "2026-03-15"]) == 1
    out = capsys.readouterr().out
    assert "box scores loaded=1 failed=6" in out
    assert "FAILED 0022500977" in out

    payloads[("ScoreboardV3", "2026-03-15")] = one_game_scoreboard(scoreboard_final)
    assert cli.main(["ingest", "--date", "2026-03-15"]) == 0
