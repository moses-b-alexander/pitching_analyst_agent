import pytest

from pitching_agent.config import ModelSpec
from pitching_agent.state import InvalidTransition, StarterState, transition
from pitching_agent.store import connect, init_db


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


def test_schema_initializes():
    conn = connect(":memory:")
    init_db(conn)
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"games", "pitches", "observations", "hypotheses", "session_starters", "preferences"} <= tables
    init_db(conn)  # idempotent


def test_model_spec_parse():
    assert str(ModelSpec.parse("anthropic:claude-sonnet-5-5")) == "anthropic:claude-sonnet-5-5"
    assert ModelSpec.parse("deterministic").model is None
    for bad in ("sonnet", "anthropic:", ":x"):
        with pytest.raises(ValueError):
            ModelSpec.parse(bad)
