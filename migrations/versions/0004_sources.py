"""pipeline_meta (source of record), ingest_runs.source, wider team abbreviations

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE pipeline_meta (
            key         text         PRIMARY KEY,
            value       text         NOT NULL,
            updated_at  timestamptz  NOT NULL DEFAULT now()
        )
        """
    )
    # Before this migration nba_api was the only source, so a database that already
    # holds games is an nba database. An empty one is claimed by its first ingest.
    op.execute(
        "INSERT INTO pipeline_meta (key, value) "
        "SELECT 'source', 'nba' WHERE EXISTS (SELECT 1 FROM games)"
    )
    op.execute("ALTER TABLE ingest_runs ADD COLUMN source text")
    op.execute("UPDATE ingest_runs SET source = 'nba'")
    # Non-NBA preseason opponents can have abbreviations longer than an NBA tricode.
    op.execute("ALTER TABLE teams ALTER COLUMN abbreviation TYPE varchar(6)")


def downgrade() -> None:
    op.execute("ALTER TABLE teams ALTER COLUMN abbreviation TYPE varchar(3)")
    op.execute("ALTER TABLE ingest_runs DROP COLUMN source")
    op.execute("DROP TABLE pipeline_meta")
