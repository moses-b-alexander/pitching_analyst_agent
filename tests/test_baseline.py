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
from pitching_agent.services.pregame import Baselines, format_season, format_season_mix
from pitching_agent.services.tracker import GameTracker
from pitching_agent.sources import mlb
from pitching_agent.sources.savant import SavantAdapter, SavantUnavailable
from pitching_agent.store import connect, init_db

GAME_DATE = "2026-09-25"


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
    for pitch in (None, "FF", "ST", "FS", "KC", "SI", "SL"):
        for m in metrics.PROPORTION_METRICS:
            if m == "usage_share" and pitch is None:
                continue
            assert metrics.proportion(tonight, m, pitch) == metrics.proportion(same_game, m, pitch), (m, pitch)
        for m in metrics.CONTINUOUS_METRICS:
            a, b = metrics.values(tonight, m, pitch), metrics.values(same_game, m, pitch)
            assert len(a) == len(b), (m, pitch)
            assert np.allclose(a, b, atol=0.11), (m, pitch)  # Savant rounds to 0.01 ft / 0.1 mph


def test_metric_menu_matches_the_prompt_menu():
    from pitching_agent.llm.prompts import METRICS

    computable = set(metrics.PROPORTION_METRICS) | set(metrics.CONTINUOUS_METRICS)
    assert computable | {"share_after_previous_pitch_type", "none"} == set(METRICS)


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
        ({"test": "proportion_vs_baseline", "pitch_type": "SI", "metric": "share_after_previous_pitch_type"}, True, "not computable yet"),
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
    assert len(df) == 2340 and GAME not in set(df.game_pk) and df.game_date.max() < GAME_DATE
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


class FakeMLB:
    async def season_stats(self, player_id, season, game_type="R"):
        if game_type == "P":
            return None
        return {"inningsPitched": "144.2", "era": "3.79", "strikeOuts": 159, "baseOnBalls": 31}


class FakeSavant:
    def __init__(self, season, fail_for=()):
        self.season, self.fail_for = season, fail_for

    async def baseline(self, pitcher_id, season, *, before_date, exclude_game):
        if pitcher_id in self.fail_for:
            raise SavantUnavailable("down")
        if pitcher_id != RYAN:
            return pd.DataFrame()
        s = self.season
        df = s[(s.game_date < before_date) & (s.game_pk != exclude_game)].reset_index(drop=True)
        df.attrs["stale"] = False
        return df


def test_formatters(baseline):
    assert format_season({"inningsPitched": "144.2", "era": "3.79", "strikeOuts": 159, "baseOnBalls": 31}) == "144.2 IP · 3.79 ERA · 159 K · 31 BB"
    assert format_season(None) == "none"
    assert format_season_mix(baseline) == "Mix: FF 44% · SI 10% · SL 7% · ST 16% · KC 11% · FS 12% (2,338 pitches)"


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
        "Season: 144.2 IP · 3.79 ERA · 159 K · 31 BB | Postseason: none",
        "Mix: FF 44% · SI 10% · SL 7% · ST 16% · KC 11% · FS 12% (2,338 pitches)",
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
