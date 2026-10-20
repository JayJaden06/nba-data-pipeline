import copy
import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url

from nba_pipeline.config import get_settings

FIXTURES = Path(__file__).parent / "fixtures"

# Integration tests drop and recreate the whole schema, so they must never touch the dev
# database. They run only against TEST_DATABASE_URL, and only if its database name ends
# in "_test". DATABASE_URL is overridden for the session so code that reads settings
# (the CLI, Alembic) also lands on the test database.
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
if TEST_DATABASE_URL:
    _name = make_url(TEST_DATABASE_URL).database or ""
    if not _name.endswith("_test"):
        raise pytest.UsageError(
            f"TEST_DATABASE_URL points at database {_name!r}; it must end in '_test'"
        )
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
else:
    os.environ["DATABASE_URL"] = "postgresql+psycopg://unset@localhost:1/no_test_db_configured"
get_settings.cache_clear()


def migrated_engine() -> Iterator[Engine]:
    """Fresh schema from the migrations on the test database; skips without one."""
    from alembic import command
    from alembic.config import Config

    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL not set")
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    eng = create_engine(TEST_DATABASE_URL, future=True)
    yield eng
    eng.dispose()


def load_fixture(name: str) -> dict[str, Any]:
    with (FIXTURES / name).open(encoding="utf-8") as fh:
        data: dict[str, Any] = json.load(fh)
        return data


@pytest.fixture
def scoreboard_final() -> dict[str, Any]:
    """2026-03-15: seven regular-season games, all final."""
    return load_fixture("scoreboard_v3_2026-03-15.json")


@pytest.fixture
def scoreboard_scheduled() -> dict[str, Any]:
    """2026-10-14: seven preseason games, none started."""
    return load_fixture("scoreboard_v3_2026-10-14.json")


@pytest.fixture
def scoreboard_intl() -> dict[str, Any]:
    """2026-10-12: five preseason games, one against a non-NBA club (London Lions)."""
    return load_fixture("scoreboard_v3_2026-10-12.json")


@pytest.fixture
def boxscore_final() -> dict[str, Any]:
    """Game 0022500976 (2026-03-15, MIN @ OKC), regulation, two DNPs."""
    return load_fixture("boxscore_traditional_v3_0022500976.json")


@pytest.fixture
def boxscore_ot() -> dict[str, Any]:
    """Game 0012600047 (2026-10-13 preseason, IND @ OKC), one overtime."""
    return load_fixture("boxscore_traditional_v3_0012600047.json")


class FakeNbaApiClient:
    """Serves recorded payloads keyed by (endpoint name, params); raises NbaApiError otherwise."""

    def __init__(self, payloads: dict[tuple[str, str], dict[str, Any]]) -> None:
        self.payloads = payloads
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def call(self, endpoint: Any, **params: Any) -> dict[str, Any]:
        from nba_pipeline.ingest.client import NbaApiError

        name = endpoint.__name__
        self.calls.append((name, params))
        key = (name, next(iter(params.values())))
        if key not in self.payloads:
            raise NbaApiError(f"{name} failed after 6 attempts: not recorded {params}")
        return copy.deepcopy(self.payloads[key])
