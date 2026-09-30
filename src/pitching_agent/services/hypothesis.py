"""Hypothesis ledger: exploratory vs prospective bookkeeping (architecture §8, SKILL.md §5).

The question is whether data generated the hypothesis or arrived after it was frozen,
not which inning or how many pitches.
"""

from __future__ import annotations

from pitching_agent.analytics.windows import InningWindow
from pitching_agent.models import InferenceType


def inference_type(generated: InningWindow, tested: InningWindow, *, frozen_before_test: bool) -> InferenceType:
    """Prospective only if the hypothesis was frozen before `tested` began and the windows don't overlap."""
    if frozen_before_test and generated.precedes(tested):
        return InferenceType.PROSPECTIVE
    return InferenceType.EXPLORATORY
