"""V1 statistical tests (architecture §8). Every function returns a TestResult.

Named stat_tests (not tests.py as in the architecture doc) to avoid confusion with the test suite.
Tests execute only on explicit user request (decisions.md #3).
"""

from __future__ import annotations

from typing import Literal

from scipy import stats

from pitching_agent.models import InferenceType, TestResult

Alternative = Literal["two-sided", "greater", "less"]

DEFAULT_ALPHA = 0.05


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


# TODO: fisher_exact, diff_in_proportions, bootstrap_ci, permutation_test, within_outing_trend
