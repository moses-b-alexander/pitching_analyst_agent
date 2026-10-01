"""Centralized, versioned zone definitions (architecture §17). Used by analytics.metrics.

Coordinates are Statcast catcher's-view feet: plate_x (0 = plate center), plate_z (height),
measured at mid-plate. sz_top / sz_bot are the batter's zone for that pitch.

- in zone: any part of the ball touches the rulebook zone.
- below / above zone: the whole ball is under sz_bot / over sz_top.
- heart: ball center within the middle HEART_FRACTION of the zone's width and height
  (an approximation of Savant's "heart" attack zone).

Bump FEATURE_VERSION when a definition changes.
"""

from __future__ import annotations

FEATURE_VERSION = "0.2"

PLATE_HALF_WIDTH_FT = 17 / 2 / 12
BALL_RADIUS_FT = 2.9 / 2 / 12
HEART_FRACTION = 2 / 3
