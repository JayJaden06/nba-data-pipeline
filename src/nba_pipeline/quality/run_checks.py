"""Checks about the run itself and the database as a whole."""

from __future__ import annotations

from datetime import date

from sqlalchemy import Connection, text

from nba_pipeline.quality import CheckContext, CheckResult, CheckStatus

FRESHNESS_MAX_GAP_DAYS = 2


class SchemaDrift:
    """Any game in this run that failed with SchemaDriftError.

    The drift itself already failed loudly in the logs; this makes it queryable.
    """

    name = "schema_drift"

    def run(self, conn: Connection, ctx: CheckContext) -> CheckResult:
        drifted = [
            e for e in ctx.ingest_errors if str(e.get("error", "")).startswith("SchemaDriftError")
        ]
        if drifted:
            return CheckResult(
                check_name=self.name,
                status=CheckStatus.FAIL,
                details={
                    "message": f"{len(drifted)} payload(s) did not match the expected schema",
                    "errors": drifted,
                },
            )
        return CheckResult(
            check_name=self.name,
            status=CheckStatus.PASS,
            details={"message": "all payloads matched the expected schema"},
        )


class Freshness:
    """Newest final game in the DB is at most FRESHNESS_MAX_GAP_DAYS behind today.

    When the gap is larger, it is only a FAIL if some run after that date actually found
    games (we are failing to load finals). If every later run found zero games it is the
    offseason or a break, and that is a WARN.
    """

    name = "freshness"

    def run(self, conn: Connection, ctx: CheckContext) -> CheckResult:
        newest: date | None = conn.execute(
            text("SELECT max(game_date) FROM games WHERE status = 'final'")
        ).scalar_one()
        if newest is None:
            return CheckResult(
                check_name=self.name,
                status=CheckStatus.WARN,
                details={"message": "no final games in the database yet"},
            )
        gap = (ctx.today - newest).days
        details = {
            "newest_final_game_date": newest.isoformat(),
            "today": ctx.today.isoformat(),
            "gap_days": gap,
        }
        if gap <= FRESHNESS_MAX_GAP_DAYS:
            return CheckResult(
                check_name=self.name,
                status=CheckStatus.PASS,
                details=details | {"message": f"newest final game is {gap} day(s) old"},
            )
        later_runs_with_games = conn.execute(
            text(
                "SELECT count(*) FROM ingest_runs "
                "WHERE game_date > :newest AND games_total > 0 AND kind = 'ingest'"
            ),
            {"newest": newest},
        ).scalar_one()
        if later_runs_with_games:
            msg = (
                f"newest final game is {gap} days old "
                f"but {later_runs_with_games} later run(s) found games"
            )
            return CheckResult(
                check_name=self.name, status=CheckStatus.FAIL, details=details | {"message": msg}
            )
        msg = f"newest final game is {gap} days old; no games on later dates (offseason or break?)"
        return CheckResult(
            check_name=self.name, status=CheckStatus.WARN, details=details | {"message": msg}
        )
