"""Adapter protocols. Swap sources without touching analytics (architecture §4)."""

from __future__ import annotations

from datetime import date
from typing import Any, Protocol

import pandas as pd

from pitching_agent.models import PitcherLine

USER_AGENT = "live-pitching-agent/0.1 (personal, low-frequency)"


class LiveSource(Protocol):
    name: str

    async def resolve_games(self, on: date) -> list[dict[str, Any]]: ...

    async def live_feed(self, game_id: int) -> dict[str, Any]: ...


class BoxLineSource(Protocol):
    """Anything that can report a pitcher's box line for exit-gate corroboration."""

    name: str

    async def pitcher_line(self, game_id: int, pitcher_id: int) -> PitcherLine | None: ...


class HistoricalSource(Protocol):
    name: str

    async def pitcher_corpus(self, pitcher_id: int, season: int, game_type: str) -> pd.DataFrame: ...
