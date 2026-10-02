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
    "release_extension", "launch_angle", "launch_speed", "is_swing", "is_whiff", "stand", "prev_pitch_type",
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
    out = out.sort_values(["game_date", "game", "at_bat_number", "pitch_number"])
    return _with_previous(out)[COLUMNS].reset_index(drop=True)


def _with_previous(df: pd.DataFrame) -> pd.DataFrame:
    """Add the type of the pitch thrown just before, within the same plate appearance (None on the first pitch)."""
    df = df.copy()
    df["prev_pitch_type"] = df.groupby(["game", "at_bat_number"], sort=False)["pitch_type"].shift(1)
    return df


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
             p.release_extension, p.launch_angle, p.launch_speed, swing, whiff, p.stand)
        )  # fmt: skip
    df = pd.DataFrame(rows, columns=COLUMNS[:-1]).sort_values(["at_bat_number", "pitch_number"])
    return _with_previous(df)[COLUMNS].reset_index(drop=True)


# -- definitions --------------------------------------------------------------

SEQUENCE_METRIC = "share_after_previous_pitch_type"
PROPORTION_METRICS = (
    "usage_share", "share_below_zone", "share_above_zone", "share_in_zone", "share_heart_of_zone", "whiff_rate",
    SEQUENCE_METRIC,
)  # fmt: skip

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


def proportion(df: pd.DataFrame, metric: str, pitch_type: str | None, previous: str | None = None) -> tuple[int, int]:
    """(successes, n) for a rate metric.

    The sequence metric is: of the pitches thrown right after a `previous`-type pitch in the
    same plate appearance, the share that were `pitch_type`.
    """
    if metric == SEQUENCE_METRIC:
        if pitch_type is None or previous is None:
            raise ValueError("the sequence metric needs both the pitch and the pitch before it")
        followers = df[df["prev_pitch_type"] == previous]
        return int((followers["pitch_type"] == pitch_type).sum()), len(followers)
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
        hit = (x.abs() <= (PLATE_HALF_WIDTH_FT + BALL_RADIUS_FT) * HEART_FRACTION) & (
            (z - mid).abs() <= (half_height + BALL_RADIUS_FT) * HEART_FRACTION
        )
    else:
        raise ValueError(f"not a proportion metric: {metric}")
    return int(hit.sum()), len(loc)


def values(df: pd.DataFrame, metric: str, pitch_type: str | None) -> np.ndarray:
    """Measured values for a continuous metric, in pitch order, missing readings dropped."""
    column, scale, _ = CONTINUOUS_METRICS[metric]
    return _of_type(df, pitch_type)[column].dropna().to_numpy(dtype=float) * scale


def unit(metric: str) -> str:
    return CONTINUOUS_METRICS[metric][2]


def per_game(
    df: pd.DataFrame, metric: str, pitch_type: str | None, previous: str | None = None, *, min_n: int = 5
) -> np.ndarray:
    """The metric computed separately for each game in `df` (rate or mean), skipping games with under `min_n` readings.

    Pitches within a start are not independent draws from the season, so this spread,
    not the pitch-level baseline, shows how unusual a single start is.
    """
    out = []
    for _, game in df.groupby("game", sort=False):
        if metric in PROPORTION_METRICS:
            k, n = proportion(game, metric, pitch_type, previous)
            if n >= min_n:
                out.append(k / n)
        else:
            v = values(game, metric, pitch_type)
            if len(v) >= min_n:
                out.append(float(v.mean()))
    return np.array(out)


def season_velo(baseline: pd.DataFrame | None) -> dict[str, float]:
    """Season average velocity per pitch type."""
    if baseline is None or baseline.empty:
        return {}
    return baseline.dropna(subset=["release_speed", "pitch_type"]).groupby("pitch_type")["release_speed"].mean().to_dict()


_TABLE_VALUES = (
    ("release_speed", "velo", "{:.1f}", "mph"),
    ("vertical_break", "vert break", "{:.1f}", "in"),
    ("horizontal_break", "horiz break", "{:+.1f}", "in"),
    ("spin_rate", "spin", "{:.0f}", "rpm"),
)
_TABLE_RATES = (
    ("share_in_zone", "in zone", ""),
    ("share_heart_of_zone", "heart", ""),
    ("share_below_zone", "below zone", ""),
    ("whiff_rate", "whiffs", " swings"),
)


def pitch_table(tonight: pd.DataFrame, baseline: pd.DataFrame | None = None) -> list[str]:
    """One line per pitch type with the data the tests use, tonight and (in parentheses) his season.

    Shown by /detail and given to the model, so its replies have real numbers to draw on.
    """
    from pitching_agent.analytics.lines import order_mix

    has_base = baseline is not None and not baseline.empty
    counts = tonight["pitch_type"].dropna().value_counts()
    rows = []
    for pt in order_mix({t: int(n) for t, n in counts.items()}):
        parts = [f"{pt}: {counts[pt]} thrown"]
        for metric, label, fmt, unit_ in _TABLE_VALUES:
            v = values(tonight, metric, pt)
            if len(v) == 0:
                continue
            text = f"{label} {fmt.format(v.mean())} {unit_}"
            if has_base and len(b := values(baseline, metric, pt)):
                text += f" (season {fmt.format(b.mean())})"
            parts.append(text)
        for metric, label, suffix in _TABLE_RATES:
            k, n = proportion(tonight, metric, pt)
            if n == 0:
                continue
            text = f"{label} {k}/{n}{suffix}"
            if has_base:
                k0, n0 = proportion(baseline, metric, pt)
                if n0:
                    text += f" (season {100 * k0 / n0:.0f}%)"
            parts.append(text)
        rows.append(" | ".join(parts))

    if len(counts):  # velocity by inning for his most-thrown pitch: the fatigue question
        main = counts.idxmax()
        by_inning = tonight[tonight["pitch_type"] == main].dropna(subset=["release_speed"]).groupby("inning")["release_speed"].mean()
        if len(by_inning) > 1:
            rows.append(f"{main} velo by inning: " + " | ".join(f"I{int(i)} {v:.1f}" for i, v in by_inning.items()))
    return rows
