"""players, team_game_stats, player_game_stats

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STAT_COLUMNS = """
            fgm                  integer      NOT NULL,
            fga                  integer      NOT NULL,
            fg3m                 integer      NOT NULL,
            fg3a                 integer      NOT NULL,
            ftm                  integer      NOT NULL,
            fta                  integer      NOT NULL,
            oreb                 integer      NOT NULL,
            dreb                 integer      NOT NULL,
            reb                  integer      NOT NULL,
            ast                  integer      NOT NULL,
            stl                  integer      NOT NULL,
            blk                  integer      NOT NULL,
            tov                  integer      NOT NULL,
            pf                   integer      NOT NULL,
            pts                  integer      NOT NULL,
            plus_minus           integer      NOT NULL,
"""

STAT_CHECK = "fgm <= fga AND fg3m <= fg3a AND ftm <= fta AND reb = oreb + dreb"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE players (
            player_id        integer      PRIMARY KEY,
            first_name       text         NOT NULL,
            last_name        text         NOT NULL,
            slug             text         NOT NULL,
            first_seen_at    timestamptz  NOT NULL DEFAULT now(),
            last_updated_at  timestamptz  NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE team_game_stats (
            game_id              varchar(10)  NOT NULL REFERENCES games(game_id),
            team_id              integer      NOT NULL REFERENCES teams(team_id),
            is_home              boolean      NOT NULL,
            seconds_played       integer      NOT NULL,
            {STAT_COLUMNS}
            source_payload_hash  char(64)     NOT NULL,
            first_seen_at        timestamptz  NOT NULL DEFAULT now(),
            last_updated_at      timestamptz  NOT NULL DEFAULT now(),
            PRIMARY KEY (game_id, team_id),
            CONSTRAINT team_game_stats_consistent CHECK ({STAT_CHECK})
        )
        """
    )
    op.execute("CREATE INDEX team_game_stats_team_idx ON team_game_stats (team_id, game_id)")
    op.execute(
        f"""
        CREATE TABLE player_game_stats (
            game_id              varchar(10)  NOT NULL REFERENCES games(game_id),
            player_id            integer      NOT NULL REFERENCES players(player_id),
            team_id              integer      NOT NULL REFERENCES teams(team_id),
            starter              boolean      NOT NULL,
            position             varchar(3),
            jersey               varchar(3),
            played               boolean      NOT NULL,
            dnp_reason           text,
            seconds_played       integer      NOT NULL,
            {STAT_COLUMNS}
            source_payload_hash  char(64)     NOT NULL,
            first_seen_at        timestamptz  NOT NULL DEFAULT now(),
            last_updated_at      timestamptz  NOT NULL DEFAULT now(),
            PRIMARY KEY (game_id, player_id),
            CONSTRAINT player_game_stats_dnp CHECK (played OR seconds_played = 0),
            CONSTRAINT player_game_stats_consistent CHECK ({STAT_CHECK})
        )
        """
    )
    op.execute(
        "CREATE INDEX player_game_stats_player_idx ON player_game_stats (player_id, game_id)"
    )
    op.execute("CREATE INDEX player_game_stats_team_idx ON player_game_stats (game_id, team_id)")


def downgrade() -> None:
    op.execute("DROP TABLE player_game_stats")
    op.execute("DROP TABLE team_game_stats")
    op.execute("DROP TABLE players")
