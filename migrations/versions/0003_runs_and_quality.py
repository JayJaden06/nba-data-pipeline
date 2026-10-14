"""ingest_runs, quality_results, ingest_run_id stamps

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STAMPED_TABLES = ("games", "team_game_stats", "player_game_stats")


def upgrade() -> None:
    op.execute("CREATE TYPE run_status AS ENUM ('running', 'succeeded', 'failed')")
    op.execute("CREATE TYPE run_kind AS ENUM ('ingest', 'check')")
    op.execute("CREATE TYPE check_status AS ENUM ('pass', 'warn', 'fail', 'error')")
    op.execute(
        """
        CREATE TABLE ingest_runs (
            run_id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            game_date          date         NOT NULL,
            kind               run_kind     NOT NULL DEFAULT 'ingest',
            status             run_status   NOT NULL,
            started_at         timestamptz  NOT NULL DEFAULT now(),
            finished_at        timestamptz,
            games_total        integer      NOT NULL DEFAULT 0,
            rows_inserted      integer      NOT NULL DEFAULT 0,
            rows_updated       integer      NOT NULL DEFAULT 0,
            rows_unchanged     integer      NOT NULL DEFAULT 0,
            box_scores_loaded  integer      NOT NULL DEFAULT 0,
            box_scores_failed  integer      NOT NULL DEFAULT 0,
            errors             jsonb        NOT NULL DEFAULT '[]',
            summary            jsonb        NOT NULL DEFAULT '{}'
        )
        """
    )
    op.execute("CREATE INDEX ingest_runs_date_idx ON ingest_runs (game_date, started_at DESC)")
    op.execute(
        """
        CREATE TABLE quality_results (
            result_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            run_id      bigint        NOT NULL REFERENCES ingest_runs(run_id),
            game_date   date          NOT NULL,
            check_name  text          NOT NULL,
            status      check_status  NOT NULL,
            details     jsonb         NOT NULL DEFAULT '{}',
            checked_at  timestamptz   NOT NULL DEFAULT now(),
            UNIQUE (run_id, check_name)
        )
        """
    )
    op.execute(
        "CREATE INDEX quality_results_date_idx ON quality_results (game_date, checked_at DESC)"
    )
    for table in STAMPED_TABLES:
        op.execute(
            f"ALTER TABLE {table} ADD COLUMN ingest_run_id bigint REFERENCES ingest_runs(run_id)"
        )


def downgrade() -> None:
    for table in STAMPED_TABLES:
        op.execute(f"ALTER TABLE {table} DROP COLUMN ingest_run_id")
    op.execute("DROP TABLE quality_results")
    op.execute("DROP TABLE ingest_runs")
    op.execute("DROP TYPE check_status")
    op.execute("DROP TYPE run_kind")
    op.execute("DROP TYPE run_status")
