import pytest

from nba_pipeline.config import Settings


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        (
            "postgresql://u:p@ep-x.neon.tech/nba?sslmode=require",
            "postgresql+psycopg://u:p@ep-x.neon.tech/nba?sslmode=require",
        ),
        ("postgres://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
        ("postgresql+psycopg://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
    ],
)
def test_database_url_gets_psycopg_driver(given: str, expected: str) -> None:
    assert Settings(database_url=given).database_url == expected
