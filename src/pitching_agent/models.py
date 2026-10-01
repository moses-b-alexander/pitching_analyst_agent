"""Core domain types shared across layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class ProblemClass(str, Enum):
    """SKILL.md §2 observation classes A–I."""

    USAGE_PROPORTION = "usage_proportion"            # A
    CONTINUOUS_SHAPE = "continuous_shape"            # B
    LOCATION_SPATIAL = "location_spatial"            # C
    SEQUENCE_TRANSITION = "sequence_transition"      # D
    COMMAND_PRECISION = "command_precision"          # E
    FATIGUE_TREND = "fatigue_trend"                  # F
    HITTER_RESPONSE = "hitter_response"              # G
    MATCHUP_INTERACTION = "matchup_interaction"      # H
    TRAJECTORY_SEPARATION = "trajectory_separation"  # I


class InferenceType(str, Enum):
    EXPLORATORY = "exploratory"
    PROSPECTIVE = "prospective"


class Half(str, Enum):
    TOP = "top"
    BOTTOM = "bottom"


@dataclass
class Pitch:
    game_id: int
    pitcher_id: int
    batter_id: int
    at_bat_number: int
    pitch_number: int
    inning: int
    half: Half
    balls: int
    strikes: int
    pitch_type: str | None
    description: str | None
    is_strike: bool | None = None
    event: str | None = None
    release_speed: float | None = None
    release_pos_x: float | None = None
    release_pos_z: float | None = None
    release_extension: float | None = None
    plate_x: float | None = None
    plate_z: float | None = None
    sz_top: float | None = None
    sz_bot: float | None = None
    pfx_x: float | None = None
    pfx_z: float | None = None
    spin_rate: float | None = None
    launch_speed: float | None = None
    launch_angle: float | None = None
    timestamp: datetime | None = None
    play_id: str | None = None


@dataclass
class PlateAppearance:
    game_id: int
    at_bat_index: int
    inning: int
    half: Half
    pitcher_id: int
    batter_id: int
    bat_side: str
    is_complete: bool
    event_type: str | None
    outs_on_play: int = 0
    hit_code: str | None = None  # Retrosheet-style, e.g. S8, D9, HR
    # (responsible pitcher id, earned) for each run that scored on this play
    runs: list[tuple[int, bool]] = field(default_factory=list)


@dataclass
class PitcherLine:
    """Box line for a pitcher over some window. None means not yet source-verified."""

    outs: int | None = None
    pitches: int | None = None
    strikes: int | None = None
    hits: int | None = None
    runs: int | None = None
    earned_runs: int | None = None
    walks: int | None = None
    strikeouts: int | None = None
    home_runs: int | None = None
    batters_faced: int | None = None


@dataclass
class TestResult:
    n: int
    baseline_n: int | None
    estimate: float
    baseline_estimate: float | None
    effect: float | None
    ci: tuple[float, float] | None
    p_value: float | None
    method: str
    inference_type: InferenceType
    conditioning: dict[str, Any] = field(default_factory=dict)
