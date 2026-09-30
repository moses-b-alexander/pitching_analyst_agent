from pitching_agent.compositor import capsule, format_hits, format_line, format_mix
from pitching_agent.models import PitcherLine


def test_half_inning_capsule_matches_spec_example():
    line = PitcherLine(pitches=17, strikes=11, runs=1, hits=3, strikeouts=2, walks=1)
    mix = {"4S": 8, "SI": 3, "FC": 2, "CU": 4}
    assert capsule(line, mix, ["S8", "S7", "D9"]) == (
        "Line: 17 P · 11S/6B | 1 R · 3 H | 2 K · 1 BB\n"
        "Mix: 4S 8 (47%) · SI 3 (18%) · FC 2 (12%) · CU 4 (24%)\n"
        "Hits: S8 · S7 · D9"
    )


def test_starter_exit_line_matches_spec_example():
    line = PitcherLine(outs=14, pitches=83, strikes=58, runs=1, earned_runs=1, hits=5, strikeouts=4, walks=1)
    assert format_line(line, include_ip=True) == "Line: 4.2 IP · 83 P · 58S/25B | 1 R/ER · 5 H | 4 K · 1 BB"


def test_starter_exit_line_unearned_runs():
    line = PitcherLine(outs=18, pitches=90, strikes=60, runs=2, earned_runs=1, hits=4, strikeouts=6, walks=2)
    assert "2 R (1 ER)" in format_line(line, include_ip=True)


def test_missing_fields_render_pending_not_guessed():
    assert format_line(PitcherLine(pitches=17, strikes=11)) == "Line: pending"
    assert format_mix(None) == "Mix: exact counts pending"
    assert format_mix({}) == "Mix: exact counts pending"


def test_mix_provisional_and_half_up_rounding():
    # 1/8 = 12.5% must round up, not to even
    assert format_mix({"4S": 7, "CU": 1}, provisional=True) == "Mix: 4S 7 (88%) · CU 1 (13%) [provisional]"


def test_no_hits():
    assert format_hits([]) == "Hits: none"
