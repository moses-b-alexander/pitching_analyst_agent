import asyncio
import copy

import httpx
import pytest
from conftest import DEGROM, GAME, RYAN

from pitching_agent.services.live import ReplaySource, run_live
from pitching_agent.services.tracker import GameTracker
from pitching_agent.sources.mlb import truncate_feed
from pitching_agent.state import StarterState

DEGROM_FINAL = (
    "DEGROM FINAL\n"
    "Line: 4.0 IP · 89 P · 58S/31B | 8 R/ER · 8 H | 5 K · 3 BB\n"
    "Mix: FF 40 (45%) · SI 10 (11%) · SL 17 (19%) · CU 9 (10%) · CH 13 (15%)\n"
    "Hits: S7 · S7 · S8 · S1 · T9 · S9 · D8 · S9"
)


def replay(feed, **tracker_kwargs):
    """Step the tracker through the game one play at a time. Returns [(plays_seen, Output)]."""
    tracker = GameTracker(**tracker_kwargs)
    total = len(feed["liveData"]["plays"]["allPlays"])
    seen = []
    for n in range(total + 1):
        seen.extend((n, o) for o in tracker.update(truncate_feed(feed, n)))
    return tracker, seen


def headlines(seen):
    return [(n, o.kind, o.text.splitlines()[0]) for n, o in seen]


def test_full_game_sequence_with_half_inning_lag(final_feed):
    tracker, seen = replay(final_feed)
    # T1 is plays 0-6, B1 plays 7-9, T2 plays 10-12: each capsule prints one half-inning late.
    assert headlines(seen) == [
        (0, "status", "Connected: TEX @ MIN 2026-09-25 | Pre-Game. Waiting for first pitch."),
        (10, "capsule", "RYAN T1"),
        (13, "capsule", "DEGROM B1"),
        (23, "capsule", "RYAN T2"),
        (26, "capsule", "DEGROM B2"),
        (29, "capsule", "RYAN T3"),
        (32, "capsule", "DEGROM B3"),
        (39, "capsule", "RYAN T4"),
        (44, "capsule", "DEGROM B4"),
        (45, "exit_final", "DEGROM FINAL"),
        (47, "capsule", "RYAN T5"),
        (57, "capsule", "RYAN T6"),
        (58, "exit_final", "RYAN FINAL"),
    ]
    by_headline = {o.text.splitlines()[0]: o.text for _, o in seen}
    assert by_headline["RYAN T1"] == (
        "RYAN T1\n"
        "Line: 28 P · 19S/9B | 2 R · 2 H | 0 K · 0 BB\n"
        "Mix: FF 11 (39%) · SI 1 (4%) · SL 1 (4%) · ST 9 (32%) · KC 2 (7%) · FS 4 (14%)\n"
        "Hits: D8 · S9"
    )
    assert by_headline["DEGROM FINAL"] == DEGROM_FINAL
    assert tracker.done
    assert {s.pitcher_id: s.state for s in tracker.starters.values()} == {
        RYAN: StarterState.FINALIZED,
        DEGROM: StarterState.FINALIZED,
    }


def test_lag_zero_prints_at_the_break(final_feed):
    _, seen = replay(final_feed, lag=0)
    assert headlines(seen)[1:3] == [(7, "capsule", "RYAN T1"), (10, "capsule", "DEGROM B1")]


def test_silent_mode_still_reports_exits(final_feed):
    _, seen = replay(final_feed, capsules=False)
    assert [k for _, k, _ in headlines(seen)] == ["status", "exit_final", "exit_final"]


def test_joining_mid_game_catches_up_without_backlog(mid_feed, final_feed):
    tracker = GameTracker()
    first = tracker.update(mid_feed)
    # deGrom already out (verified against the real boxscore); Ryan still active.
    assert [o.kind for o in first] == ["status", "exit_final"]
    assert "RYAN (MIN) so far" in first[0].text and "DEGROM" not in first[0].text
    assert first[1].text == DEGROM_FINAL

    later = tracker.update(final_feed)
    assert [o.text.splitlines()[0] for o in later] == ["RYAN T5", "RYAN T6", "RYAN FINAL"]


def test_boxscore_disagreement_holds_the_final_line(mid_feed):
    bad = copy.deepcopy(mid_feed)
    bad["liveData"]["boxscore"]["teams"]["away"]["players"][f"ID{DEGROM}"]["stats"]["pitching"]["numberOfPitches"] = 88
    tracker = GameTracker()
    out = tracker.update(bad)
    assert out[-1].kind == "exit_detected"
    assert out[-1].text == "DEGROM: Starter exit detected; final line not yet source-complete."
    assert tracker.starters["away"].state is StarterState.RECONCILING

    assert tracker.update(bad) == []  # still waiting; says nothing new
    assert [o.text for o in tracker.update(mid_feed)] == [DEGROM_FINAL]  # box caught up


def test_give_up_prints_labelled_line(mid_feed):
    bad = copy.deepcopy(mid_feed)
    bad["liveData"]["boxscore"]["teams"]["away"]["players"][f"ID{DEGROM}"]["stats"]["pitching"]["hits"] = 9
    tracker = GameTracker()
    tracker.update(bad)
    out = tracker.give_up()
    assert out[0].text.splitlines()[0] == "DEGROM FINAL (not source-complete)"
    assert tracker.starters["away"].state is StarterState.UNRESOLVED


def test_mid_inning_exit_waits_for_inherited_runners(final_feed):
    # Synthetic: pull Ryan after 4 batters of the 7-batter first inning, runners aboard.
    feed = copy.deepcopy(final_feed)
    for play in feed["liveData"]["plays"]["allPlays"][4:7]:
        play["matchup"]["pitcher"] = {"id": 999, "fullName": "Relief Guy"}
    tracker = GameTracker()
    tracker.update(truncate_feed(feed, 0))

    out = tracker.update(truncate_feed(feed, 5))
    assert [o.text for o in out] == ["RYAN: Starter exit detected; R/ER pending inherited runners."]
    assert tracker.starters["home"].state is StarterState.AWAITING_INHERITED
    assert tracker.update(truncate_feed(feed, 6)) == []

    out = tracker.update(truncate_feed(feed, 7))  # inning over: both inherited runners scored
    final = next(o for o in out if o.kind == "exit_final")
    assert final.text.splitlines()[1].startswith("Line: 0.1 IP")
    assert "| 2 R/ER ·" in final.text.splitlines()[1]


# -- polling loop -----------------------------------------------------------


class Script:
    """Feed source that plays back a list of feeds or exceptions, repeating the last."""

    def __init__(self, items):
        self.items = list(items)
        self.calls = 0

    async def live_feed(self, game_id):
        item = self.items[min(self.calls, len(self.items) - 1)]
        self.calls += 1
        if isinstance(item, Exception):
            raise item
        return item


def run(source, tracker, **kwargs):
    emitted, sleeps = [], []

    async def sleep(seconds):
        sleeps.append(seconds)

    asyncio.run(run_live(source, GAME, tracker, emitted.append, sleep=sleep, **kwargs))
    return emitted, sleeps


def test_loop_replays_whole_game_offline(final_feed):
    emitted, _ = run(ReplaySource(final_feed), GameTracker(), interval=0)
    assert [o.text.splitlines()[0] for o in emitted][-1] == "RYAN FINAL"
    assert sum(o.kind == "capsule" for o in emitted) == 10


def test_loop_backs_off_on_failure_and_still_prints_due_capsule(final_feed):
    down = httpx.ConnectError("refused")
    source = Script([truncate_feed(final_feed, 0), truncate_feed(final_feed, 7), down, down, down, final_feed])
    emitted, sleeps = run(source, GameTracker(), interval=15)
    texts = [o.text.splitlines()[0] for o in emitted]
    assert texts.count("Feed unavailable (ConnectError); retrying.") == 1  # announced once, not per retry
    assert texts.count("Feed back.") == 1
    assert texts.index("Feed back.") < texts.index("RYAN T1")  # nothing skipped while the feed was down
    assert sleeps == [60, 15, 15, 30, 60]  # pregame, live, then doubling backoff


def test_loop_gives_up_on_unreconciled_final(final_feed):
    bad = copy.deepcopy(final_feed)
    bad["liveData"]["boxscore"]["teams"]["home"]["players"][f"ID{RYAN}"]["stats"]["pitching"]["strikeOuts"] = 9
    now = [0.0]

    emitted, sleeps = [], []

    async def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    asyncio.run(
        run_live(Script([bad]), GAME, GameTracker(), emitted.append, sleep=sleep, clock=lambda: now[0],
                 reconcile_interval=600, give_up_after=7200)
    )  # fmt: skip
    assert sleeps == [600] * 12  # rechecks every 10 min for 2 h
    assert emitted[-1].text.splitlines()[0] == "RYAN FINAL (not source-complete)"
    assert DEGROM_FINAL in [o.text for o in emitted]  # the other starter reconciled normally


def test_malformed_payload_is_treated_as_outage(final_feed):
    emitted, _ = run(Script([{"gamePk": GAME}, final_feed]), GameTracker(), interval=15)
    assert emitted[0].text == "Feed unavailable (KeyError); retrying."
    assert emitted[-1].kind == "exit_final"


@pytest.mark.parametrize("n", [0, 1, 30, 73])
def test_truncate_feed_never_mutates_source(final_feed, n):
    before = len(final_feed["liveData"]["plays"]["allPlays"])
    truncate_feed(final_feed, n)
    assert len(final_feed["liveData"]["plays"]["allPlays"]) == before
    assert final_feed["gameData"]["status"]["abstractGameState"] == "Final"
