"""Integration tests for players / team_game_stats / player_game_stats upserts."""

import copy
import os
from collections.abc import Iterator
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.exc import IntegrityError

from nba_pipeline.load.box_stats import upsert_player_game_stats, upsert_team_game_stats
from nba_pipeline.load.games import upsert_games
from nba_pipeline.load.players import upsert_players
from nba_pipeline.load.tables import player_game_stats, players
from nba_pipeline.schemas.raw_boxscore import RawBoxScoreResponse
from nba_pipeline.schemas.raw_scoreboard import RawScoreboardResponse
from nba_pipeline.transform.boxscore import BoxScoreRows, to_box_score_rows
from nba_pipeline.transform.games import to_clean_games

pytestmark = pytest.mark.integration

DATABASE_URL = os.environ.get("DATABASE_URL")
GAME_ID = "0022500976"
DORT = 1629652


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
def seeded_games(engine: Engine, scoreboard_final: dict[str, Any]) -> None:
    with engine.begin() as conn:
        for table in ("player_game_stats", "team_game_stats", "players", "games"):
            conn.execute(text(f"DELETE FROM {table}"))
        upsert_games(conn, to_clean_games(RawScoreboardResponse.parse(scoreboard_final)))


def load(engine: Engine, rows: BoxScoreRows) -> tuple[tuple[int, int, int], ...]:
    with engine.begin() as conn:
        p = upsert_players(conn, rows.players)
        t = upsert_team_game_stats(conn, rows.team_stats)
        s = upsert_player_game_stats(conn, rows.player_stats)
    return p.as_tuple(), t.as_tuple(), s.as_tuple()


def test_load_then_rerun_is_noop(engine: Engine, boxscore_final: dict[str, Any]) -> None:
    rows = to_box_score_rows(RawBoxScoreResponse.parse(boxscore_final))
    n = len(rows.player_stats)
    assert load(engine, rows) == ((n, 0, 0), (2, 0, 0), (n, 0, 0))
    assert load(engine, rows) == ((0, 0, n), (0, 0, 2), (0, 0, n))

    with engine.connect() as conn:
        totals = conn.execute(
            text(
                "SELECT t.pts, sum(p.pts) FROM team_game_stats t "
                "JOIN player_game_stats p USING (game_id, team_id) "
                "WHERE t.game_id = :g GROUP BY t.team_id, t.pts"
            ),
            {"g": GAME_ID},
        ).all()
    assert len(totals) == 2
    assert all(team_pts == player_sum for team_pts, player_sum in totals)


def test_stat_correction_updates_one_row(engine: Engine, boxscore_final: dict[str, Any]) -> None:
    load(engine, to_box_score_rows(RawBoxScoreResponse.parse(boxscore_final)))

    corrected = copy.deepcopy(boxscore_final)
    stats = corrected["boxScoreTraditional"]["homeTeam"]["players"][0]["statistics"]
    stats["assists"] += 1
    rows = to_box_score_rows(RawBoxScoreResponse.parse(corrected))
    n = len(rows.player_stats)
    assert load(engine, rows) == ((0, 0, n), (0, 0, 2), (0, 1, n - 1))

    cols = (
        player_game_stats.c.ast,
        player_game_stats.c.first_seen_at,
        player_game_stats.c.last_updated_at,
    )
    with engine.connect() as conn:
        row = conn.execute(select(*cols).where(player_game_stats.c.player_id == DORT)).one()
    assert row.ast == stats["assists"]
    assert row.last_updated_at > row.first_seen_at


def test_player_rename_updates_identity(engine: Engine, boxscore_final: dict[str, Any]) -> None:
    load(engine, to_box_score_rows(RawBoxScoreResponse.parse(boxscore_final)))

    renamed = copy.deepcopy(boxscore_final)
    renamed["boxScoreTraditional"]["homeTeam"]["players"][0]["familyName"] = "Dort Jr."
    rows = to_box_score_rows(RawBoxScoreResponse.parse(renamed))
    p, _, s = load(engine, rows)
    assert p == (0, 1, len(rows.players) - 1)
    assert s[1] == 1  # the stats row hashes identity too, so it updates as well

    with engine.connect() as conn:
        name = conn.execute(select(players.c.last_name).where(players.c.player_id == DORT))
    assert name.scalar_one() == "Dort Jr."


def test_unknown_game_is_rejected(engine: Engine, boxscore_final: dict[str, Any]) -> None:
    """The games -> stats foreign key holds: no orphan box scores."""
    payload = copy.deepcopy(boxscore_final)
    payload["boxScoreTraditional"]["gameId"] = "0022599999"
    rows = to_box_score_rows(RawBoxScoreResponse.parse(payload))
    with pytest.raises(IntegrityError), engine.begin() as conn:
        upsert_players(conn, rows.players)
        upsert_team_game_stats(conn, rows.team_stats)
