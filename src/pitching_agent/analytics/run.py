"""Run the test a classification names, and print it in a fixed format.

The model chooses test / pitch type / metric from the menus; everything numeric
happens here. Window rule (SKILL.md §5): if the starter has thrown pitches in innings
after the observation, test those (prospective); otherwise test what exists (exploratory).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from pitching_agent.analytics import metrics, stat_tests
from pitching_agent.models import InferenceType, TestResult


@dataclass(frozen=True)
class TestReport:
    text: str
    result: TestResult | None = None  # None: the test could not be run; text says why


def _innings(df: pd.DataFrame) -> str:
    lo, hi = int(df["inning"].min()), int(df["inning"].max())
    return f"inning {lo}" if lo == hi else f"innings {lo}-{hi}"


def _p(p: float) -> str:
    return "p<.001" if p < 0.001 else f"p={p:.3f}".replace("0.", ".", 1)


def _verdict(r: TestResult) -> str:
    word = "significant" if r.significant else "not significant"
    return f"{r.method} | {_p(r.p_value)} | {word} at alpha {r.alpha:g}".replace("alpha 0.", "alpha .")


def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def _starts_line(
    baseline: pd.DataFrame, metric: str, pitch: str | None, tonight_value: float, previous: str | None = None
) -> str | None:
    """Where tonight falls among his individual season starts (guards against significance theater)."""
    games = metrics.per_game(baseline, metric, pitch, previous)
    if len(games) < 3:
        return None
    if metric in metrics.PROPORTION_METRICS:
        fmt = _pct
    else:
        u = metrics.unit(metric)
        fmt = lambda v: f"{v:.1f} {u}"  # noqa: E731
    below = int((games < tonight_value).sum())
    return (
        f"Season starts ({len(games)}): {fmt(games.min())} to {fmt(games.max())}, median {fmt(float(np.median(games)))}"
        f" | tonight is above {below} of {len(games)}"
    )


def run_test(
    classification: dict[str, Any],
    tonight: pd.DataFrame,
    baseline: pd.DataFrame | None,
    *,
    boundary_inning: int,
    alpha: float = stat_tests.DEFAULT_ALPHA,
    mean_method: stat_tests.MeanMethod = "permutation",
) -> TestReport:
    """`tonight` / `baseline` are metrics frames for one pitcher. `boundary_inning` is the last
    inning he had pitched in when the observation was made (0 = before his first pitch)."""
    test, metric, pitch = classification["test"], classification["metric"], classification.get("pitch_type")
    previous = classification.get("previous_pitch_type") if metric == metrics.SEQUENCE_METRIC else None
    what = f"{pitch} after {previous}" if previous and pitch else f"{pitch or 'all pitches'} {metric}"
    is_rate = metric in metrics.PROPORTION_METRICS
    is_value = metric in metrics.CONTINUOUS_METRICS

    if test == "none" or metric == "none":
        return TestReport("No test: this observation is not checkable with pitch data.")
    if not (is_rate or is_value):
        return TestReport(f"No test: {metric} is not computable yet.")
    if metric == "usage_share" and pitch is None:
        return TestReport("No test: usage needs a specific pitch type.")
    if metric == metrics.SEQUENCE_METRIC and not (pitch and previous):
        return TestReport("No test: a sequence needs both pitches, e.g. sinker after four-seam.")
    if tonight.empty:
        return TestReport("No test: he has not thrown a pitch yet.")

    after = tonight[tonight["inning"] > boundary_inning]
    prospective = not after.empty
    window = after if prospective else tonight
    kind = InferenceType.PROSPECTIVE if prospective else InferenceType.EXPLORATORY
    header = f"Test: {what}, {_innings(window)} ({kind.value})"

    needs_baseline = test in ("proportion_vs_baseline", "mean_shift")
    if needs_baseline and (baseline is None or baseline.empty):
        return TestReport("No test: no season baseline is loaded for him.")

    if test == "trend" or (is_value and test in ("two_window_proportion",)):
        if not is_value:
            return TestReport(f"No test: a trend needs a measured value, not a rate ({metric}).")
        vals = metrics.values(tonight, metric, pitch)  # a trend uses the whole outing
        if len(vals) < 5:
            return TestReport(f"No test: only {len(vals)} readings of {what} tonight.")
        r = stat_tests.trend(vals, alpha=alpha, inference_type=InferenceType.EXPLORATORY)
        u = metrics.unit(metric)
        return TestReport(
            "\n".join([
                f"Test: {what}, {_innings(tonight)} (exploratory)",
                f"Tonight: {r.estimate:+.3f} {u} per pitch over {r.n} pitches | fitted change {r.effect:+.1f} {u}",
                _verdict(r),
            ]),
            r,
        )  # fmt: skip

    if is_rate:
        k, n = metrics.proportion(window, metric, pitch, previous)
        if n == 0:
            return TestReport(f"No test: nothing to count for {what} in {_innings(window)}.")
        if test == "two_window_proportion":
            if not prospective:
                return TestReport("No test: no pitches after the observation yet to compare against.")
            k0, n0 = metrics.proportion(tonight[tonight["inning"] <= boundary_inning], metric, pitch, previous)
            if n0 == 0:
                return TestReport(f"No test: nothing to count for {what} before the observation.")
            r = stat_tests.fisher_two_window((k0, n0), (k, n), alpha=alpha, inference_type=kind)
            lines = [
                header,
                f"Later: {k}/{n} ({_pct(r.estimate)}) | Earlier: {k0}/{n0} ({_pct(r.baseline_estimate)}) | Effect: {100 * r.effect:+.1f} pp",
            ]
        else:
            k0, n0 = metrics.proportion(baseline, metric, pitch, previous)
            if n0 == 0:
                return TestReport(f"No test: the season baseline has no {what} to compare against.")
            r = stat_tests.binomial_vs_baseline(k, n, k0 / n0, baseline_n=n0, alpha=alpha, inference_type=kind)
            lines = [
                header,
                f"Tonight: {k}/{n} ({_pct(r.estimate)})",
                f"Baseline: {_pct(r.baseline_estimate)} (n={n0}) | Effect: {100 * r.effect:+.1f} pp"
                f" | {100 * (1 - alpha):g}% CI {_pct(r.ci[0])} to {_pct(r.ci[1])}",
            ]
            starts = _starts_line(baseline, metric, pitch, r.estimate, previous)
            if starts:
                lines.append(starts)
        return TestReport("\n".join([*lines, _verdict(r)]), r)

    # mean_shift (also the fallback when a rate test was picked for a measured value)
    vals, base = metrics.values(window, metric, pitch), metrics.values(baseline, metric, pitch)
    if len(vals) < 2 or len(base) < 2:
        return TestReport(f"No test: too few readings of {what} (tonight {len(vals)}, baseline {len(base)}).")
    r = stat_tests.mean_shift(vals, base, method=mean_method, alpha=alpha, inference_type=kind)
    u = metrics.unit(metric)
    lines = [
        header,
        f"Tonight: {r.estimate:.1f} {u} (n={r.n})",
        f"Baseline: {r.baseline_estimate:.1f} {u} (n={r.baseline_n}) | Effect: {r.effect:+.1f} {u}"
        f" | {100 * (1 - alpha):g}% CI {r.ci[0]:+.1f} to {r.ci[1]:+.1f}",
    ]
    starts = _starts_line(baseline, metric, pitch, r.estimate)
    if starts:
        lines.append(starts)
    return TestReport("\n".join([*lines, _verdict(r)]), r)
