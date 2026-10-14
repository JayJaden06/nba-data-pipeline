"""Enums for the ingest_runs table."""

from enum import StrEnum


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class RunKind(StrEnum):
    INGEST = "ingest"
    CHECK = "check"  # `nba-pipeline check`: quality checks only, nothing ingested
