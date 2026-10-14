import copy
import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


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
