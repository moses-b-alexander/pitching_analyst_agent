from pitching_agent.analytics.stat_tests import binomial_vs_baseline
from pitching_agent.models import InferenceType, PitcherLine
from pitching_agent.services.reconciliation import evaluate_gate
from pitching_agent.state import StarterState

FULL = PitcherLine(outs=14, pitches=83, strikes=58, hits=5, runs=1, earned_runs=1, walks=1, strikeouts=4)


def test_complete_line_finalizes():
    r = evaluate_gate(FULL, {"espn": FULL}, inherited_runners_on_base=False)
    assert r.state is StarterState.FINALIZED
    assert r.conflicts == {}


def test_missing_core_field_keeps_reconciling():
    partial = PitcherLine(outs=14, pitches=83, strikes=58, hits=5, runs=1, walks=1, strikeouts=4)
    r = evaluate_gate(partial, {}, inherited_runners_on_base=False)
    assert r.state is StarterState.RECONCILING
    assert r.missing == ["earned_runs"]
    assert r.status_line == "Starter exit detected; final line not yet source-complete."


def test_inherited_runners_hold_finalization():
    r = evaluate_gate(FULL, {}, inherited_runners_on_base=True)
    assert r.state is StarterState.AWAITING_INHERITED


def test_secondary_disagreement_reported_but_primary_wins():
    espn = PitcherLine(pitches=84, strikes=58)
    r = evaluate_gate(FULL, {"espn": espn, "mlb_stats": None}, inherited_runners_on_base=False)
    assert r.state is StarterState.FINALIZED
    assert r.conflicts == {"espn": ["pitches"]}


def test_binomial_result_shape():
    r = binomial_vs_baseline(11, 13, 0.612, alternative="greater", inference_type=InferenceType.EXPLORATORY)
    assert r.n == 13
    assert round(r.effect, 3) == round(11 / 13 - 0.612, 3)
    assert 0 < r.p_value < 1
    assert r.ci[0] < r.estimate < r.ci[1]
