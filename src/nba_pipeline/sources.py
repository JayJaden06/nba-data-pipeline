"""Data sources. Each turns a date into clean teams and games, and a started game into
clean box score rows. The pipeline, loaders, quality checks and API never see raw
payloads, so they are identical for every source.

* nba  - nba_api / stats.nba.com. Precise (seconds), but blocks cloud IP ranges.
* espn - ESPN's public JSON. Reachable from GitHub Actions; whole-minute precision.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal, Protocol

from nba_pipeline.ingest import espn as espn_ingest
from nba_pipeline.ingest.boxscore import fetch_boxscore
from nba_pipeline.ingest.client import ApiClient
from nba_pipeline.ingest.scoreboard import fetch_scoreboard
from nba_pipeline.schemas.clean_game import CleanGame
from nba_pipeline.schemas.clean_team import CleanTeam
from nba_pipeline.transform import boxscore as nba_box
from nba_pipeline.transform import espn as espn_transform
from nba_pipeline.transform import games as nba_games
from nba_pipeline.transform import teams as nba_teams
from nba_pipeline.transform.boxscore import BoxScoreRows

SourceName = Literal["nba", "espn"]
SOURCES: tuple[SourceName, ...] = ("nba", "espn")


@dataclass(frozen=True)
class Day:
    teams: list[CleanTeam]
    games: list[CleanGame]


class Source(Protocol):
    name: SourceName

    def fetch_day(self, game_date: date) -> Day: ...

    def fetch_box_score(self, game: CleanGame) -> BoxScoreRows: ...


class NbaSource:
    name: SourceName = "nba"

    def __init__(self, client: ApiClient) -> None:
        self.client = client

    def fetch_day(self, game_date: date) -> Day:
        raw = fetch_scoreboard(self.client, game_date)
        return Day(nba_teams.teams_from_scoreboard(raw), nba_games.to_clean_games(raw))

    def fetch_box_score(self, game: CleanGame) -> BoxScoreRows:
        return nba_box.to_box_score_rows(fetch_boxscore(self.client, game.game_id))


class EspnSource:
    name: SourceName = "espn"

    def __init__(self, client: ApiClient) -> None:
        self.client = client

    def fetch_day(self, game_date: date) -> Day:
        raw = espn_transform.scoreboard_day(
            espn_ingest.fetch_scoreboard(self.client, game_date), game_date
        )
        return Day(
            espn_transform.teams_from_scoreboard(raw), espn_transform.games_from_scoreboard(raw)
        )

    def fetch_box_score(self, game: CleanGame) -> BoxScoreRows:
        raw = espn_ingest.fetch_summary(self.client, game.game_id)
        return espn_transform.to_box_score_rows(raw, game)


def make_source(name: SourceName, client: ApiClient) -> Source:
    return NbaSource(client) if name == "nba" else EspnSource(client)
