import pytest

from pitching_agent.state import InvalidTransition, StarterState, transition


def test_happy_path_to_finalized():
    s = StarterState.ACTIVE
    for nxt in (StarterState.EXIT_CANDIDATE, StarterState.RECONCILING, StarterState.FINALIZED):
        s = transition(s, nxt)
    assert s is StarterState.FINALIZED


def test_inherited_runner_path():
    s = transition(StarterState.RECONCILING, StarterState.AWAITING_INHERITED)
    assert transition(s, StarterState.FINALIZED) is StarterState.FINALIZED


def test_cannot_skip_reconciliation_or_leave_finalized():
    with pytest.raises(InvalidTransition):
        transition(StarterState.ACTIVE, StarterState.FINALIZED)
    with pytest.raises(InvalidTransition):
        transition(StarterState.FINALIZED, StarterState.ACTIVE)
