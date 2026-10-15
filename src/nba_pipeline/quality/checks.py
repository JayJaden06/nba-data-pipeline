"""Registry of every quality check, in the order they run and are reported."""

from __future__ import annotations

from nba_pipeline.quality import QualityCheck
from nba_pipeline.quality.box_checks import (
    BoxScoresComplete,
    NoDuplicatePlayerRows,
    TeamMinutesSum,
    TeamPointsMatchPlayers,
)
from nba_pipeline.quality.run_checks import Freshness, SchemaDrift

ALL_CHECKS: tuple[QualityCheck, ...] = (
    BoxScoresComplete(),
    NoDuplicatePlayerRows(),
    TeamPointsMatchPlayers(),
    TeamMinutesSum(),
    SchemaDrift(),
    Freshness(),
)
