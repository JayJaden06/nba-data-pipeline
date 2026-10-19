from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import and_, select
from sqlalchemy.orm import aliased

from nba_pipeline.api.deps import Conn, SeasonParam
from nba_pipeline.api.models import (
    STAT_COLUMNS,
    PlayerGameLine,
    PlayerGames,
    PlayerRef,
    StatLine,
    TeamRef,
    result_for,
    stat_fields,
)
from nba_pipeline.load.tables import games, player_game_stats, players, teams

router = APIRouter(prefix="/players", tags=["players"])

own = aliased(teams, name="own")
opp = aliased(teams, name="opp")


@router.get("/{player_id}/games", response_model=PlayerGames)
def player_games(player_id: int, conn: Conn, season: SeasonParam) -> PlayerGames:
    player = (
        conn.execute(select(players).where(players.c.player_id == player_id)).mappings().first()
    )
    if player is None:
        raise HTTPException(404, f"player {player_id} not found")

    is_home = player_game_stats.c.team_id == games.c.home_team_id
    rows = (
        conn.execute(
            select(
                player_game_stats,
                games.c.game_date,
                games.c.status,
                games.c.home_team_id,
                games.c.away_team_id,
                games.c.home_score,
                games.c.away_score,
                is_home.label("is_home"),
                own.c.abbreviation.label("own_abbreviation"),
                own.c.full_name.label("own_full_name"),
                opp.c.team_id.label("opp_team_id"),
                opp.c.abbreviation.label("opp_abbreviation"),
                opp.c.full_name.label("opp_full_name"),
            )
            .join(games, games.c.game_id == player_game_stats.c.game_id)
            .join(own, own.c.team_id == player_game_stats.c.team_id)
            .join(
                opp,
                and_(
                    opp.c.team_id.in_([games.c.home_team_id, games.c.away_team_id]),
                    opp.c.team_id != player_game_stats.c.team_id,
                ),
            )
            .where(player_game_stats.c.player_id == player_id, games.c.season == season)
            .order_by(games.c.game_date.desc(), games.c.game_id.desc())
        )
        .mappings()
        .all()
    )

    lines: list[PlayerGameLine] = []
    for r in rows:
        own_score, opp_score = (
            (r["home_score"], r["away_score"])
            if r["is_home"]
            else (r["away_score"], r["home_score"])
        )
        lines.append(
            PlayerGameLine(
                game_id=r["game_id"],
                game_date=r["game_date"],
                team=TeamRef(
                    team_id=r["team_id"],
                    abbreviation=r["own_abbreviation"],
                    full_name=r["own_full_name"],
                ),
                opponent=TeamRef(
                    team_id=r["opp_team_id"],
                    abbreviation=r["opp_abbreviation"],
                    full_name=r["opp_full_name"],
                ),
                is_home=r["is_home"],
                starter=r["starter"],
                played=r["played"],
                dnp_reason=r["dnp_reason"],
                result=result_for(own_score, opp_score, r["status"].value),
                **stat_fields(r),
            )
        )

    totals: dict[str, Any] = {c: 0 for c in (*STAT_COLUMNS, "seconds_played", "plus_minus")}
    for r in rows:
        if r["played"]:
            for c in totals:
                totals[c] += r[c]
    return PlayerGames(
        player=PlayerRef(
            player_id=player["player_id"],
            name=f"{player['first_name']} {player['last_name']}".strip(),
            slug=player["slug"],
        ),
        season=season,
        games=lines,
        totals=StatLine.from_row(totals),
    )
