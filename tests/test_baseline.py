"""Season baselines: Savant adapter, the metric menu, the test runner, pregame lines, /test in chat."""

import asyncio

import httpx
import numpy as np
import pandas as pd
import pytest
from conftest import GAME, RYAN

from pitching_agent.analytics import metrics, stat_tests
from pitching_agent.analytics.run import run_test
from pitching_agent.models import InferenceType
from pitching_agent.services.chat import Chat
from pitching_agent.services.pregame import Baselines, format_season_mix, format_to_date
from pitching_agent.services.tracker import GameTracker
from pitching_agent.sources import mlb
from pitching_agent.sources.savant import SavantAdapter, SavantUnavailable
from pitching_agent.store import connect, init_db

GAME_DATE = "2026-09-25"

# Per pitch: count to lefties / righties, then share of all pitches. Verified against raw Savant rows.
SEASON_MIX = "Mix (L/R 1314/1024): FF 601/437 (44%) · SI 86/139 (10%) · SL 45/115 (7%) · ST 152/215 (16%) · KC 166/98 (11%) · FS 264/20 (12%)"


@pytest.fixture(scope="module")
def tonight(final_feed):
    pitches, _ = mlb.normalize(final_feed)
    return metrics.tonight_frame(pitches, RYAN)


@pytest.fixture(scope="module")
def baseline(savant_season_ryan):
    s = savant_season_ryan
    return metrics.savant_frame(s[(s.game_date < GAME_DATE) & (s.game_pk != GAME)])


# -- one definition, two sources ---------------------------------------------


def test_every_metric_matches_between_feed_and_savant_for_the_same_game(tonight, savant_season_ryan):
    same_game = metrics.savant_frame(savant_season_ryan[savant_season_ryan.game_pk == GAME])
    assert len(tonight) == len(same_game) == 103
    assert tonight["stand"].tolist() == same_game["stand"].tolist()  # batter side, pitch for pitch
    for pitch in (None, "FF", "ST", "FS", "KC", "SI", "SL"):
        for m in metrics.PROPORTION_METRICS:
            if m == metrics.SEQUENCE_METRIC or (m == "usage_share" and pitch is None):
                continue
            assert metrics.proportion(tonight, m, pitch) == metrics.proportion(same_game, m, pitch), (m, pitch)
        for m in metrics.CONTINUOUS_METRICS:
            a, b = metrics.values(tonight, m, pitch), metrics.values(same_game, m, pitch)
            assert len(a) == len(b), (m, pitch)
            assert np.allclose(a, b, atol=0.11), (m, pitch)  # Savant rounds to 0.01 ft / 0.1 mph


def test_sequence_metric_matches_between_sources_and_raw_savant(tonight, baseline, savant_season_ryan):
    m = metrics.SEQUENCE_METRIC
    same_game = metrics.savant_frame(savant_season_ryan[savant_season_ryan.game_pk == GAME])
    # Expected counts computed independently from the raw Savant rows (previous pitch in the same PA).
    expected = {("SI", "FF"): ((1, 34), (58, 788)), ("ST", "FF"): ((10, 34), (131, 788)), ("FF", "ST"): ((9, 19), (107, 275))}
    for (pitch, previous), (game, season) in expected.items():
        assert metrics.proportion(tonight, m, pitch, previous) == game
        assert metrics.proportion(same_game, m, pitch, previous) == game
        assert metrics.proportion(baseline, m, pitch, previous) == season
    with pytest.raises(ValueError):
        metrics.proportion(tonight, m, "SI", None)


def test_metric_menu_matches_the_prompt_menu():
    from pitching_agent.llm.prompts import METRICS

    computable = set(metrics.PROPORTION_METRICS) | set(metrics.CONTINUOUS_METRICS)
    assert computable | {"none"} == set(METRICS)


# -- stat tests ----------------------------------------------------------------


def test_permutation_and_welch_agree_when_spreads_differ(tonight, baseline):
    a, b = metrics.values(tonight, "release_speed", "FF"), metrics.values(baseline, "release_speed", "FF")
    kw = dict(inference_type=InferenceType.EXPLORATORY)
    perm, welch = stat_tests.mean_shift(a, b, **kw), stat_tests.mean_shift(a, b, method="welch", **kw)
    assert (perm.n, perm.baseline_n) == (43, 1038)
    assert perm.effect == pytest.approx(-0.34, abs=0.02)
    assert welch.p_value == pytest.approx(0.010, abs=0.003)
    assert perm.p_value == pytest.approx(welch.p_value, abs=0.01)  # a raw-difference permutation gives .08 here
    assert perm.ci[0] < perm.effect < perm.ci[1] < 0  # interval and p-value tell the same story
    assert stat_tests.mean_shift(a, b, **kw).p_value == perm.p_value  # seeded: repeatable


def test_trend_and_fisher():
    rising = stat_tests.trend(np.arange(20) * 0.1 + 90, inference_type=InferenceType.EXPLORATORY)
    assert rising.estimate == pytest.approx(0.1) and rising.effect == pytest.approx(1.9) and rising.significant
    flat = stat_tests.fisher_two_window((22, 52), (21, 51), inference_type=InferenceType.PROSPECTIVE)
    assert flat.p_value == pytest.approx(1.0) and flat.significant is False
    assert flat.effect == pytest.approx(21 / 51 - 22 / 52)


# -- runner ----------------------------------------------------------------------


def test_usage_test_report_is_fully_specified(tonight, baseline):
    c = {"test": "proportion_vs_baseline", "pitch_type": "ST", "metric": "usage_share"}
    report = run_test(c, tonight, baseline, boundary_inning=0)
    # 396 season sweepers and 2,443 season pitches include tonight's 29 and 103.
    assert report.result.baseline_estimate == pytest.approx(367 / 2340)
    assert report.text.splitlines() == [
        "Test: ST usage_share, innings 1-6 (prospective)",
        "Tonight: 29/103 (28.2%)",
        "Baseline: 15.7% (n=2340) | Effect: +12.5 pp | 95% CI 19.7% to 37.9%",
        "Season starts (26): 6.4% to 31.3%, median 13.8% | tonight is above 25 of 26",
        "exact binomial (two-sided) | p=.002 | significant at alpha .05",
    ]


def test_sequence_test_report(tonight, baseline):
    c = {"test": "proportion_vs_baseline", "pitch_type": "ST", "metric": "share_after_previous_pitch_type", "previous_pitch_type": "FF"}
    assert run_test(c, tonight, baseline, boundary_inning=0).text.splitlines() == [
        "Test: ST after FF, innings 1-6 (prospective)",
        "Tonight: 10/34 (29.4%)",
        "Baseline: 16.6% (n=788) | Effect: +12.8 pp | 95% CI 15.1% to 47.5%",
        "Season starts (25): 4.0% to 43.8%, median 15.9% | tonight is above 23 of 25",
        "exact binomial (two-sided) | p=.061 | not significant at alpha .05",
    ]


def test_batter_side_condition_compares_like_with_like(tonight, baseline):
    c = {"test": "proportion_vs_baseline", "pitch_type": "FS", "metric": "usage_share", "batter_hand": "L"}
    report = run_test(c, tonight, baseline, boundary_inning=0)
    # raw Savant: 9 splitters in 55 pitches to lefties tonight; 264 in 1,316 before tonight
    assert report.text.splitlines()[:3] == [
        "Test: FS usage_share vs LHB, innings 1-6 (prospective)",
        "Tonight: 9/55 (16.4%)",
        "Baseline: 20.1% (n=1316) | Effect: -3.7 pp | 95% CI 7.8% to 28.8%",
    ]
    both = run_test({**c, "batter_hand": None}, tonight, baseline, boundary_inning=0)
    assert both.text.splitlines()[1] == "Tonight: 9/103 (8.7%)"
    only_righties = tonight[tonight["stand"] == "R"]
    assert run_test(c, only_righties, baseline, boundary_inning=0).text == "No test: he has not faced a LHB yet."


def test_window_is_prospective_only_when_pitches_follow_the_observation(tonight, baseline):
    c = {"test": "proportion_vs_baseline", "pitch_type": "KC", "metric": "share_below_zone"}
    later = run_test(c, tonight, baseline, boundary_inning=3)
    assert later.text.startswith("Test: KC share_below_zone, innings 4-6 (prospective)\nTonight: 4/6 ")
    assert later.result.inference_type is InferenceType.PROSPECTIVE
    whole = run_test(c, tonight, baseline, boundary_inning=6)  # observed after his last inning
    assert whole.text.startswith("Test: KC share_below_zone, innings 1-6 (exploratory)")
    assert whole.result.inference_type is InferenceType.EXPLORATORY


def test_alpha_changes_the_verdict_and_interval(tonight, baseline):
    c = {"test": "mean_shift", "pitch_type": "FF", "metric": "release_speed"}
    assert "| significant at alpha .05" in run_test(c, tonight, baseline, boundary_inning=0).text
    strict = run_test(c, tonight, baseline, boundary_inning=0, alpha=0.001).text
    assert "| not significant at alpha .001" in strict and "99.9% CI" in strict


@pytest.mark.parametrize(
    "c,base,expected",
    [
        ({"test": "none", "pitch_type": None, "metric": "none"}, True, "not checkable with pitch data"),
        ({"test": "proportion_vs_baseline", "pitch_type": "SI", "metric": "share_after_previous_pitch_type"}, True, "a sequence needs both pitches"),
        ({"test": "proportion_vs_baseline", "pitch_type": None, "metric": "usage_share"}, True, "needs a specific pitch type"),
        ({"test": "mean_shift", "pitch_type": "FF", "metric": "release_speed"}, False, "no season baseline is loaded"),
        ({"test": "proportion_vs_baseline", "pitch_type": "CU", "metric": "share_below_zone"}, True, "nothing to count"),
        ({"test": "two_window_proportion", "pitch_type": "FF", "metric": "usage_share"}, True, "no pitches after the observation"),
    ],
)  # fmt: skip
def test_untestable_requests_say_why(tonight, baseline, c, base, expected):
    report = run_test(c, tonight, baseline if base else None, boundary_inning=6)
    assert report.result is None and expected in report.text


def test_trend_needs_no_baseline(tonight):
    report = run_test({"test": "trend", "pitch_type": "FF", "metric": "release_speed"}, tonight, None, boundary_inning=2)
    assert report.text.splitlines()[0] == "Test: FF release_speed, innings 1-6 (exploratory)"
    assert "mph per pitch over 43 pitches" in report.text


# -- Savant adapter ----------------------------------------------------------------


def _savant(tmp_path, handler):
    return SavantAdapter(tmp_path, httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def test_baseline_excludes_tonight_and_caches(tmp_path, savant_season_ryan):
    csv = savant_season_ryan.to_csv(index=False).encode()
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        return httpx.Response(200, content=csv if request.url.params["hfGT"] == "R|" else b"")

    df = asyncio.run(_savant(tmp_path, handler).baseline(RYAN, 2026, before_date=GAME_DATE, exclude_game=GAME))
    assert len(df) == 2340 and GAME not in set(df.game_pk) and df.game_date.max() < GAME_DATE  # only game that day
    assert [p["hfGT"] for p in seen] == ["R|", "PO|"]
    assert seen[0]["hfSea"] == "2026|" and seen[0]["pitchers_lookup[]"] == str(RYAN)
    assert (tmp_path / f"savant_{RYAN}_2026_R.csv.gz").exists()

    def down(request):
        raise httpx.ConnectError("refused")

    again = asyncio.run(_savant(tmp_path, down).baseline(RYAN, 2026, before_date=GAME_DATE, exclude_game=GAME))
    assert len(again) == 2340 and again.attrs["stale"] is True  # served from the cached pull


def test_no_cache_and_no_network_raises(tmp_path):
    def down(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(SavantUnavailable):
        asyncio.run(_savant(tmp_path, down).pitcher_corpus(RYAN, 2026))


# -- pregame + chat ------------------------------------------------------------------


def _game(date, game_id, outs, er, k, bb, postseason=False):
    return {"date": date, "game_id": game_id, "postseason": postseason,
            "stat": {"outs": outs, "earnedRuns": er, "strikeOuts": k, "baseOnBalls": bb}}  # fmt: skip


LOG = [_game("2026-09-14", 1, 21, 1, 9, 1), _game("2026-09-20", 2, 18, 3, 6, 2), _game(GAME_DATE, GAME, 18, 2, 8, 1)]


class FakeMLB:
    async def game_log(self, player_id, season):
        return LOG if player_id == RYAN else []


class FakeSavant:
    def __init__(self, season, fail_for=()):
        self.season, self.fail_for = season, fail_for

    async def baseline(self, pitcher_id, season, *, before_date, exclude_game):
        if pitcher_id in self.fail_for:
            raise SavantUnavailable("down")
        if pitcher_id != RYAN:
            return pd.DataFrame()
        s = self.season
        df = s[(s.game_date <= before_date) & (s.game_pk != exclude_game)].reset_index(drop=True)
        df.attrs["stale"] = False
        return df


def test_running_totals_stop_before_tonight_and_fold_in_postseason(baseline):
    # 39 outs, 4 ER through the two earlier games; tonight's game is never counted
    assert format_to_date(LOG, before_date=GAME_DATE, exclude_game=GAME) == "Season to date: 2 G · 13.0 IP · 2.77 ERA · 15 K · 3 BB"
    october = [*LOG, _game("2026-10-02", 9, 20, 0, 10, 0, postseason=True)]
    assert format_to_date(october, before_date="2026-10-07", exclude_game=77) == (
        "Season to date: 4 G · 25.2 IP · 2.10 ERA · 33 K · 4 BB (incl. 1 postseason G)"
    )
    assert format_to_date([], before_date=GAME_DATE, exclude_game=GAME) == "Season to date: no appearances before tonight"
    assert format_season_mix(baseline) == SEASON_MIX


def test_heart_zone_is_exactly_savants(savant_season_ryan, savant_heart_ryan):
    """Our heart definition against the pitches Savant's own attack-zone filter returns for the season."""
    key = ["game_pk", "at_bat_number", "pitch_number"]
    season = savant_season_ryan.dropna(subset=["plate_x", "plate_z", "sz_top", "sz_bot"])
    savant_says = season.set_index(key).index.isin(savant_heart_ryan.set_index(key).index)
    assert savant_says.sum() == len(savant_heart_ryan) == 657
    for flag in (True, False):  # every Savant-heart pitch is ours, and none of the others are
        subset = metrics.savant_frame(season[savant_says == flag])
        k, n = metrics.proportion(subset, "share_heart_of_zone", None)
        assert (k, n) == ((n, n) if flag else (0, n))


def test_pregame_loads_each_starter_once_and_reports_gaps(final_feed, savant_season_ryan):
    async def run(savant):
        tracker, emitted = GameTracker(), []
        tracker.update(mlb.truncate_feed(final_feed, 0))  # before first pitch: probables
        baselines = Baselines(FakeMLB(), savant, emitted.append)
        baselines.ensure(tracker)
        baselines.ensure(tracker)  # second call must not reload
        await baselines.wait()
        return baselines, {o.text.splitlines()[0]: o.text.splitlines()[1:] for o in emitted}

    baselines, out = asyncio.run(run(FakeSavant(savant_season_ryan)))
    assert len(out) == 2
    assert out["PREGAME Joe Ryan (MIN)"] == [
        "Season to date: 2 G · 13.0 IP · 2.77 ERA · 15 K · 3 BB",
        SEASON_MIX,
    ]
    assert out["PREGAME Jacob deGrom (TEX)"][1] == "No season pitch data before this game; baseline tests unavailable."
    assert list(baselines.frames) == [RYAN]

    _, out = asyncio.run(run(FakeSavant(savant_season_ryan, fail_for=(RYAN,))))
    assert "Savant unreachable" in out["PREGAME Joe Ryan (MIN)"][1]


class Model:
    """Returns a fixed classification, then whatever prose."""

    def __init__(self, classification):
        self.classification = classification
        self.test_prompts = []

    async def chat_json(self, messages, schema):
        return self.classification

    async def chat(self, messages, **kwargs):
        if messages[0]["content"].startswith("You explain a statistical test"):
            self.test_prompts.append(messages[-1]["content"])
            return "The sweeper usage is well above his norm."
        return "Noted."


def test_slash_test_runs_the_named_test_with_real_numbers(final_feed, baseline):
    conn = connect(":memory:")
    init_db(conn)
    tracker = GameTracker()
    tracker.update(mlb.truncate_feed(final_feed, 0))
    model = Model({"primary_class": "usage_proportion", "test": "proportion_vs_baseline", "pitch_type": "ST", "metric": "usage_share"})
    chat = Chat(tracker, conn, model, baselines={RYAN: baseline})

    assert asyncio.run(chat.handle("/test")) == "Nothing to test yet: make an observation first."
    asyncio.run(chat.handle("ryan will lean on the sweeper tonight"))  # before first pitch
    tracker.update(final_feed)

    out = asyncio.run(chat.handle("test it")).splitlines()
    assert out == [
        'Joe Ryan: "ryan will lean on the sweeper tonight"',
        "Test: ST usage_share, innings 1-6 (prospective)",
        "Tonight: 29/103 (28.2%)",
        "Baseline: 15.7% (n=2340) | Effect: +12.5 pp | 95% CI 19.7% to 37.9%",
        "Season starts (26): 6.4% to 31.3%, median 13.8% | tonight is above 25 of 26",
        "exact binomial (two-sided) | p=.002 | significant at alpha .05",
        "The sweeper usage is well above his norm.",
    ]
    assert "Tonight: 29/103 (28.2%)" in model.test_prompts[0]  # the model explains code-computed numbers


def test_slash_test_without_baseline_or_model(final_feed):
    conn = connect(":memory:")
    init_db(conn)
    tracker = GameTracker()
    tracker.update(final_feed)
    chat = Chat(tracker, conn, Model({"primary_class": "fatigue_trend", "test": "mean_shift", "pitch_type": "FF", "metric": "release_speed"}))
    asyncio.run(chat.handle("ryan's heater looks slow"))
    assert asyncio.run(chat.handle("/test")).splitlines()[1] == "No test: no season baseline is loaded for him."


def test_boundary_is_fixed_when_the_viewer_speaks_not_when_the_model_answers(final_feed, baseline):
    """The game advances while a slow model call is awaited; the test window must not move with it."""
    conn = connect(":memory:")
    init_db(conn)
    tracker = GameTracker()
    tracker.update(mlb.truncate_feed(final_feed, 23))  # Ryan has pitched innings 1-2

    class SlowModel(Model):
        async def chat_json(self, messages, schema):
            tracker.update(final_feed)  # the whole game goes by during the call
            return self.classification

    model = SlowModel({"primary_class": "usage_proportion", "test": "proportion_vs_baseline", "pitch_type": "ST", "metric": "usage_share"})
    chat = Chat(tracker, conn, model, baselines={RYAN: baseline})
    said = asyncio.run(chat.handle("ryan is throwing a ton of sweepers"))
    assert "Exploratory through innings 1-2; prospective window starts with his inning 3." in said
    tested = asyncio.run(chat.handle("/test")).splitlines()
    assert tested[1] == "Test: ST usage_share, innings 3-6 (prospective)"
    assert tested[2] == "Tonight: 16/63 (25.4%)"


# -- velocity line and per-pitch table -------------------------------------------------


def test_velo_line_shows_difference_from_season(final_feed, baseline):
    tracker = GameTracker()
    tracker.baselines = {RYAN: baseline}
    tracker.update(final_feed)
    ryan = tracker.starters["home"]
    # raw Savant means: game FF 93.13 / season 93.48, SL 85.59 / 86.33, FS 88.41 / 87.88
    assert tracker.starter_capsule(ryan).splitlines()[2] == (
        "Velo: FF 93.1 (-0.3) · SI 93.1 (-0.1) · SL 85.6 (-0.7) · ST 79.5 (-0.9) · KC 79.2 (+0.1) · FS 88.4 (+0.5)"
    )
    degrom = tracker.starters["away"]  # no baseline loaded for him: plain averages, no comparison
    assert tracker.starter_capsule(degrom).splitlines()[2] == "Velo: FF 97.5 · SI 96.8 · SL 92.9 · CU 83.7 · CH 90.7"


def test_pitch_table_has_real_numbers_for_the_model(tonight, baseline):
    rows = metrics.pitch_table(tonight, baseline)
    assert rows[0] == (
        "FF: 43 thrown | velo 93.1 mph (season 93.5) | vert break 14.4 in (season 13.5) | horiz break -14.0 in (season -13.3)"
        " | spin 2291 rpm (season 2288) | in zone 27/43 (season 56%) | heart 15/43 (season 32%) | below zone 1/43 (season 2%)"
        " | whiffs 3/17 swings (season 21%)"
    )
    assert [r.split(":")[0] for r in rows[:6]] == ["FF", "SI", "SL", "ST", "KC", "FS"]
    assert rows[-1] == "FF velo by inning: I1 93.7 | I2 92.7 | I3 93.2 | I4 93.2 | I5 93.0 | I6 92.8"
    plain = metrics.pitch_table(tonight)  # without a baseline: same rows, no season figures
    assert plain[0].startswith("FF: 43 thrown | velo 93.1 mph | vert break 14.4 in") and "season" not in plain[0]
    assert metrics.pitch_table(tonight.iloc[0:0]) == []


def test_detail_command_and_model_context(final_feed, baseline):
    conn = connect(":memory:")
    init_db(conn)
    tracker = GameTracker()
    tracker.update(final_feed)
    model = Model({"primary_class": "fatigue_trend", "test": "trend", "pitch_type": "FF", "metric": "release_speed"})
    seen = []

    async def chat_capture(messages, **kwargs):
        seen.append(messages)
        return "Noted."

    model.chat = chat_capture
    chat = Chat(tracker, conn, model, baselines={RYAN: baseline})

    detail = asyncio.run(chat.handle("/detail"))
    assert "RYAN (MIN) by pitch, season in parentheses\nFF: 43 thrown | velo 93.1 mph (season 93.5)" in detail
    assert "DEGROM (TEX) by pitch (no season baseline loaded)\nFF: 40 thrown | velo 97.5 mph |" in detail

    asyncio.run(chat.handle("ryan's velo looks cooked"))
    system, user = seen[0][0]["content"], seen[0][1]["content"]
    assert "By pitch:\nFF: 43 thrown | velo 93.1 mph (season 93.5)" in user  # the velocity it used to invent
    assert "FF velo by inning: I1 93.7" in user
    assert "to left-handed batters" in system and "never invent a number" in system
