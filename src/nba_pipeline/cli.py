"""Command-line entry point.

Usage: nba-pipeline ingest --date 2026-03-15  (default date: yesterday, US/Eastern)
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from nba_pipeline.config import get_settings
from nba_pipeline.db import get_engine
from nba_pipeline.ingest.client import NbaApiClient
from nba_pipeline.pipeline import ingest_date

ET = ZoneInfo("America/New_York")


def yesterday_et(now: datetime | None = None) -> date:
    """NBA game dates are US/Eastern; last night means yesterday in ET."""
    now = now or datetime.now(tz=UTC)
    return (now.astimezone(ET) - timedelta(days=1)).date()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nba-pipeline")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="ingest one game date")
    ingest.add_argument("--date", type=date.fromisoformat, default=None, help="YYYY-MM-DD")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = get_settings()

    if args.command == "ingest":
        engine = get_engine(settings.database_url)
        client = NbaApiClient(
            min_interval_s=settings.nba_api_min_interval_s,
            max_retries=settings.nba_api_max_retries,
            timeout_s=settings.nba_api_timeout_s,
        )
        summary = ingest_date(engine, client, args.date or yesterday_et())
        r = summary.games
        print(
            f"{summary.game_date}: {r.total} games "
            f"(inserted={r.inserted} updated={r.updated} unchanged={r.unchanged}); "
            f"teams added={len(summary.teams_added)}"
        )
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
