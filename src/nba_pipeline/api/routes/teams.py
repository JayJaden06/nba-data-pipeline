from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import aliased

from nba_pipeline.api.deps import Conn, SeasonParam
from nba_pipeline.api.models import (
    StatLine,
    TeamGameLine,
    TeamGames,
    TeamRef,
    result_for,
)
from nba_pipeline.load.tables import games, team_game_stats, teams

router = APIRouter(prefix="/teams", tags=["teams"])

opp = aliased(teams, name="opp")

# Columns of team_game_stats that are keys or bookkeeping, not stats; they would also
# clash with the games columns selected alongside.
_NOT_STATS = frozenset(
    {"game_id", "team_id", "is_home", "source_payload_hash", "ingest_run_id",
     "first_seen_at", "last_updated_at"}
)  # fmt: skip


@router.get("/{team_id}/games", response_model=TeamGames)
def team_games(team_id: int, conn: Conn, season: SeasonParam) -> TeamGames:
    team = conn.execute(select(teams).where(teams.c.team_id == team_id)).mappings().first()
    if team is None:
        raise HTTPException(404, f"team {team_id} not found")

    is_home = games.c.home_team_id == team_id
    rows = (
        conn.execute(
            select(
                games.c.game_id,
                games.c.game_date,
                games.c.status,
                games.c.home_score,
                games.c.away_score,
                is_home.label("is_home"),
                opp.c.team_id.label("opp_team_id"),
                opp.c.abbreviation.label("opp_abbreviation"),
                opp.c.full_name.label("opp_full_name"),
                *[c for c in team_game_stats.c if c.name not in _NOT_STATS],
            )
            .join(
                opp,
                and_(
                    opp.c.team_id.in_([games.c.home_team_id, games.c.away_team_id]),
                    opp.c.team_id != team_id,
                ),
            )
            .outerjoin(
                team_game_stats,
                and_(
                    team_game_stats.c.game_id == games.c.game_id,
                    team_game_stats.c.team_id == team_id,
                ),
            )
            .where(
                or_(games.c.home_team_id == team_id, games.c.away_team_id == team_id),
                games.c.season == season,
            )
            .order_by(games.c.game_date.desc(), games.c.game_id.desc())
        )
        .mappings()
        .all()
    )

    lines: list[TeamGameLine] = []
    wins = losses = 0
    for r in rows:
        own, other = (
            (r["home_score"], r["away_score"])
            if r["is_home"]
            else (r["away_score"], r["home_score"])
        )
        result = result_for(own, other, r["status"].value)
        wins += result == "W"
        losses += result == "L"
        has_box = r["seconds_played"] is not None
        lines.append(
            TeamGameLine(
                game_id=r["game_id"],
                game_date=r["game_date"],
                status=r["status"].value,
                opponent=TeamRef(
                    team_id=r["opp_team_id"],
                    abbreviation=r["opp_abbreviation"],
                    full_name=r["opp_full_name"],
                ),
                is_home=r["is_home"],
                result=result,
                team_score=own,
                opponent_score=other,
                stats=StatLine.from_row(r) if has_box else None,
            )
        )
    return TeamGames(
        team=TeamRef(
            team_id=team["team_id"], abbreviation=team["abbreviation"], full_name=team["full_name"]
        ),
        season=season,
        record=f"{wins}-{losses}",
        games=lines,
    )
