from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import Connection, RowMapping, Select, select
from sqlalchemy.orm import aliased

from nba_pipeline.api.deps import Conn
from nba_pipeline.api.models import (
    Game,
    GameDetail,
    PlayerLine,
    TeamBoxScore,
    TeamRef,
    stat_fields,
)
from nba_pipeline.load.tables import games, player_game_stats, players, team_game_stats, teams

router = APIRouter(prefix="/games", tags=["games"])

home = aliased(teams, name="home")
away = aliased(teams, name="away")


def team_ref(row: RowMapping, prefix: str) -> TeamRef:
    return TeamRef(
        team_id=row[f"{prefix}_team_id"],
        abbreviation=row[f"{prefix}_abbreviation"],
        full_name=row[f"{prefix}_full_name"],
    )


def games_select() -> Select[Any]:
    return (
        select(
            games,
            home.c.abbreviation.label("home_abbreviation"),
            home.c.full_name.label("home_full_name"),
            away.c.abbreviation.label("away_abbreviation"),
            away.c.full_name.label("away_full_name"),
        )
        .join(home, home.c.team_id == games.c.home_team_id)
        .join(away, away.c.team_id == games.c.away_team_id)
    )


def game_fields(row: RowMapping) -> dict[str, Any]:
    return {
        "game_id": row["game_id"],
        "game_date": row["game_date"],
        "season": row["season"],
        "season_type": row["season_type"].value,
        "status": row["status"].value,
        "home": team_ref(row, "home"),
        "away": team_ref(row, "away"),
        "home_score": row["home_score"],
        "away_score": row["away_score"],
        "periods": row["periods"],
        "national_tv": row["national_tv"],
        "last_updated_at": row["last_updated_at"],
    }


def box_score_for(conn: Connection, game_id: str) -> list[TeamBoxScore] | None:
    team_rows = (
        conn.execute(
            select(team_game_stats, teams.c.abbreviation, teams.c.full_name)
            .join(teams, teams.c.team_id == team_game_stats.c.team_id)
            .where(team_game_stats.c.game_id == game_id)
            .order_by(team_game_stats.c.is_home.desc())
        )
        .mappings()
        .all()
    )
    if not team_rows:
        return None
    player_rows = (
        conn.execute(
            select(player_game_stats, players.c.first_name, players.c.last_name)
            .join(players, players.c.player_id == player_game_stats.c.player_id)
            .where(player_game_stats.c.game_id == game_id)
            .order_by(
                player_game_stats.c.starter.desc(),
                player_game_stats.c.seconds_played.desc(),
                players.c.last_name,
            )
        )
        .mappings()
        .all()
    )
    return [
        TeamBoxScore(
            team=TeamRef(
                team_id=t["team_id"], abbreviation=t["abbreviation"], full_name=t["full_name"]
            ),
            is_home=t["is_home"],
            players=[
                PlayerLine(
                    player_id=p["player_id"],
                    name=f"{p['first_name']} {p['last_name']}".strip(),
                    starter=p["starter"],
                    position=p["position"],
                    played=p["played"],
                    dnp_reason=p["dnp_reason"],
                    **stat_fields(p),
                )
                for p in player_rows
                if p["team_id"] == t["team_id"]
            ],
            **stat_fields(t),
        )
        for t in team_rows
    ]


@router.get("", response_model=list[Game])
def list_games(
    conn: Conn, game_date: Annotated[date, Query(alias="date", description="YYYY-MM-DD")]
) -> list[Game]:
    rows = conn.execute(
        games_select().where(games.c.game_date == game_date).order_by(games.c.game_sequence)
    ).mappings()
    return [Game(**game_fields(r)) for r in rows]


@router.get("/{game_id}", response_model=GameDetail)
def get_game(game_id: str, conn: Conn) -> GameDetail:
    row = conn.execute(games_select().where(games.c.game_id == game_id)).mappings().first()
    if row is None:
        raise HTTPException(404, f"game {game_id} not found")
    return GameDetail(**game_fields(row), box_score=box_score_for(conn, game_id))
