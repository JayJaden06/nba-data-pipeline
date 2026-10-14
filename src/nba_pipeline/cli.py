"""Command-line entry point.

    nba-pipeline ingest --date 2026-03-15   ingest one date (default: yesterday, US/Eastern)
    nba-pipeline check  --date 2026-03-15   run the quality checks only

Exit status is 1 when any game failed to load or any quality check is fail/error, so a
scheduler can alert on it. A `warn` exits 0.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from nba_pipeline.config import get_settings
from nba_pipeline.db import get_engine
from nba_pipeline.ingest.client import NbaApiClient
from nba_pipeline.load.upsert import UpsertResult
from nba_pipeline.pipeline import IngestSummary, check_date, ingest_date
from nba_pipeline.schemas.quality import CheckResult, CheckStatus

ET = ZoneInfo("America/New_York")


def yesterday_et(now: datetime | None = None) -> date:
    """NBA game dates are US/Eastern; last night means yesterday in ET."""
    now = now or datetime.now(tz=UTC)
    return (now.astimezone(ET) - timedelta(days=1)).date()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nba-pipeline")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="ingest one game date and run quality checks")
    ingest.add_argument("--date", type=date.fromisoformat, default=None, help="YYYY-MM-DD")

    check = sub.add_parser("check", help="run quality checks for one game date")
    check.add_argument("--date", type=date.fromisoformat, default=None, help="YYYY-MM-DD")
    return parser


def format_checks(results: Sequence[CheckResult]) -> list[str]:
    counts = {s: sum(1 for r in results if r.status is s) for s in CheckStatus}
    lines = [
        "  quality: "
        + ", ".join(
            f"{counts[s]} {s.value}" for s in CheckStatus if counts[s] or s is CheckStatus.PASS
        )
    ]
    lines.extend(
        f"    {r.status.value.upper()} {r.check_name}: {r.details.get('message')}"
        for r in results
        if r.status is not CheckStatus.PASS
    )
    return lines


def format_summary(s: IngestSummary) -> str:
    def fmt(r: UpsertResult) -> str:
        return f"inserted={r.inserted} updated={r.updated} unchanged={r.unchanged}"

    lines = [
        f"{s.game_date} run {s.run_id}: {s.status.value}",
        f"  games        {fmt(s.games)} (total={s.games.total}, teams added={len(s.teams_added)})",
        f"  box scores   loaded={s.box_scores_loaded} failed={len(s.failures)}",
        f"  players      {fmt(s.players)}",
        f"  team stats   {fmt(s.team_stats)}",
        f"  player stats {fmt(s.player_stats)}",
    ]
    lines.extend(f"  FAILED {game_id}: {err}" for game_id, err in s.failures.items())
    lines.extend(format_checks(s.checks))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = get_settings()
    engine = get_engine(settings.database_url)
    game_date = args.date or yesterday_et()

    if args.command == "ingest":
        client = NbaApiClient(
            min_interval_s=settings.nba_api_min_interval_s,
            max_retries=settings.nba_api_max_retries,
            timeout_s=settings.nba_api_timeout_s,
        )
        summary = ingest_date(engine, client, game_date)
        print(format_summary(summary))
        return 0 if summary.ok else 1

    if args.command == "check":
        run_id, results = check_date(engine, game_date)
        blocking = any(r.blocking for r in results)
        print(f"{game_date} check run {run_id}: {'failed' if blocking else 'succeeded'}")
        print("\n".join(format_checks(results)))
        return 1 if blocking else 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
