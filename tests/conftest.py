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
