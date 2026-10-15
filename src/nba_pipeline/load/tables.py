"""SQLAlchemy Core table definitions used by the loaders and the API.

The schema itself is owned by the Alembic migrations in migrations/versions; these
definitions must stay in sync with them.
"""

from enum import StrEnum

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    MetaData,
    SmallInteger,
    String,
    Table,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

from nba_pipeline.schemas.clean_game import GameStatus, SeasonType
from nba_pipeline.schemas.quality import CheckStatus
from nba_pipeline.schemas.run import RunKind, RunStatus

metadata = MetaData()


def _values(enum_cls: type[StrEnum]) -> list[str]:
    """Store enum values (e.g. "in_progress"), not member names (IN_PROGRESS)."""
    return [m.value for m in enum_cls]


teams = Table(
    "teams",
    metadata,
    Column("team_id", Integer, primary_key=True),
    Column("abbreviation", String(3), nullable=False),
    Column("city", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("full_name", Text, nullable=False),
    Column("is_nba", Boolean, nullable=False, server_default="true"),
)

games = Table(
    "games",
    metadata,
    Column("game_id", String(10), primary_key=True),
    Column("game_date", Date, nullable=False),
    Column("season", String(7), nullable=False),
    Column(
        "season_type", Enum(SeasonType, name="season_type", values_callable=_values), nullable=False
    ),
    Column("status", Enum(GameStatus, name="game_status", values_callable=_values), nullable=False),
    Column("status_text", Text, nullable=False),
    Column("home_team_id", Integer, ForeignKey("teams.team_id"), nullable=False),
    Column("away_team_id", Integer, ForeignKey("teams.team_id"), nullable=False),
    Column("home_score", Integer),
    Column("away_score", Integer),
    Column("periods", SmallInteger),
    Column("national_tv", Text),
    Column("game_sequence", SmallInteger, nullable=False),
    Column("source_payload_hash", CHAR(64), nullable=False),
    Column("ingest_run_id", BigInteger, ForeignKey("ingest_runs.run_id")),
    Column("first_seen_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("last_updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)


def _stat_columns() -> list[Column[int]]:
    names = [
        "fgm", "fga", "fg3m", "fg3a", "ftm", "fta",
        "oreb", "dreb", "reb", "ast", "stl", "blk", "tov", "pf", "pts",
    ]  # fmt: skip
    return [Column(n, Integer, nullable=False) for n in names]


players = Table(
    "players",
    metadata,
    Column("player_id", Integer, primary_key=True),
    Column("first_name", Text, nullable=False),
    Column("last_name", Text, nullable=False),
    Column("slug", Text, nullable=False),
    Column("first_seen_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("last_updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

team_game_stats = Table(
    "team_game_stats",
    metadata,
    Column("game_id", String(10), ForeignKey("games.game_id"), primary_key=True),
    Column("team_id", Integer, ForeignKey("teams.team_id"), primary_key=True),
    Column("is_home", Boolean, nullable=False),
    Column("seconds_played", Integer, nullable=False),
    *_stat_columns(),
    Column("plus_minus", Integer, nullable=False),
    Column("source_payload_hash", CHAR(64), nullable=False),
    Column("ingest_run_id", BigInteger, ForeignKey("ingest_runs.run_id")),
    Column("first_seen_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("last_updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

player_game_stats = Table(
    "player_game_stats",
    metadata,
    Column("game_id", String(10), ForeignKey("games.game_id"), primary_key=True),
    Column("player_id", Integer, ForeignKey("players.player_id"), primary_key=True),
    Column("team_id", Integer, ForeignKey("teams.team_id"), nullable=False),
    Column("starter", Boolean, nullable=False),
    Column("position", String(3)),
    Column("jersey", String(3)),
    Column("played", Boolean, nullable=False),
    Column("dnp_reason", Text),
    Column("seconds_played", Integer, nullable=False),
    *_stat_columns(),
    Column("plus_minus", Integer, nullable=False),
    Column("source_payload_hash", CHAR(64), nullable=False),
    Column("ingest_run_id", BigInteger, ForeignKey("ingest_runs.run_id")),
    Column("first_seen_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("last_updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)


ingest_runs = Table(
    "ingest_runs",
    metadata,
    Column("run_id", BigInteger, primary_key=True),
    Column("game_date", Date, nullable=False),
    Column("kind", Enum(RunKind, name="run_kind", values_callable=_values), nullable=False),
    Column("status", Enum(RunStatus, name="run_status", values_callable=_values), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("finished_at", DateTime(timezone=True)),
    Column("games_total", Integer, nullable=False, server_default="0"),
    Column("rows_inserted", Integer, nullable=False, server_default="0"),
    Column("rows_updated", Integer, nullable=False, server_default="0"),
    Column("rows_unchanged", Integer, nullable=False, server_default="0"),
    Column("box_scores_loaded", Integer, nullable=False, server_default="0"),
    Column("box_scores_failed", Integer, nullable=False, server_default="0"),
    Column("errors", JSONB, nullable=False, server_default="[]"),
    Column("summary", JSONB, nullable=False, server_default="{}"),
)

quality_results = Table(
    "quality_results",
    metadata,
    Column("result_id", BigInteger, primary_key=True),
    Column("run_id", BigInteger, ForeignKey("ingest_runs.run_id"), nullable=False),
    Column("game_date", Date, nullable=False),
    Column("check_name", Text, nullable=False),
    Column(
        "status", Enum(CheckStatus, name="check_status", values_callable=_values), nullable=False
    ),
    Column("details", JSONB, nullable=False, server_default="{}"),
    Column("checked_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
