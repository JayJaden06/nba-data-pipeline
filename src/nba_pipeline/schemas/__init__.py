"""Pydantic models.

raw_*   : payloads exactly as nba_api returns them. Strict (extra="forbid") so that
          schema drift in the upstream API fails loudly before anything is loaded.
clean_* : rows exactly as stored in Postgres.
"""

from pydantic import ValidationError


class SchemaDriftError(ValueError):
    """Raised when a raw payload does not match the expected shape."""

    def __init__(self, endpoint: str, error: ValidationError) -> None:
        self.endpoint = endpoint
        self.error = error
        super().__init__(f"schema drift in {endpoint}: {error.error_count()} error(s)\n{error}")
