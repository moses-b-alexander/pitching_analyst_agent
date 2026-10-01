import asyncio

import pytest
from conftest import DEGROM, GAME, RYAN

from pitching_agent.llm.client import LLMUnavailable
from pitching_agent.services.chat import Chat
from pitching_agent.services.tracker import GameTracker
from pitching_agent.sources.mlb import truncate_feed
from pitching_agent.store import connect, init_db, observations


class FakeModel:
    def __init__(self, fail=False):
        self.fail = fail
        self.prompts = []

    async def chat_json(self, messages, schema):
        if self.fail:
            raise LLMUnavailable("down")
        return {"primary_class": "location_spatial", "test": "proportion_vs_baseline", "pitch_type": "ST", "metric": "share_below_zone"}

    async def chat(self, messages, **kwargs):
        self.prompts.append(messages[-1]["content"])
        return "Sweeper usage is 28% tonight."


@pytest.fixture
def conn():
    c = connect(":memory:")
    init_db(c)
    return c


def make(feed, conn, model=None):
    tracker = GameTracker()
    tracker.update(feed)
    return Chat(tracker, conn, model)


def say(chat, text):
    return asyncio.run(chat.handle(text))


def test_named_player_is_saved_classified_and_answered(mid_feed, conn):
    model = FakeModel()
    out = say(make(mid_feed, conn, model), "ryan's sweeper looks buried tonight")
    assert out.splitlines() == [
        "OBS saved: Joe Ryan (MIN)",
        "Class: location_spatial | Test: proportion_vs_baseline (ST, share_below_zone)",
        "Exploratory through innings 1-5; prospective window starts with his inning 6.",
        "Sweeper usage is 28% tonight.",
    ]
    (obs,) = observations(conn, pitcher_id=RYAN)
    assert (obs.game_id, obs.team, obs.inning, obs.half) == (GAME, "MIN", 5, "bottom")
    assert obs.raw_text == "ryan's sweeper looks buried tonight"
    # the reply prompt carries his real line, computed in code
    assert "Line: 5.0 IP" in model.prompts[0] and "Viewer now says: ryan's sweeper" in model.prompts[0]


@pytest.mark.parametrize("text", ["twins guy is nibbling", "MIN starter is nibbling", "Minnesota's starter is nibbling"])
def test_team_resolves_to_its_starter(mid_feed, conn, text):
    assert say(make(mid_feed, conn), text).startswith("OBS saved: Joe Ryan (MIN)")
    assert observations(conn, team="MIN")[0].pitcher_id == RYAN


def test_unnamed_observation_asks_then_accepts_just_a_name(mid_feed, conn):
    chat = make(mid_feed, conn)
    assert say(chat, "his curve looks way lower") == "Which starter is that about: Jacob deGrom (TEX) or Joe Ryan (MIN)?"
    assert observations(conn) == []  # nothing saved on a guess
    assert say(chat, "degrom").startswith("OBS saved: Jacob deGrom (TEX)")
    (obs,) = observations(conn)
    assert (obs.pitcher_id, obs.raw_text) == (DEGROM, "his curve looks way lower")


def test_naming_both_starters_asks(mid_feed, conn):
    out = say(make(mid_feed, conn), "ryan has better stuff than degrom")
    assert out.startswith("Which starter is that about")


def test_exited_starter_is_exploratory_only(mid_feed, conn):
    out = say(make(mid_feed, conn), "degrom had nothing tonight")
    assert "He has exited: any test of this on tonight's data is exploratory." in out


def test_before_first_pitch_uses_probables_and_is_prospective(final_feed, conn):
    out = say(make(truncate_feed(final_feed, 0), conn), "watch ryan's splitter usage")
    assert out.splitlines() == [
        "OBS saved: Joe Ryan (MIN)",
        "Noted before his first pitch: everything he throws tonight is prospective.",
    ]


def test_model_down_still_saves(mid_feed, conn):
    out = say(make(mid_feed, conn, FakeModel(fail=True)), "ryan looks sharp")
    assert out.splitlines()[0] == "OBS saved: Joe Ryan (MIN)"
    assert "model unavailable, saved without analysis" in out
    assert len(observations(conn)) == 1


def test_earlier_observations_are_given_to_the_model(mid_feed, conn):
    model = FakeModel()
    chat = make(mid_feed, conn, model)
    say(chat, "ryan's sweeper looks sharp")
    say(chat, "ryan keeps doubling up on it")
    assert "Earlier viewer observations: ryan's sweeper looks sharp" in model.prompts[1]
    assert "Earlier viewer observations" not in model.prompts[0]


def test_commands(mid_feed, conn):
    chat = make(mid_feed, conn)
    assert say(chat, "/obs") == "No observations saved for this game."
    say(chat, "ryan looks sharp")
    assert say(chat, "/obs") == "Joe Ryan (MIN) B5: ryan looks sharp"
    status = say(chat, "/status")
    assert "RYAN (MIN)\nLine: 5.0 IP" in status and "DEGROM (TEX)\nLine: 4.0 IP" in status
    assert say(chat, "/clear") == "Cleared 1 observations for this game."
    assert observations(conn) == []
