"""Centralized, versioned zone definitions (architecture §17). Used by analytics.metrics.

Coordinates are Statcast catcher's-view feet: plate_x (0 = plate center), plate_z (height),
measured at mid-plate. sz_top / sz_bot are the batter's zone for that pitch.

The "effective zone" is the rulebook zone widened by one ball radius on every side, i.e.
every location where some part of the ball touches the zone.

- in zone: the ball center is inside the effective zone.
- below / above zone: the whole ball is under sz_bot / over sz_top.
- heart: the ball center is within the middle two thirds of the effective zone, in both
  width and height. This is Savant's "heart" attack zone (zones 1-9): it reproduces
  Savant's own heart filter exactly on a full season (tests/test_baseline.py).

Bump FEATURE_VERSION when a definition changes.
"""

from __future__ import annotations

FEATURE_VERSION = "0.3"

PLATE_HALF_WIDTH_FT = 17 / 2 / 12
BALL_RADIUS_FT = 2.9 / 2 / 12
HEART_FRACTION = 2 / 3
