"""API tests: the real FastAPI app over Postgres, seeded through the real pipeline."""

import copy
from collections.abc import Iterator
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from nba_pipeline.api.app import create_app
from nba_pipeline.api.models import minutes_str, pct
from nba_pipeline.pipeline import check_date, ingest_date
from tests.conftest import TEST_DATABASE_URL, FakeNbaApiClient, migrated_engine

pytestmark = pytest.mark.integration

GAME_ID = "0022500976"  # 2026-03-15, MIN 103 @ OKC 116
OKC, MIN = 1610612760, 1610612750
SGA, DORT = 1628983, 1629652


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    yield from migrated_engine()


@pytest.fixture(scope="module")
def seeded(
    engine: Engine,
    request: pytest.FixtureRequest,
) -> dict[str, Any]:
    """March 15 (one final game with box score) and October 14 (scheduled preseason)."""
    sb_final = request.getfixturevalue("scoreboard_final")
    sb_sched = request.getfixturevalue("scoreboard_scheduled")
    box = request.getfixturevalue("boxscore_final")
    with engine.begin() as conn:
        for t in (
            "quality_results",
            "player_game_stats",
            "team_game_stats",
            "players",
            "games",
            "ingest_runs",
        ):
            conn.execute(text(f"DELETE FROM {t}"))
    one = copy.deepcopy(sb_final)
    one["scoreboard"]["games"] = one["scoreboard"]["games"][:1]
    client = FakeNbaApiClient(
        {
            ("ScoreboardV3", "2026-03-15"): one,
            ("ScoreboardV3", "2026-10-14"): sb_sched,
            ("BoxScoreTraditionalV3", GAME_ID): box,
        }
    )
    march = ingest_date(engine, client, date(2026, 3, 15), today=date(2026, 3, 16))  # type: ignore[arg-type]
    october = ingest_date(engine, client, date(2026, 10, 14), today=date(2026, 10, 15))  # type: ignore[arg-type]
    return {"march": march, "october": october, "box": box}


@pytest.fixture(scope="module")
def api(seeded: dict[str, Any]) -> Iterator[TestClient]:
    with TestClient(create_app(TEST_DATABASE_URL)) as client:
        yield client


# Module-scoped fixtures can't use function-scoped ones directly; re-expose them.
@pytest.fixture(scope="module")
def scoreboard_final() -> dict[str, Any]:
    from tests.conftest import load_fixture

    return load_fixture("scoreboard_v3_2026-03-15.json")


@pytest.fixture(scope="module")
def scoreboard_scheduled() -> dict[str, Any]:
    from tests.conftest import load_fixture

    return load_fixture("scoreboard_v3_2026-10-14.json")


@pytest.fixture(scope="module")
def boxscore_final() -> dict[str, Any]:
    from tests.conftest import load_fixture

    return load_fixture("boxscore_traditional_v3_0022500976.json")


def test_derived_field_helpers() -> None:
    assert minutes_str(1059) == "17:39"
    assert minutes_str(14400) == "240:00"
    assert pct(42, 101) == 0.416
    assert pct(0, 0) is None


def test_openapi_lists_every_endpoint(api: TestClient) -> None:
    paths = set(api.get("/openapi.json").json()["paths"])
    assert paths == {
        "/health",
        "/runs/latest",
        "/runs/{game_date}",
        "/quality/{game_date}",
        "/games",
        "/games/{game_id}",
        "/players/{player_id}/games",
        "/teams/{team_id}/games",
    }


def test_health(api: TestClient, seeded: dict[str, Any]) -> None:
    body = api.get("/health").json()
    assert body["database"] == "ok"
    assert body["status"] == "ok"
    assert body["latest_run"]["run_id"] == seeded["october"].run_id


def test_runs_latest_and_by_date(api: TestClient, seeded: dict[str, Any]) -> None:
    latest = api.get("/runs/latest").json()
    assert latest["run_id"] == seeded["october"].run_id
    assert latest["game_date"] == "2026-10-14"

    march = api.get("/runs/2026-03-15").json()
    assert march["run_id"] == seeded["march"].run_id
    assert (march["kind"], march["status"]) == ("ingest", "succeeded")
    assert (march["games_total"], march["box_scores_loaded"]) == (1, 1)
    assert march["rows"]["inserted"] > 0
    assert march["quality"][0]["check_name"] == "box_scores_complete"
    assert len(march["quality"]) == 6

    assert api.get("/runs/2026-01-01").status_code == 404
    assert api.get("/runs/not-a-date").status_code == 422


def test_quality_report(api: TestClient, engine: Engine, seeded: dict[str, Any]) -> None:
    march = api.get("/quality/2026-03-15").json()
    assert march["overall"] == "pass"
    assert march["run_id"] == seeded["march"].run_id

    october = api.get("/quality/2026-10-14").json()
    assert october["overall"] == "warn"  # games not played yet
    assert {r["check_name"]: r["status"] for r in october["results"]}[
        "box_scores_complete"
    ] == "warn"

    # A later check-only run for the date becomes the reported one.
    run_id, _ = check_date(engine, date(2026, 3, 15), today=date(2026, 3, 16))
    assert api.get("/quality/2026-03-15").json()["run_id"] == run_id

    assert api.get("/quality/2026-01-01").status_code == 404


def test_games_by_date(api: TestClient) -> None:
    games = api.get("/games", params={"date": "2026-03-15"}).json()
    assert len(games) == 1
    g = games[0]
    assert g["game_id"] == GAME_ID
    assert (g["home"]["abbreviation"], g["away"]["abbreviation"]) == ("OKC", "MIN")
    assert (g["home_score"], g["away_score"], g["status"]) == (116, 103, "final")

    scheduled = api.get("/games", params={"date": "2026-10-14"}).json()
    assert len(scheduled) == 7
    assert all(x["home_score"] is None and x["status"] == "scheduled" for x in scheduled)

    assert api.get("/games", params={"date": "2026-01-01"}).json() == []
    assert api.get("/games").status_code == 422  # date is required


def test_game_detail(api: TestClient, seeded: dict[str, Any]) -> None:
    g = api.get(f"/games/{GAME_ID}").json()
    home, away = g["box_score"]
    assert (home["team"]["team_id"], home["is_home"], away["is_home"]) == (OKC, True, False)
    assert (home["pts"], home["minutes"], home["fg_pct"]) == (116, "240:00", 0.416)
    assert home["plus_minus"] == 13

    raw_home = seeded["box"]["boxScoreTraditional"]["homeTeam"]["players"]
    assert len(home["players"]) == len(raw_home)
    assert [p["starter"] for p in home["players"]][:5] == [True] * 5
    assert not any(p["starter"] for p in home["players"][5:])
    assert sum(p["pts"] for p in home["players"]) == home["pts"]

    dort = next(p for p in home["players"] if p["player_id"] == DORT)
    assert (dort["name"], dort["minutes"], dort["fg_pct"], dort["ft_pct"]) == (
        "Luguentz Dort",
        "17:39",
        0.0,
        0.75,
    )
    dnp = next(p for p in home["players"] if not p["played"])
    assert dnp["minutes"] == "0:00" and dnp["fg_pct"] is None and dnp["dnp_reason"]

    unplayed = api.get("/games/0012600003").json()
    assert unplayed["box_score"] is None
    assert api.get("/games/0029999999").status_code == 404


def test_player_games(api: TestClient) -> None:
    body = api.get(f"/players/{SGA}/games", params={"season": "2025-26"}).json()
    assert body["player"]["name"] == "Shai Gilgeous-Alexander"
    (line,) = body["games"]
    assert line["game_id"] == GAME_ID
    assert (line["team"]["abbreviation"], line["opponent"]["abbreviation"]) == ("OKC", "MIN")
    assert (line["is_home"], line["result"], line["starter"]) == (True, "W", True)
    assert body["totals"]["pts"] == line["pts"]

    empty = api.get(f"/players/{SGA}/games", params={"season": "2024-25"}).json()
    assert empty["games"] == [] and empty["totals"]["pts"] == 0

    assert api.get(f"/players/{SGA}/games").status_code == 422  # season required
    assert api.get(f"/players/{SGA}/games", params={"season": "2025"}).status_code == 422
    assert api.get("/players/1/games", params={"season": "2025-26"}).status_code == 404


def test_team_games(api: TestClient) -> None:
    okc = api.get(f"/teams/{OKC}/games", params={"season": "2025-26"}).json()
    assert okc["record"] == "1-0"
    (line,) = okc["games"]
    assert (line["opponent"]["abbreviation"], line["is_home"], line["result"]) == ("MIN", True, "W")
    assert (line["team_score"], line["opponent_score"]) == (116, 103)
    assert line["stats"]["pts"] == 116

    mn = api.get(f"/teams/{MIN}/games", params={"season": "2025-26"}).json()
    assert mn["record"] == "0-1"
    assert mn["games"][0]["result"] == "L" and mn["games"][0]["is_home"] is False

    # Preseason 2026-27: scheduled games appear with no result and no stats.
    pre = api.get(f"/teams/{OKC}/games", params={"season": "2026-27"}).json()
    assert pre["record"] == "0-0"
    assert all(g["result"] is None and g["stats"] is None for g in pre["games"])

    assert api.get("/teams/999/games", params={"season": "2025-26"}).status_code == 404
