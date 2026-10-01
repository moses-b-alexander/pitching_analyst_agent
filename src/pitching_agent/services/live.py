"""The polling loop: fetch the feed, hand it to the tracker, emit what it returns.

Never calls the model. If the feed fails, keeps retrying with backoff; a capsule that is
due is printed when data returns, never skipped or guessed (decisions.md #1).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

import httpx

from pitching_agent.services.tracker import GameTracker, Output
from pitching_agent.sources.mlb import truncate_feed

MAX_BACKOFF_S = 120.0
PREGAME_INTERVAL_S = 60.0


class FeedSource(Protocol):
    async def live_feed(self, game_id: int) -> dict[str, Any]: ...


async def run_live(
    source: FeedSource,
    game_id: int,
    tracker: GameTracker,
    emit: Callable[[Output], None],
    *,
    interval: float = 15.0,
    reconcile_interval: float = 600.0,
    give_up_after: float = 7200.0,
    on_feed: Callable[[dict[str, Any]], None] | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """Run until the game is Final and every starter's line is closed out."""
    backoff = max(interval, 1.0)
    failing = False
    final_at: float | None = None

    while True:
        try:
            feed = await source.live_feed(game_id)
            outputs = tracker.update(feed)
        except (httpx.HTTPError, KeyError, ValueError) as e:
            # KeyError/ValueError: a half-written or reshaped payload; treat like an outage and retry.
            if not failing:
                emit(Output("status", f"Feed unavailable ({type(e).__name__}); retrying."))
            failing = True
            await sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_S)
            continue

        if failing:
            emit(Output("status", "Feed back."))
            failing, backoff = False, max(interval, 1.0)
        for output in outputs:
            emit(output)
        if on_feed:
            on_feed(feed)

        if tracker.is_final:
            if tracker.done:
                return
            # Game over but a starter's line has not reconciled: slow recheck, then give up.
            final_at = clock() if final_at is None else final_at
            if clock() - final_at >= give_up_after:
                for output in tracker.give_up():
                    emit(output)
                return
            await sleep(reconcile_interval)
        elif tracker.is_preview:
            await sleep(max(interval, PREGAME_INTERVAL_S))
        else:
            # The feed states its own minimum poll interval (metaData.wait).
            await sleep(max(interval, float(feed.get("metaData", {}).get("wait", 0))))


class ReplaySource:
    """Replays a completed game's feed one play per poll, offline (one fetch, then no network)."""

    def __init__(self, feed: dict[str, Any], *, start: int = 0) -> None:
        self._feed = feed
        self._n = start
        self.total = len(feed["liveData"]["plays"]["allPlays"])

    async def live_feed(self, game_id: int) -> dict[str, Any]:
        feed = truncate_feed(self._feed, self._n)
        self._n = min(self._n + 1, self.total)
        return feed
