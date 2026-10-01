"""Typed input during a game: attribute it to a starter, save it, classify it, reply.

Attribution (decisions.md #2): the viewer names the player or team. If a message names
neither starter, or both, ask rather than guess; the next message can be just the name.
The model is optional: without it the observation is still saved.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any, Protocol

import pandas as pd

from pitching_agent.analytics import metrics
from pitching_agent.analytics.run import run_test
from pitching_agent.analytics.stat_tests import DEFAULT_ALPHA, MeanMethod
from pitching_agent.llm.client import LLMUnavailable
from pitching_agent.llm.prompts import CLASSIFY_SCHEMA, CLASSIFY_SYSTEM, PITCH_CODES
from pitching_agent.services.tracker import GameTracker, StarterTrack
from pitching_agent.store import add_observation, clear_game, observations, touch_game

REPLY_SYSTEM = (
    "You are a pitching analyst sitting next to a viewer watching a live MLB game. "
    "Reply in at most three short sentences. Use only the numbers provided; never invent a number. " + PITCH_CODES
)

TEST_SYSTEM = (
    "You explain a statistical test result to a baseball viewer in one or two plain sentences. "
    "Say whether the data support what the viewer saw, and mention the sample size if it is small. "
    "Use only the numbers provided; never invent a number. " + PITCH_CODES
)

TEST_REQUESTS = {"/test", "test it", "test that", "run it", "run the test"}

# Team-name words too generic to identify a team on their own.
_GENERIC = {"new", "los", "san", "st", "city", "bay", "red", "white", "blue", "the"}


class ChatModel(Protocol):
    async def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str: ...

    async def chat_json(self, messages: list[dict[str, str]], schema: dict[str, Any]) -> dict[str, Any]: ...


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _keys(s: StarterTrack) -> set[str]:
    """Words that identify this starter: last name, team abbreviation, team name words."""
    return ({_tokens(s.name)[-1], s.team.lower()} | set(_tokens(s.team_name))) - _GENERIC


class Chat:
    def __init__(
        self,
        tracker: GameTracker,
        conn: sqlite3.Connection,
        llm: ChatModel | None,
        *,
        baselines: dict[int, pd.DataFrame] | None = None,
        alpha: float = DEFAULT_ALPHA,
        mean_method: MeanMethod = "permutation",
    ) -> None:
        self.tracker = tracker
        self.conn = conn
        self.llm = llm
        self.baselines = baselines if baselines is not None else {}  # pitcher id -> season metrics frame
        self.alpha = alpha
        self.mean_method = mean_method
        self._pending: str | None = None  # an observation waiting for the viewer to say who it is about
        self._last: dict[str, Any] | None = None  # most recent classified observation, for /test

    def _named(self, text: str) -> list[StarterTrack]:
        words = set(_tokens(text))
        return [s for s in self.tracker.candidates() if words & _keys(s)]

    async def handle(self, text: str) -> str:
        text = text.strip()
        if not text:
            return ""
        info = self.tracker.info
        if info is None:
            return "Not connected to a game yet."

        command = text.lower()
        if command == "/status":
            return self._status()
        if command == "/obs":
            return self._list()
        if command == "/clear":
            self._last = None
            return f"Cleared {clear_game(self.conn, info.game_id)} observations for this game."
        if command in TEST_REQUESTS:
            return await self._test()

        candidates = self.tracker.candidates()
        if not candidates:
            return "No starters known for this game yet."
        named = self._named(text)

        if self._pending is not None and len(named) == 1 and len(_tokens(text)) <= 3:
            text, self._pending = self._pending, None  # the reply was just the name
        elif len(named) != 1:
            self._pending = text
            options = " or ".join(f"{s.name} ({s.team})" for s in candidates)
            return f"Which starter is that about: {options}?"
        else:
            self._pending = None

        return await self._observe(named[0], text)

    async def _observe(self, s: StarterTrack, text: str) -> str:
        info = self.tracker.info
        touch_game(self.conn, info.game_id, info.date, is_final=info.status == "Final")
        earlier = observations(self.conn, game_id=info.game_id, pitcher_id=s.pitcher_id)
        add_observation(
            self.conn,
            game_id=info.game_id,
            team=s.team,
            pitcher_id=s.pitcher_id,
            pitcher_name=s.name,
            inning=info.inning,
            half=info.half.value if info.half else None,
            raw_text=text,
        )
        # Everything about "now" is fixed here, before any model call: the game keeps
        # advancing while the model is awaited, and the boundary must be when the viewer spoke.
        boundary = self.tracker.innings_pitched_in(s)
        lines = [f"OBS saved: {s.name} ({s.team})", self._boundary(s, boundary)]
        if self.llm is None:
            return "\n".join(lines)

        capsule_now = self.tracker.starter_capsule(s)
        try:
            c = await self.llm.chat_json(
                [{"role": "system", "content": CLASSIFY_SYSTEM}, {"role": "user", "content": text}], CLASSIFY_SCHEMA
            )
            lines.insert(1, f"Class: {c['primary_class']} | Test: {c['test']} ({c['pitch_type'] or 'any pitch'}, {c['metric']})")
            self._last = {"starter": s, "classification": c, "boundary": boundary, "text": text}
            if c["test"] != "none":
                lines.insert(3, "Type /test to run it.")
            context = [f"{s.name} ({s.team}) tonight:", capsule_now]
            if earlier:
                context.append("Earlier viewer observations: " + "; ".join(o.raw_text for o in earlier))
            context.append(f"Viewer now says: {text}")
            reply = await self.llm.chat(
                [{"role": "system", "content": REPLY_SYSTEM}, {"role": "user", "content": "\n".join(context)}]
            )
            if reply:
                lines.append(reply)
        except LLMUnavailable as e:
            lines.append(f"(model unavailable, saved without analysis: {e})")
        return "\n".join(lines)

    async def _test(self) -> str:
        """Run the test named by the most recent classified observation (decisions.md #3: only on request)."""
        if self._last is None:
            return "Nothing to test yet: make an observation first."
        s, c = self._last["starter"], self._last["classification"]
        report = run_test(
            c,
            metrics.tonight_frame(self.tracker.pitches, s.pitcher_id),
            self.baselines.get(s.pitcher_id),
            boundary_inning=self._last["boundary"],
            alpha=self.alpha,
            mean_method=self.mean_method,
        )
        lines = [f'{s.name}: "{self._last["text"]}"', report.text]
        if report.result is not None and self.llm is not None:
            try:
                reply = await self.llm.chat(
                    [
                        {"role": "system", "content": TEST_SYSTEM},
                        {"role": "user", "content": f'Viewer observation: {self._last["text"]}\n\n{report.text}'},
                    ]
                )
                if reply:
                    lines.append(reply)
            except LLMUnavailable:
                pass  # the numbers stand on their own
        return "\n".join(lines)

    def _boundary(self, s: StarterTrack, n: int) -> str:
        """Which of tonight's data generated this observation, and where prospective data starts (SKILL.md §5).

        `n` is the last inning he had pitched in when the viewer spoke.
        """
        if s.exited:
            return "He has exited: any test of this on tonight's data is exploratory."
        if n == 0:
            return "Noted before his first pitch: everything he throws tonight is prospective."
        window = "inning 1" if n == 1 else f"innings 1-{n}"
        return f"Exploratory through {window}; prospective window starts with his inning {n + 1}."

    def _status(self) -> str:
        blocks = [
            f"{s.label} ({s.team})\n{self.tracker.starter_capsule(s)}"
            for s in self.tracker.candidates()
            if self.tracker.innings_pitched_in(s)
        ]
        return "\n\n".join(blocks) or "No pitches yet."

    def _list(self) -> str:
        obs = observations(self.conn, game_id=self.tracker.info.game_id)
        if not obs:
            return "No observations saved for this game."
        return "\n".join(f"{o.pitcher_name} ({o.team}) {(o.half or '?')[0].upper()}{o.inning or '?'}: {o.raw_text}" for o in obs)
