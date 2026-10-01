import copy

import pytest
from conftest import DEGROM, GAME, RYAN

from pitching_agent.analytics.lines import window_hits, window_line, window_mix
from pitching_agent.analytics.windows import InningWindow
from pitching_agent.compositor import capsule
from pitching_agent.sources import mlb


@pytest.fixture(scope="module")
def normalized(final_feed):
    return mlb.normalize(final_feed)


def test_game_info(final_feed):
    info = mlb.game_info(final_feed)
    assert (info.game_id, info.date, info.away.abbrev, info.home.abbrev) == (GAME, "2026-09-25", "TEX", "MIN")
    assert info.status == "Final"
    assert (info.probable_away, info.probable_home) == (DEGROM, RYAN)
    assert mlb.actual_starters(final_feed) == {"away": DEGROM, "home": RYAN}


def test_matches_savant_pitch_by_pitch(normalized, savant_ryan):
    pitches, _ = normalized
    ours = {(p.at_bat_number, p.pitch_number): p for p in pitches if p.pitcher_id == RYAN}
    assert len(ours) == len(savant_ryan) == 103
    for r in savant_ryan.itertuples():
        p = ours[(r.at_bat_number, r.pitch_number)]
        assert p.pitch_type == r.pitch_type
        assert (p.balls, p.strikes) == (r.balls, r.strikes)  # pre-pitch count
        assert p.release_speed == pytest.approx(r.release_speed, abs=0.05)
        # Savant rounds pfx/release to 0.01 ft
        for field in ("pfx_x", "pfx_z", "release_pos_x", "release_pos_z"):
            assert getattr(p, field) == pytest.approx(getattr(r, field), abs=0.006), field
        for field in ("plate_x", "plate_z"):
            assert getattr(p, field) == pytest.approx(getattr(r, field), abs=1e-4), field


@pytest.mark.parametrize("side", ["away", "home"])
def test_every_pitcher_line_matches_boxscore(normalized, boxscore, final_feed, side):
    pitches, pas = normalized
    for pid in final_feed["liveData"]["boxscore"]["teams"][side]["pitchers"]:
        assert window_line(pitches, pas, pid) == mlb.box_line(boxscore, pid), pid


def test_half_inning_capsule_golden(normalized):
    # Expected values cross-checked against linescore (2 R, 2 H in T1) and Savant
    # (28 pitches, 19 strikes, mix FF11/ST9/FS4/KC2/SI1/SL1; two HBP, no K/BB).
    pitches, pas = normalized
    i1 = InningWindow(1, 1)
    out = capsule(window_line(pitches, pas, RYAN, i1), window_mix(pitches, RYAN, i1), window_hits(pas, RYAN, i1))
    assert out == (
        "Line: 28 P · 19S/9B | 2 R · 2 H | 0 K · 0 BB\n"
        "Mix: FF 11 (39%) · SI 1 (4%) · SL 1 (4%) · ST 9 (32%) · KC 2 (7%) · FS 4 (14%)\n"
        "Hits: D8 · S9"
    )


def test_starter_exit_capsule_golden(normalized):
    pitches, pas = normalized
    out = capsule(
        window_line(pitches, pas, DEGROM), window_mix(pitches, DEGROM), window_hits(pas, DEGROM), include_ip=True
    )
    # Matches the official box: 4.0 IP, 89 P, 58 S, 31 B, 8 R, 8 ER, 8 H, 5 K, 3 BB
    assert out.splitlines()[0] == "Line: 4.0 IP · 89 P · 58S/31B | 8 R/ER · 8 H | 5 K · 3 BB"
    assert out.splitlines()[2] == "Hits: S7 · S7 · S8 · S1 · T9 · S9 · D8 · S9"


def test_mid_game_snapshot(mid_feed, boxscore):
    pitches, pas = mlb.normalize(mid_feed)
    assert pas[-1].is_complete is False and pas[-1].event_type is None
    assert mlb.game_info(mid_feed).status == "Live"
    # deGrom had already exited: his line is final in the mid-game snapshot
    assert window_line(pitches, pas, DEGROM) == mlb.box_line(boxscore, DEGROM)


def test_unclassified_pitch_makes_mix_pending(normalized):
    pitches, _ = normalized
    pitches = copy.deepcopy(pitches)
    next(p for p in pitches if p.pitcher_id == RYAN).pitch_type = None
    assert window_mix(pitches, RYAN) is None
