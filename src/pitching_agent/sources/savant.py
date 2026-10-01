"""Baseball Savant Statcast adapter: the historical corpus for baselines.

Season + current postseason per starter, re-pulled in full every pregame
(decisions.md #11) so MLB pitch reclassifications are always picked up.
data/cache/ holds the last pull as a fallback if Savant is unavailable.
One request per pitcher per game type (~2 MB for a full season).
"""

from __future__ import annotations

import io
from pathlib import Path

import httpx
import pandas as pd

from pitching_agent.sources.base import USER_AGENT

CSV_URL = "https://baseballsavant.mlb.com/statcast_search/csv"

REGULAR_SEASON = "R"
POSTSEASON = "PO"


class SavantUnavailable(RuntimeError):
    """Savant could not be reached and there is no cached pull to fall back on."""


class SavantAdapter:
    name = "savant_csv"

    def __init__(self, cache_dir: Path, client: httpx.AsyncClient | None = None) -> None:
        self.cache_dir = Path(cache_dir)
        self._client = client or httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, timeout=120.0)

    def _cache_path(self, pitcher_id: int, season: int, game_type: str) -> Path:
        return self.cache_dir / f"savant_{pitcher_id}_{season}_{game_type}.csv.gz"

    async def pitcher_corpus(self, pitcher_id: int, season: int, game_type: str = REGULAR_SEASON) -> pd.DataFrame:
        """Every pitch the pitcher threw in that season and game type. `df.attrs["stale"]` marks a cache fallback."""
        path = self._cache_path(pitcher_id, season, game_type)
        try:
            resp = await self._client.get(
                CSV_URL,
                params={
                    "all": "true",
                    "type": "details",
                    "player_type": "pitcher",
                    "hfSea": f"{season}|",
                    "hfGT": f"{game_type}|",
                    "pitchers_lookup[]": pitcher_id,
                },
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            if path.exists():
                df = pd.read_csv(path)
                df.attrs["stale"] = True
                return df
            raise SavantUnavailable(f"Savant unreachable and no cached corpus for {pitcher_id}: {e}") from e

        df = pd.read_csv(io.BytesIO(resp.content)) if resp.content.strip() else pd.DataFrame()
        if not df.empty:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            df.to_csv(path, index=False)
        df.attrs["stale"] = False
        return df

    async def baseline(self, pitcher_id: int, season: int, *, before_date: str, exclude_game: int) -> pd.DataFrame:
        """Regular season + postseason pitches thrown before `before_date`, never including tonight's game."""
        frames = [await self.pitcher_corpus(pitcher_id, season, REGULAR_SEASON)]
        try:
            frames.append(await self.pitcher_corpus(pitcher_id, season, POSTSEASON))
        except SavantUnavailable:
            # Most pitchers have no postseason pitches, so there is usually nothing cached to fall
            # back on. The regular season alone is still a usable baseline.
            frames[0].attrs["stale"] = True
        stale = any(f.attrs.get("stale") for f in frames)
        frames = [f for f in frames if not f.empty]
        if not frames:
            return pd.DataFrame()
        df = pd.concat(frames, ignore_index=True)
        df = df[(df["game_date"] < before_date) & (df["game_pk"] != exclude_game)].reset_index(drop=True)
        df.attrs["stale"] = stale
        return df

    async def aclose(self) -> None:
        await self._client.aclose()
