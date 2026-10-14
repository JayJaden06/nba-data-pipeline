"""SQLAlchemy Core table definitions used by the loaders and the API.

The schema itself is owned by the Alembic migrations in migrations/versions; these
definitions must stay in sync with them.
"""

from enum import StrEnum

from sqlalchemy import (
    CHAR,
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

from nba_pipeline.schemas.clean_game import GameStatus, SeasonType

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
    Column("first_seen_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("last_updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
