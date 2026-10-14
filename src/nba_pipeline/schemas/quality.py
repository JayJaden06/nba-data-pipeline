"""Structured result of one data-quality check."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CheckStatus(StrEnum):
    PASS = "pass"
    WARN = "warn"  # worth a look, not a data problem (e.g. a game is not final yet)
    FAIL = "fail"  # the loaded data is inconsistent or incomplete
    ERROR = "error"  # the check itself raised


class CheckResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    check_name: str
    status: CheckStatus
    details: dict[str, Any] = Field(default_factory=dict)  # always carries "message"

    @model_validator(mode="after")
    def _has_message(self) -> "CheckResult":
        if "message" not in self.details:
            raise ValueError("details must include a message")
        return self

    @property
    def blocking(self) -> bool:
        """True when this result should fail the run."""
        return self.status in (CheckStatus.FAIL, CheckStatus.ERROR)
