"""MLB Stats API adapter — authoritative live source (decisions.md #6).

The endpoints are public but undocumented; keep every schema assumption in this
module and cover it with recorded fixtures under tests/fixtures/.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx

from pitching_agent.models import PitcherLine
from pitching_agent.sources.base import USER_AGENT

BASE = "https://statsapi.mlb.com"


class MLBStatsAdapter:
    name = "mlb_live"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(
            base_url=BASE, headers={"User-Agent": USER_AGENT}, timeout=15.0
        )

    async def _get(self, path: str, **params: Any) -> dict[str, Any]:
        resp = await self._client.get(path, params=params or None)
        resp.raise_for_status()
        return resp.json()

    async def resolve_games(self, on: date) -> list[dict[str, Any]]:
        data = await self._get(
            "/api/v1/schedule", sportId=1, date=on.isoformat(), hydrate="probablePitcher,team"
        )
        return [g for d in data.get("dates", []) for g in d.get("games", [])]

    async def live_feed(self, game_id: int) -> dict[str, Any]:
        return await self._get(f"/api/v1.1/game/{game_id}/feed/live")

    async def boxscore(self, game_id: int) -> dict[str, Any]:
        return await self._get(f"/api/v1/game/{game_id}/boxscore")

    async def person(self, player_id: int) -> dict[str, Any]:
        data = await self._get(f"/api/v1/people/{player_id}")
        return data["people"][0]

    async def pitcher_line(self, game_id: int, pitcher_id: int) -> PitcherLine | None:
        raise NotImplementedError("normalize boxscore -> PitcherLine (next step)")

    async def aclose(self) -> None:
        await self._client.aclose()
