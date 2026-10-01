"""Prompts and output schemas.

The behavioral contract is skills/live-starting-pitching-analyst/SKILL.md, but it is
~8k tokens and local models load with a small context window, so prompts here are
condensed. Class definitions plus examples are what make an 8B model classify
correctly (8/8 on the probe set with them, wrong without).
"""

from __future__ import annotations

from pathlib import Path

from pitching_agent.models import ProblemClass

SKILL_PATH = Path(__file__).resolve().parents[3] / "skills" / "live-starting-pitching-analyst" / "SKILL.md"

PITCH_CODES = (
    "Pitch codes: FF four-seam, SI sinker, FC cutter, SL slider, ST sweeper, CU curveball, "
    "KC knuckle curve, CH changeup, FS splitter. "
    '"4s" or "heater" = FF. "breaker" = the pitcher\'s main breaking ball.'
)

TESTS = ("proportion_vs_baseline", "two_window_proportion", "mean_shift", "trend", "none")

# Every metric here must be computable from normalized pitches (models.Pitch).
METRICS = (
    "usage_share",
    "share_below_zone",
    "share_above_zone",
    "share_in_zone",
    "share_heart_of_zone",
    "share_after_previous_pitch_type",
    "whiff_rate",
    "release_speed",
    "horizontal_break",
    "vertical_break",
    "spin_rate",
    "release_point",
    "extension",
    "launch_angle",
    "exit_velocity",
    "none",
)

CLASSIFY_SYSTEM = f"""You classify a baseball viewer's observation about a starting pitcher and choose the statistical test that checks it.

{PITCH_CODES}

Classes (pick the single best):
- usage_proportion: how OFTEN a pitch is thrown ("throwing way more sliders", "curve usage is up")
- continuous_shape: the pitch itself changed: movement, spin, break, release point ("slider looks flatter", "more ride on the heater")
- location_spatial: WHERE pitches end up ("curve looks lower", "everything is up", "living on the outside edge")
- sequence_transition: what pitch follows what, or pitch choice by count ("sinker after four-seamers", "always curve first pitch")
- command_precision: missing spots, leaking over the middle ("no command", "missing arm side")
- fatigue_trend: decline as the outing goes on ("velo looks cooked", "losing steam", "tiring")
- hitter_response: what hitters do ("swinging flat", "late on the fastball", "taking the low stuff")
- matchup_interaction: differs by batter hand or times through the order ("only doing it to lefties")
- trajectory_separation: two pitches looking alike out of the hand, tunneling, late break

Tests:
- proportion_vs_baseline: tonight's rate of something vs the pitcher's season rate (usage share, share below the zone)
- two_window_proportion: a rate in early innings vs later innings tonight
- mean_shift: tonight's average of a measured value (velocity, break, release) vs season
- trend: a measured value drifting pitch by pitch within tonight's outing
- none: not checkable with pitch data

pitch_type is the pitch code the observation is about, or null if it is not about one pitch.
metric is what to measure. Use "none" if nothing on the list fits.

Examples:
"his curve looks way lower tonight" -> location_spatial, proportion_vs_baseline, CU, share_below_zone
"his velo looks cooked" -> fatigue_trend, trend, FF, release_speed
"slider is flatter than usual" -> continuous_shape, mean_shift, SL, horizontal_break
"fastball is leaking middle" -> command_precision, proportion_vs_baseline, FF, share_heart_of_zone
"he keeps going sinker after 4s" -> sequence_transition, proportion_vs_baseline, SI, share_after_previous_pitch_type
"they're swinging flat" -> hitter_response, mean_shift, null, launch_angle"""

CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "primary_class": {"type": "string", "enum": [c.value for c in ProblemClass]},
        "test": {"type": "string", "enum": list(TESTS)},
        "pitch_type": {"type": ["string", "null"]},
        "metric": {"type": "string", "enum": list(METRICS)},
    },
    "required": ["primary_class", "test", "pitch_type", "metric"],
}


def load_skill() -> str:
    return SKILL_PATH.read_text(encoding="utf-8")
