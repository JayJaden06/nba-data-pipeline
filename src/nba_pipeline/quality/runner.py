"""Run every registered check and persist the results."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from sqlalchemy import Connection

from nba_pipeline.load.quality import write_results
from nba_pipeline.quality import CheckContext, CheckResult, CheckStatus, QualityCheck
from nba_pipeline.quality.checks import ALL_CHECKS

log = logging.getLogger(__name__)


def run_checks(
    conn: Connection, ctx: CheckContext, checks: Sequence[QualityCheck] = ALL_CHECKS
) -> list[CheckResult]:
    results: list[CheckResult] = []
    for check in checks:
        try:
            result = check.run(conn, ctx)
        except Exception as exc:
            log.exception("check %s raised", check.name)
            result = CheckResult(
                check_name=check.name,
                status=CheckStatus.ERROR,
                details={"message": f"{type(exc).__name__}: {str(exc).splitlines()[0]}"},
            )
        log.log(
            logging.WARNING if result.blocking else logging.INFO,
            "check %s %s: %s",
            result.check_name,
            result.status.value.upper(),
            result.details.get("message"),
        )
        results.append(result)
    return results


def run_and_record(conn: Connection, ctx: CheckContext) -> list[CheckResult]:
    """Run all checks for `ctx` and write them under ctx.run_id."""
    if ctx.run_id is None:
        raise ValueError("run_id is required to record results")
    results = run_checks(conn, ctx)
    write_results(conn, ctx.run_id, ctx.game_date, results)
    return results
