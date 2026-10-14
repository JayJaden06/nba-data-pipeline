"""Integration tests for the games upsert. Need a live Postgres: set DATABASE_URL.

Run locally with:  docker compose up -d && uv run pytest -m integration
"""

import copy
import os
from collections.abc import Iterator
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, select, text

from nba_pipeline.load.games import upsert_games
from nba_pipeline.load.tables import games
from nba_pipeline.schemas.raw_scoreboard import RawScoreboardResponse
from nba_pipeline.transform.games import to_clean_games

pytestmark = pytest.mark.integration

DATABASE_URL = os.environ.get("DATABASE_URL")


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
def clean_games(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM games"))


def test_migration_seeds_30_teams(engine: Engine) -> None:
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM teams")).scalar_one() == 30


def test_upsert_is_idempotent(engine: Engine, scoreboard_final: dict[str, Any]) -> None:
    rows = to_clean_games(RawScoreboardResponse.parse(scoreboard_final))

    with engine.begin() as conn:
        first = upsert_games(conn, rows)
    assert (first.inserted, first.updated, first.unchanged) == (7, 0, 0)

    with engine.begin() as conn:
        second = upsert_games(conn, rows)
    assert (second.inserted, second.updated, second.unchanged) == (0, 0, 7)

    with engine.connect() as conn:
        stored = conn.execute(select(games).order_by(games.c.game_sequence)).mappings().all()
    assert [r["game_id"] for r in stored] == [g.game_id for g in rows]
    assert all(r["first_seen_at"] == r["last_updated_at"] for r in stored)


def test_changed_payload_updates_row(engine: Engine, scoreboard_final: dict[str, Any]) -> None:
    rows = to_clean_games(RawScoreboardResponse.parse(scoreboard_final))
    with engine.begin() as conn:
        upsert_games(conn, rows)

    corrected = copy.deepcopy(scoreboard_final)
    corrected["scoreboard"]["games"][0]["homeTeam"]["score"] = 117
    rows2 = to_clean_games(RawScoreboardResponse.parse(corrected))
    with engine.begin() as conn:
        result = upsert_games(conn, rows2)
    assert (result.inserted, result.updated, result.unchanged) == (0, 1, 6)

    with engine.connect() as conn:
        row = conn.execute(select(games).where(games.c.game_id == "0022500976")).mappings().one()
    assert row["home_score"] == 117
    assert row["last_updated_at"] > row["first_seen_at"]


def test_scheduled_then_final_same_game_id(
    engine: Engine, scoreboard_scheduled: dict[str, Any]
) -> None:
    """Partial-day handling: a game first seen as scheduled is overwritten once final."""
    scheduled = to_clean_games(RawScoreboardResponse.parse(scoreboard_scheduled))
    with engine.begin() as conn:
        upsert_games(conn, scheduled)

    final_payload = copy.deepcopy(scoreboard_scheduled)
    g = final_payload["scoreboard"]["games"][0]
    g["gameStatus"], g["gameStatusText"], g["period"] = 3, "Final", 4
    g["homeTeam"]["score"], g["awayTeam"]["score"] = 110, 104
    final = to_clean_games(RawScoreboardResponse.parse(final_payload))
    with engine.begin() as conn:
        result = upsert_games(conn, final)
    assert (result.inserted, result.updated, result.unchanged) == (0, 1, 6)

    with engine.connect() as conn:
        row = conn.execute(
            select(games.c.status, games.c.home_score, games.c.periods).where(
                games.c.game_id == scheduled[0].game_id
            )
        ).one()
    assert tuple(row) == ("final", 110, 4)


def test_non_nba_opponent_is_registered_then_loaded(
    engine: Engine, scoreboard_intl: dict[str, Any]
) -> None:
    """A preseason game against a non-NBA club must load, with the club flagged is_nba=false."""
    from nba_pipeline.load.tables import teams
    from nba_pipeline.load.teams import ensure_teams
    from nba_pipeline.transform.teams import teams_from_scoreboard

    raw = RawScoreboardResponse.parse(scoreboard_intl)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM teams WHERE NOT is_nba"))
        added = ensure_teams(conn, teams_from_scoreboard(raw))
        result = upsert_games(conn, to_clean_games(raw))
    assert added == [50015]
    assert result.inserted == 5

    with engine.connect() as conn:
        row = conn.execute(select(teams).where(teams.c.team_id == 50015)).mappings().one()
        n_nba = conn.execute(text("SELECT count(*) FROM teams WHERE is_nba")).scalar_one()
    assert (row["abbreviation"], row["full_name"], row["is_nba"]) == ("LON", "London Lions", False)
    assert n_nba == 30

    # Re-running registers nothing new and changes nothing.
    with engine.begin() as conn:
        assert ensure_teams(conn, teams_from_scoreboard(raw)) == []
        assert upsert_games(conn, to_clean_games(raw)).unchanged == 5
