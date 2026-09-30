"""Centralized, versioned pitch-feature definitions (architecture §17).

All zone/location concepts live here. Bump FEATURE_VERSION when a definition changes,
and record the version alongside any stored test result.

Coordinates are Statcast catcher's-view feet: plate_x (0 = plate center), plate_z (height).
"""

from __future__ import annotations

FEATURE_VERSION = "0.1"

PLATE_HALF_WIDTH_FT = 17 / 2 / 12
BALL_RADIUS_FT = 2.9 / 2 / 12


def is_in_zone(plate_x: float, plate_z: float, sz_bot: float, sz_top: float) -> bool:
    """Any part of the ball touches the rulebook zone."""
    edge = PLATE_HALF_WIDTH_FT + BALL_RADIUS_FT
    return abs(plate_x) <= edge and sz_bot - BALL_RADIUS_FT <= plate_z <= sz_top + BALL_RADIUS_FT


def is_below_zone(plate_z: float, sz_bot: float) -> bool:
    return plate_z < sz_bot - BALL_RADIUS_FT


def is_above_zone(plate_z: float, sz_top: float) -> bool:
    return plate_z > sz_top + BALL_RADIUS_FT


# TODO: is_heart / is_edge (Savant attack-zone definitions), is_inner_to_batter /
# is_outer_to_batter (needs batter handedness), backdoor/frontdoor candidates.
