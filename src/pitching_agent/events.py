"""Event types emitted by the ingestion/state engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class EventType(str, Enum):
    GAME_STARTED = "game_started"
    HALF_INNING_ENDED = "half_inning_ended"
    PITCH_RECORDED = "pitch_recorded"
    PA_ENDED = "pa_ended"
    PITCHER_CHANGED = "pitcher_changed"
    STARTER_EXIT_CANDIDATE = "starter_exit_candidate"
    STARTER_FINALIZED = "starter_finalized"
    USER_OBSERVATION = "user_observation"
    USER_TEST_REQUEST = "user_test_request"
    GAME_ENDED = "game_ended"


@dataclass(frozen=True)
class Event:
    type: EventType
    game_id: int
    payload: dict[str, Any] = field(default_factory=dict)
    at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
