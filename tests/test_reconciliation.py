from pitching_agent.analytics.stat_tests import binomial_vs_baseline
from pitching_agent.models import InferenceType, PitcherLine
from pitching_agent.services.reconciliation import evaluate_gate
from pitching_agent.state import StarterState

FULL = PitcherLine(outs=14, pitches=83, strikes=58, hits=5, runs=1, earned_runs=1, walks=1, strikeouts=4)


def test_complete_line_finalizes():
    r = evaluate_gate(FULL, {"mlb_boxscore": FULL}, inherited_runners_on_base=False)
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


def test_boxscore_disagreement_holds_finalization():
    box = PitcherLine(pitches=84, strikes=58)
    r = evaluate_gate(FULL, {"mlb_boxscore": box}, inherited_runners_on_base=False)
    assert r.state is StarterState.RECONCILING
    assert r.conflicts == {"mlb_boxscore": ["pitches"]}


def test_missing_corroboration_does_not_block():
    r = evaluate_gate(FULL, {"mlb_boxscore": None}, inherited_runners_on_base=False)
    assert r.state is StarterState.FINALIZED


def test_binomial_result_shape():
    r = binomial_vs_baseline(11, 13, 0.612, alternative="greater", inference_type=InferenceType.EXPLORATORY)
    assert r.n == 13
    assert round(r.effect, 3) == round(11 / 13 - 0.612, 3)
    assert 0 < r.p_value < 1
    assert r.ci[0] < r.estimate < r.ci[1]


def test_alpha_defaults_to_05_and_sets_ci_width():
    r = binomial_vs_baseline(11, 13, 0.612, inference_type=InferenceType.EXPLORATORY)
    assert r.alpha == 0.05
    assert r.significant is False  # two-sided p = .095
    assert binomial_vs_baseline(12, 13, 0.612, inference_type=InferenceType.EXPLORATORY).significant is True

    strict = binomial_vs_baseline(11, 13, 0.612, alpha=0.01, inference_type=InferenceType.EXPLORATORY)
    assert strict.p_value == r.p_value
    assert strict.ci[0] < r.ci[0] and strict.ci[1] > r.ci[1]  # 99% interval is wider than 95%
