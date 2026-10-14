"""teams and games

Revision ID: 0001
Revises:
Create Date: 2026-10-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE TYPE game_status AS ENUM ('scheduled', 'in_progress', 'final', 'postponed')")
    op.execute(
        "CREATE TYPE season_type AS ENUM "
        "('preseason', 'regular', 'all_star', 'playoffs', 'play_in')"
    )
    op.execute(
        """
        CREATE TABLE teams (
            team_id       integer     PRIMARY KEY,
            abbreviation  varchar(3)  NOT NULL,
            city          text        NOT NULL,
            name          text        NOT NULL,
            full_name     text        NOT NULL,
            is_nba        boolean     NOT NULL DEFAULT true
        )
        """
    )
    op.execute(
        """
        CREATE TABLE games (
            game_id              varchar(10)  PRIMARY KEY,
            game_date            date         NOT NULL,
            season               varchar(7)   NOT NULL,
            season_type          season_type  NOT NULL,
            status               game_status  NOT NULL,
            status_text          text         NOT NULL,
            home_team_id         integer      NOT NULL REFERENCES teams(team_id),
            away_team_id         integer      NOT NULL REFERENCES teams(team_id),
            home_score           integer,
            away_score           integer,
            periods              smallint,
            national_tv          text,
            game_sequence        smallint     NOT NULL,
            source_payload_hash  char(64)     NOT NULL,
            first_seen_at        timestamptz  NOT NULL DEFAULT now(),
            last_updated_at      timestamptz  NOT NULL DEFAULT now(),
            CONSTRAINT games_scores_final CHECK (
                status <> 'final' OR (home_score IS NOT NULL AND away_score IS NOT NULL)
            ),
            CONSTRAINT games_distinct_teams CHECK (home_team_id <> away_team_id)
        )
        """
    )
    # Preseason opponents (e.g. London Lions, team_id 50015) are discovered from the
    # scoreboard and inserted with is_nba = false. Tricodes are only unique among NBA teams.
    op.execute(
        "CREATE UNIQUE INDEX teams_abbreviation_nba_idx ON teams (abbreviation) WHERE is_nba"
    )
    op.execute("CREATE INDEX games_game_date_idx ON games (game_date)")
    op.execute("CREATE INDEX games_season_home_idx ON games (season, home_team_id)")
    op.execute("CREATE INDEX games_season_away_idx ON games (season, away_team_id)")

    # Seed the 30 current franchises from nba_api.stats.static.teams (bundled data, no
    # network call). Materialised here so the migration has no runtime dependency.
    op.execute(
        """
        INSERT INTO teams (team_id, abbreviation, city, name, full_name) VALUES
        (1610612737, 'ATL', 'Atlanta', 'Hawks', 'Atlanta Hawks'),
        (1610612738, 'BOS', 'Boston', 'Celtics', 'Boston Celtics'),
        (1610612739, 'CLE', 'Cleveland', 'Cavaliers', 'Cleveland Cavaliers'),
        (1610612740, 'NOP', 'New Orleans', 'Pelicans', 'New Orleans Pelicans'),
        (1610612741, 'CHI', 'Chicago', 'Bulls', 'Chicago Bulls'),
        (1610612742, 'DAL', 'Dallas', 'Mavericks', 'Dallas Mavericks'),
        (1610612743, 'DEN', 'Denver', 'Nuggets', 'Denver Nuggets'),
        (1610612744, 'GSW', 'San Francisco', 'Warriors', 'Golden State Warriors'),
        (1610612745, 'HOU', 'Houston', 'Rockets', 'Houston Rockets'),
        (1610612746, 'LAC', 'Los Angeles', 'Clippers', 'Los Angeles Clippers'),
        (1610612747, 'LAL', 'Los Angeles', 'Lakers', 'Los Angeles Lakers'),
        (1610612748, 'MIA', 'Miami', 'Heat', 'Miami Heat'),
        (1610612749, 'MIL', 'Milwaukee', 'Bucks', 'Milwaukee Bucks'),
        (1610612750, 'MIN', 'Minnesota', 'Timberwolves', 'Minnesota Timberwolves'),
        (1610612751, 'BKN', 'Brooklyn', 'Nets', 'Brooklyn Nets'),
        (1610612752, 'NYK', 'New York', 'Knicks', 'New York Knicks'),
        (1610612753, 'ORL', 'Orlando', 'Magic', 'Orlando Magic'),
        (1610612754, 'IND', 'Indiana', 'Pacers', 'Indiana Pacers'),
        (1610612755, 'PHI', 'Philadelphia', '76ers', 'Philadelphia 76ers'),
        (1610612756, 'PHX', 'Phoenix', 'Suns', 'Phoenix Suns'),
        (1610612757, 'POR', 'Portland', 'Trail Blazers', 'Portland Trail Blazers'),
        (1610612758, 'SAC', 'Sacramento', 'Kings', 'Sacramento Kings'),
        (1610612759, 'SAS', 'San Antonio', 'Spurs', 'San Antonio Spurs'),
        (1610612760, 'OKC', 'Oklahoma City', 'Thunder', 'Oklahoma City Thunder'),
        (1610612761, 'TOR', 'Toronto', 'Raptors', 'Toronto Raptors'),
        (1610612762, 'UTA', 'Utah', 'Jazz', 'Utah Jazz'),
        (1610612763, 'MEM', 'Memphis', 'Grizzlies', 'Memphis Grizzlies'),
        (1610612764, 'WAS', 'Washington', 'Wizards', 'Washington Wizards'),
        (1610612765, 'DET', 'Detroit', 'Pistons', 'Detroit Pistons'),
        (1610612766, 'CHA', 'Charlotte', 'Hornets', 'Charlotte Hornets')
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE games")
    op.execute("DROP TABLE teams")
    op.execute("DROP TYPE game_status")
    op.execute("DROP TYPE season_type")
