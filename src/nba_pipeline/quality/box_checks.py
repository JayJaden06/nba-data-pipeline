"""Checks over games / team_game_stats / player_game_stats for one date."""

from __future__ import annotations

from sqlalchemy import Connection, text

from nba_pipeline.quality import CheckContext, CheckResult, CheckStatus

REGULATION_SECONDS = 14400  # 48 min x 5 players
OVERTIME_SECONDS = 1500  # 5 min x 5 players
MINUTES_TOLERANCE_S = 60  # the NBA rounds each player's minutes separately


class BoxScoresComplete:
    """Every final game on the date has a box score. Not-yet-final games are a warn."""

    name = "box_scores_complete"

    def run(self, conn: Connection, ctx: CheckContext) -> CheckResult:
        rows = conn.execute(
            text(
                "SELECT g.game_id, g.status::text FROM games g "
                "LEFT JOIN team_game_stats t ON t.game_id = g.game_id "
                "WHERE g.game_date = :d AND g.status <> 'postponed' "
                "GROUP BY g.game_id, g.status HAVING count(t.game_id) = 0 ORDER BY g.game_id"
            ),
            {"d": ctx.game_date},
        ).all()
        missing_final = [g for g, s in rows if s == "final"]
        pending = [g for g, s in rows if s != "final"]
        details = {"missing_final": missing_final, "pending": pending}
        if missing_final:
            msg = f"{len(missing_final)} final game(s) have no box score"
            return CheckResult(
                check_name=self.name, status=CheckStatus.FAIL, details=details | {"message": msg}
            )
        if pending:
            msg = f"{len(pending)} game(s) not final yet, box score pending"
            return CheckResult(
                check_name=self.name, status=CheckStatus.WARN, details=details | {"message": msg}
            )
        return CheckResult(
            check_name=self.name,
            status=CheckStatus.PASS,
            details=details | {"message": "all final games have box scores"},
        )


class NoDuplicatePlayerRows:
    """One player_game_stats row per (game_id, player_id).

    The primary key already guarantees this; the check verifies the guarantee so it stays
    true if the schema or a load path ever changes, and documents it in quality_results.
    """

    name = "no_duplicate_player_rows"

    def run(self, conn: Connection, ctx: CheckContext) -> CheckResult:
        dupes = conn.execute(
            text(
                "SELECT p.game_id, p.player_id, count(*) FROM player_game_stats p "
                "JOIN games g USING (game_id) WHERE g.game_date = :d "
                "GROUP BY p.game_id, p.player_id HAVING count(*) > 1"
            ),
            {"d": ctx.game_date},
        ).all()
        if dupes:
            return CheckResult(
                check_name=self.name,
                status=CheckStatus.FAIL,
                details={
                    "message": f"{len(dupes)} duplicate (game_id, player_id) rows",
                    "duplicates": [list(r) for r in dupes],
                },
            )
        return CheckResult(
            check_name=self.name, status=CheckStatus.PASS, details={"message": "no duplicates"}
        )


class TeamPointsMatchPlayers:
    """team_game_stats.pts == sum(player_game_stats.pts) for every team-game."""

    name = "team_points_match_players"

    def run(self, conn: Connection, ctx: CheckContext) -> CheckResult:
        rows = conn.execute(
            text(
                "SELECT t.game_id, t.team_id, t.pts, coalesce(sum(p.pts), 0) AS player_pts "
                "FROM team_game_stats t JOIN games g USING (game_id) "
                "LEFT JOIN player_game_stats p ON p.game_id = t.game_id AND p.team_id = t.team_id "
                "WHERE g.game_date = :d GROUP BY t.game_id, t.team_id, t.pts "
                "HAVING t.pts <> coalesce(sum(p.pts), 0) ORDER BY t.game_id, t.team_id"
            ),
            {"d": ctx.game_date},
        ).all()
        if rows:
            mismatches = [
                {"game_id": g, "team_id": t, "team_pts": tp, "player_pts": int(pp)}
                for g, t, tp, pp in rows
            ]
            return CheckResult(
                check_name=self.name,
                status=CheckStatus.FAIL,
                details={
                    "message": f"{len(rows)} team-game(s): team points != sum of player points",
                    "mismatches": mismatches,
                },
            )
        return CheckResult(
            check_name=self.name,
            status=CheckStatus.PASS,
            details={"message": "team points match player sums"},
        )


class TeamMinutesSum:
    """Final games: team seconds == 14400 + 1500 per OT; player seconds sum to it (±60s)."""

    name = "team_minutes_sum"

    def run(self, conn: Connection, ctx: CheckContext) -> CheckResult:
        rows = conn.execute(
            text(
                "SELECT t.game_id, t.team_id, g.periods, t.seconds_played, "
                "coalesce(sum(p.seconds_played), 0) AS player_seconds "
                "FROM team_game_stats t JOIN games g USING (game_id) "
                "LEFT JOIN player_game_stats p ON p.game_id = t.game_id AND p.team_id = t.team_id "
                "WHERE g.game_date = :d AND g.status = 'final' "
                "GROUP BY t.game_id, t.team_id, g.periods, t.seconds_played "
                "ORDER BY t.game_id, t.team_id"
            ),
            {"d": ctx.game_date},
        ).all()
        problems = []
        for game_id, team_id, periods, team_s, player_s in rows:
            expected = REGULATION_SECONDS + OVERTIME_SECONDS * max(0, (periods or 4) - 4)
            if (
                abs(team_s - expected) > MINUTES_TOLERANCE_S
                or abs(int(player_s) - team_s) > MINUTES_TOLERANCE_S
            ):
                problems.append(
                    {
                        "game_id": game_id,
                        "team_id": team_id,
                        "periods": periods,
                        "expected": expected,
                        "team_seconds": team_s,
                        "player_seconds": int(player_s),
                    }
                )
        if problems:
            return CheckResult(
                check_name=self.name,
                status=CheckStatus.FAIL,
                details={
                    "message": f"{len(problems)} team-game(s) with minutes outside tolerance",
                    "tolerance_seconds": MINUTES_TOLERANCE_S,
                    "problems": problems,
                },
            )
        return CheckResult(
            check_name=self.name,
            status=CheckStatus.PASS,
            details={
                "message": f"minutes consistent for {len(rows)} team-game(s)",
                "tolerance_seconds": MINUTES_TOLERANCE_S,
            },
        )
