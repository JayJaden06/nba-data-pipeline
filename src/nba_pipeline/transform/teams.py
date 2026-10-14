"""Teams referenced by a scoreboard payload.

The 30 NBA franchises are seeded by migration 0001. Preseason games against non-NBA
opponents (e.g. London Lions, team_id 50015) would otherwise violate the games -> teams
foreign key, so every team seen in a payload is registered before games are loaded.
"""

from __future__ import annotations

from functools import cache

from nba_api.stats.static import teams as static_teams

from nba_pipeline.schemas.clean_team import CleanTeam
from nba_pipeline.schemas.raw_scoreboard import RawScoreboardResponse, RawTeam


@cache
def nba_team_ids() -> frozenset[int]:
    """IDs of the 30 current franchises, from nba_api's bundled static data."""
    return frozenset(int(t["id"]) for t in static_teams.get_teams())


def to_clean_team(team: RawTeam) -> CleanTeam:
    return CleanTeam(
        team_id=team.team_id,
        abbreviation=team.team_tricode,
        city=team.team_city,
        name=team.team_name,
        full_name=f"{team.team_city} {team.team_name}".strip(),
        is_nba=team.team_id in nba_team_ids(),
    )


def teams_from_scoreboard(raw: RawScoreboardResponse) -> list[CleanTeam]:
    """Distinct teams in payload order (home then away, per game)."""
    seen: dict[int, CleanTeam] = {}
    for game in raw.scoreboard.games:
        for team in (game.home_team, game.away_team):
            seen.setdefault(team.team_id, to_clean_team(team))
    return list(seen.values())
