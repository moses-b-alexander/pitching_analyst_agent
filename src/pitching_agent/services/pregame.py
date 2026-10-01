"""Season context for each starter: the pregame lines and the baseline frame tests compare against.

Loaded in the background the first time a starter is seen (a probable before first pitch,
or the actual starter if he differs), so a slow or failed Savant pull never blocks the game loop.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import httpx
import pandas as pd

from pitching_agent.analytics import metrics
from pitching_agent.analytics.lines import PITCH_ORDER
from pitching_agent.compositor import SEP
from pitching_agent.services.tracker import GameTracker, Output, StarterTrack
from pitching_agent.sources.mlb import GameInfo, MLBStatsAdapter
from pitching_agent.sources.savant import SavantAdapter, SavantUnavailable


def format_to_date(games: list[dict[str, Any]], *, before_date: str, exclude_game: int) -> str:
    """Running totals through his last appearance before tonight: regular season and postseason together."""
    prior = [g for g in games if g["game_id"] != exclude_game and g["date"] <= before_date]
    if not prior:
        return "Season to date: no appearances before tonight"
    outs, er, k, bb = (sum(g["stat"][f] for g in prior) for f in ("outs", "earnedRuns", "strikeOuts", "baseOnBalls"))
    era = f"{27 * er / outs:.2f}" if outs else "-.--"
    line = SEP.join([f"{len(prior)} G", f"{outs // 3}.{outs % 3} IP", f"{era} ERA", f"{k} K", f"{bb} BB"])
    post = sum(g["postseason"] for g in prior)
    return f"Season to date: {line}" + (f" (incl. {post} postseason G)" if post else "")


def format_season_mix(frame: pd.DataFrame) -> str:
    counts = frame["pitch_type"].dropna().value_counts()
    rank = {t: i for i, t in enumerate(PITCH_ORDER)}
    ordered = sorted(counts.index, key=lambda t: (rank.get(t, len(rank)), t))
    body = SEP.join(f"{t} {100 * counts[t] / counts.sum():.0f}%" for t in ordered)
    return f"Mix: {body} ({counts.sum():,} pitches)"


class Baselines:
    def __init__(self, mlb: MLBStatsAdapter, savant: SavantAdapter, emit: Callable[[Output], None]) -> None:
        self._mlb = mlb
        self._savant = savant
        self._emit = emit
        self.frames: dict[int, pd.DataFrame] = {}  # pitcher id -> metrics frame of his season before tonight
        self._seen: set[int] = set()
        self._tasks: set[asyncio.Task] = set()

    def ensure(self, tracker: GameTracker) -> None:
        """Start loading for any starter not seen yet. Call after each feed update."""
        if tracker.info is None:
            return
        for s in tracker.candidates():
            if s.pitcher_id not in self._seen:
                self._seen.add(s.pitcher_id)
                task = asyncio.create_task(self.load(s, tracker.info))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)

    async def load(self, s: StarterTrack, info: GameInfo) -> None:
        season = int(info.date[:4])
        lines = [f"PREGAME {s.name} ({s.team})"]
        try:
            games = await self._mlb.game_log(s.pitcher_id, season)
            lines.append(format_to_date(games, before_date=info.date, exclude_game=info.game_id))
        except httpx.HTTPError:
            lines.append("Season line unavailable.")
        try:
            raw = await self._savant.baseline(s.pitcher_id, season, before_date=info.date, exclude_game=info.game_id)
            if raw.empty:
                lines.append("No season pitch data before this game; baseline tests unavailable.")
            else:
                self.frames[s.pitcher_id] = frame = metrics.savant_frame(raw)
                lines.append(format_season_mix(frame) + (" [cached]" if raw.attrs.get("stale") else ""))
        except SavantUnavailable:
            lines.append("Season pitch data unavailable (Savant unreachable); baseline tests unavailable.")
        self._emit(Output("status", "\n".join(lines), s.pitcher_id))

    async def wait(self) -> None:
        """Wait for loads in flight (used by tests and before exit)."""
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
