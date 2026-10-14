"""Unit tests for the check result model and the runner's error isolation. No database."""

from datetime import date
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import Connection

from nba_pipeline.quality import CheckContext, CheckResult, CheckStatus
from nba_pipeline.quality.runner import run_checks


def test_result_requires_message() -> None:
    with pytest.raises(ValidationError, match="message"):
        CheckResult(check_name="x", status=CheckStatus.PASS, details={})


@pytest.mark.parametrize(
    ("status", "blocking"),
    [
        (CheckStatus.PASS, False),
        (CheckStatus.WARN, False),
        (CheckStatus.FAIL, True),
        (CheckStatus.ERROR, True),
    ],
)
def test_blocking(status: CheckStatus, blocking: bool) -> None:
    r = CheckResult(check_name="x", status=status, details={"message": "m"})
    assert r.blocking is blocking


class Passes:
    name = "passes"

    def run(self, conn: Connection, ctx: CheckContext) -> CheckResult:
        return CheckResult(check_name=self.name, status=CheckStatus.PASS, details={"message": "ok"})


class Explodes:
    name = "explodes"

    def run(self, conn: Connection, ctx: CheckContext) -> CheckResult:
        raise RuntimeError("boom\nsecond line")


def test_runner_isolates_a_broken_check() -> None:
    ctx = CheckContext(game_date=date(2026, 3, 15), today=date(2026, 3, 16))
    conn: Any = None  # the fake checks never touch it
    results = run_checks(conn, ctx, checks=[Explodes(), Passes()])
    assert [(r.check_name, r.status) for r in results] == [
        ("explodes", CheckStatus.ERROR),
        ("passes", CheckStatus.PASS),
    ]
    assert results[0].details["message"] == "RuntimeError: boom"
