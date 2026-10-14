"""Database engine factory. SQLAlchemy Core only; no ORM sessions."""

from sqlalchemy import Engine, create_engine


def get_engine(database_url: str) -> Engine:
    return create_engine(database_url, future=True)
