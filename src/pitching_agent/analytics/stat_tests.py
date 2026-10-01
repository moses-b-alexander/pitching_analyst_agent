"""The stat-test menu (architecture §8). Every function returns a TestResult.

Named stat_tests (not tests.py as in the architecture doc) to avoid confusion with the test suite.
Tests execute only on explicit user request (decisions.md #3). Default alpha is 0.05.
"""

from __future__ import annotations

from typing import Literal

import numpy as np
from scipy import stats

from pitching_agent.models import InferenceType, TestResult

Alternative = Literal["two-sided", "greater", "less"]
MeanMethod = Literal["permutation", "welch"]

DEFAULT_ALPHA = 0.05
RESAMPLES = 10_000
SEED = 20260930  # fixed so the same data always prints the same p-value


def binomial_vs_baseline(
    successes: int,
    n: int,
    baseline_rate: float,
    *,
    baseline_n: int | None = None,
    alternative: Alternative = "two-sided",
    alpha: float = DEFAULT_ALPHA,
    inference_type: InferenceType,
    conditioning: dict | None = None,
) -> TestResult:
    """Exact binomial test of an observed proportion against a historical rate.

    e.g. tonight 11/13 curves below zone vs season 61.2%.
    """
    res = stats.binomtest(successes, n, baseline_rate, alternative=alternative)
    ci = res.proportion_ci(confidence_level=1 - alpha, method="exact")
    estimate = successes / n
    return TestResult(
        n=n,
        baseline_n=baseline_n,
        estimate=estimate,
        baseline_estimate=baseline_rate,
        effect=estimate - baseline_rate,
        ci=(float(ci.low), float(ci.high)),
        p_value=float(res.pvalue),
        method=f"exact binomial ({alternative})",
        inference_type=inference_type,
        conditioning=conditioning or {},
        alpha=alpha,
    )


def fisher_two_window(
    early: tuple[int, int],
    late: tuple[int, int],
    *,
    alpha: float = DEFAULT_ALPHA,
    inference_type: InferenceType,
    conditioning: dict | None = None,
) -> TestResult:
    """Fisher exact test of a rate in a later window against an earlier one, each given as (successes, n)."""
    (a, n1), (b, n2) = early, late
    res = stats.fisher_exact([[b, n2 - b], [a, n1 - a]])
    return TestResult(
        n=n2,
        baseline_n=n1,
        estimate=b / n2,
        baseline_estimate=a / n1,
        effect=b / n2 - a / n1,
        ci=None,
        p_value=float(res.pvalue),
        method="Fisher exact (two-sided)",
        inference_type=inference_type,
        conditioning=conditioning or {},
        alpha=alpha,
    )


def mean_shift(
    tonight: np.ndarray,
    baseline: np.ndarray,
    *,
    method: MeanMethod = "permutation",
    alpha: float = DEFAULT_ALPHA,
    inference_type: InferenceType,
    conditioning: dict | None = None,
) -> TestResult:
    """Difference in means, tonight minus baseline.

    `permutation` (default) permutes the Welch statistic and assumes no distribution, as SKILL.md prefers;
    `welch` is the normal-theory unequal-variance t-test. The CI is for the difference.
    """
    diff = float(tonight.mean() - baseline.mean())
    if method == "welch":
        res = stats.ttest_ind(tonight, baseline, equal_var=False)
        interval = res.confidence_interval(1 - alpha)
        p, ci, name = float(res.pvalue), (float(interval.low), float(interval.high)), "Welch t-test (two-sided)"
    else:
        rng = np.random.default_rng(SEED)
        pooled, k, m = np.concatenate([tonight, baseline]), len(tonight), len(baseline)
        total, total_sq = pooled.sum(), (pooled**2).sum()

        def welch_t(s1: float, q1: float) -> float:
            """Welch t for a k-subset with sum s1 and sum of squares q1 against the remaining m."""
            s2, q2 = total - s1, total_sq - q1
            v1 = max(q1 - s1 * s1 / k, 0.0) / (k - 1)
            v2 = max(q2 - s2 * s2 / m, 0.0) / (m - 1)
            se = np.sqrt(v1 / k + v2 / m)
            return (s1 / k - s2 / m) / se if se > 0 else 0.0

        # Studentized: permuting the Welch statistic stays valid when tonight's spread differs from
        # the season's (a raw difference in means does not). One resample at a time, because a
        # (resamples x pitches) array would cost hundreds of MB for a season baseline.
        observed = welch_t(tonight.sum(), (tonight**2).sum())
        perm, boot = np.empty(RESAMPLES), np.empty(RESAMPLES)
        for i in range(RESAMPLES):
            sub = rng.choice(pooled, k, replace=False)
            perm[i] = welch_t(sub.sum(), (sub**2).sum())
            boot[i] = rng.choice(tonight, k).mean() - rng.choice(baseline, m).mean()
        p = float((np.sum(np.abs(perm) >= abs(observed) - 1e-12) + 1) / (RESAMPLES + 1))
        low, high = np.quantile(boot, [alpha / 2, 1 - alpha / 2])
        ci, name = (float(low), float(high)), f"studentized permutation test, {RESAMPLES:,} resamples (two-sided)"
    return TestResult(
        n=len(tonight),
        baseline_n=len(baseline),
        estimate=float(tonight.mean()),
        baseline_estimate=float(baseline.mean()),
        effect=diff,
        ci=ci,
        p_value=p,
        method=name,
        inference_type=inference_type,
        conditioning=conditioning or {},
        alpha=alpha,
    )


def trend(
    values: np.ndarray,
    *,
    alpha: float = DEFAULT_ALPHA,
    inference_type: InferenceType,
    conditioning: dict | None = None,
) -> TestResult:
    """Linear drift across consecutive pitches. estimate = slope per pitch; effect = fitted first-to-last change."""
    x = np.arange(len(values), dtype=float)
    res = stats.linregress(x, values)
    half = stats.t.ppf(1 - alpha / 2, len(values) - 2) * res.stderr
    return TestResult(
        n=len(values),
        baseline_n=None,
        estimate=float(res.slope),
        baseline_estimate=None,
        effect=float(res.slope * (len(values) - 1)),
        ci=(float(res.slope - half), float(res.slope + half)),
        p_value=float(res.pvalue),
        method="linear trend over pitch order (two-sided)",
        inference_type=inference_type,
        conditioning=conditioning or {},
        alpha=alpha,
    )
