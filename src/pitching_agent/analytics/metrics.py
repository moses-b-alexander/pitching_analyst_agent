"""The metric menu, computed identically for tonight's pitches and the Savant baseline.

Both sources are first put into one frame layout (`tonight_frame`, `savant_frame`), so a
metric is defined once. Names match llm.prompts.METRICS. Bump features.FEATURE_VERSION
when a definition changes.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd

from pitching_agent.analytics.features import BALL_RADIUS_FT, HEART_FRACTION, PLATE_HALF_WIDTH_FT
from pitching_agent.models import Pitch

COLUMNS = [
    "game", "inning", "at_bat_number", "pitch_number", "pitch_type", "release_speed", "pfx_x", "pfx_z",
    "plate_x", "plate_z", "sz_top", "sz_bot", "release_spin_rate", "release_pos_x", "release_pos_z",
    "release_extension", "launch_angle", "launch_speed", "is_swing", "is_whiff",
]  # fmt: skip

_SAVANT_WHIFF = {"swinging_strike", "swinging_strike_blocked"}
_SAVANT_SWING = _SAVANT_WHIFF | {"foul", "foul_tip", "hit_into_play"}


def savant_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=COLUMNS)
    out = df.copy()
    out["game"] = out["game_pk"]
    out["is_swing"] = out["description"].isin(_SAVANT_SWING)
    out["is_whiff"] = out["description"].isin(_SAVANT_WHIFF)
    # Savant also reports exit velocity / launch angle on fouls; the live feed only on balls in play.
    out.loc[out["description"] != "hit_into_play", ["launch_angle", "launch_speed"]] = float("nan")
    return out.sort_values(["game_date", "at_bat_number", "pitch_number"])[COLUMNS].reset_index(drop=True)


def _swing(description: str | None) -> tuple[bool, bool]:
    d = (description or "").lower()
    whiff = d.startswith("swinging strike")
    swing = whiff or d.startswith("in play") or (d.startswith("foul") and "bunt" not in d)
    return swing, whiff


def tonight_frame(pitches: Iterable[Pitch], pitcher_id: int) -> pd.DataFrame:
    rows = []
    for p in pitches:
        if p.pitcher_id != pitcher_id:
            continue
        swing, whiff = _swing(p.description)
        rows.append(
            (p.game_id, p.inning, p.at_bat_number, p.pitch_number, p.pitch_type, p.release_speed, p.pfx_x, p.pfx_z,
             p.plate_x, p.plate_z, p.sz_top, p.sz_bot, p.spin_rate, p.release_pos_x, p.release_pos_z,
             p.release_extension, p.launch_angle, p.launch_speed, swing, whiff)
        )  # fmt: skip
    return pd.DataFrame(rows, columns=COLUMNS)


# -- definitions --------------------------------------------------------------

PROPORTION_METRICS = ("usage_share", "share_below_zone", "share_above_zone", "share_in_zone", "share_heart_of_zone", "whiff_rate")  # fmt: skip

# metric -> (column, multiplier, unit)
CONTINUOUS_METRICS = {
    "release_speed": ("release_speed", 1.0, "mph"),
    "horizontal_break": ("pfx_x", 12.0, "in"),
    "vertical_break": ("pfx_z", 12.0, "in"),
    "spin_rate": ("release_spin_rate", 1.0, "rpm"),
    "release_point": ("release_pos_z", 1.0, "ft"),  # release height
    "extension": ("release_extension", 1.0, "ft"),
    "launch_angle": ("launch_angle", 1.0, "deg"),
    "exit_velocity": ("launch_speed", 1.0, "mph"),
}


def _of_type(df: pd.DataFrame, pitch_type: str | None) -> pd.DataFrame:
    return df if pitch_type is None else df[df["pitch_type"] == pitch_type]


def proportion(df: pd.DataFrame, metric: str, pitch_type: str | None) -> tuple[int, int]:
    """(successes, n) for a rate metric."""
    if metric == "usage_share":
        if pitch_type is None:
            raise ValueError("usage_share needs a pitch type")
        return int((df["pitch_type"] == pitch_type).sum()), len(df)
    sub = _of_type(df, pitch_type)
    if metric == "whiff_rate":
        swings = sub[sub["is_swing"].astype(bool)]
        return int(swings["is_whiff"].sum()), len(swings)

    loc = sub.dropna(subset=["plate_x", "plate_z", "sz_top", "sz_bot"])
    x, z, top, bot = (loc[c].astype(float) for c in ("plate_x", "plate_z", "sz_top", "sz_bot"))
    if metric == "share_below_zone":
        hit = z < bot - BALL_RADIUS_FT
    elif metric == "share_above_zone":
        hit = z > top + BALL_RADIUS_FT
    elif metric == "share_in_zone":
        hit = (x.abs() <= PLATE_HALF_WIDTH_FT + BALL_RADIUS_FT) & (z >= bot - BALL_RADIUS_FT) & (z <= top + BALL_RADIUS_FT)
    elif metric == "share_heart_of_zone":
        mid, half_height = (top + bot) / 2, (top - bot) / 2
        hit = (x.abs() <= PLATE_HALF_WIDTH_FT * HEART_FRACTION) & ((z - mid).abs() <= half_height * HEART_FRACTION)
    else:
        raise ValueError(f"not a proportion metric: {metric}")
    return int(hit.sum()), len(loc)


def values(df: pd.DataFrame, metric: str, pitch_type: str | None) -> np.ndarray:
    """Measured values for a continuous metric, in pitch order, missing readings dropped."""
    column, scale, _ = CONTINUOUS_METRICS[metric]
    return _of_type(df, pitch_type)[column].dropna().to_numpy(dtype=float) * scale


def unit(metric: str) -> str:
    return CONTINUOUS_METRICS[metric][2]


def per_game(df: pd.DataFrame, metric: str, pitch_type: str | None, *, min_n: int = 5) -> np.ndarray:
    """The metric computed separately for each game in `df` (rate or mean), skipping games with under `min_n` readings.

    Pitches within a start are not independent draws from the season, so this spread,
    not the pitch-level baseline, shows how unusual a single start is.
    """
    out = []
    for _, game in df.groupby("game", sort=False):
        if metric in PROPORTION_METRICS:
            k, n = proportion(game, metric, pitch_type)
            if n >= min_n:
                out.append(k / n)
        else:
            v = values(game, metric, pitch_type)
            if len(v) >= min_n:
                out.append(float(v.mean()))
    return np.array(out)
