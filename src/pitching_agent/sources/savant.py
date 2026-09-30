"""Baseball Savant Statcast adapter — authoritative historical corpus.

Season + current-postseason per starter, re-pulled in full every pregame
(decisions.md #11) so MLB pitch reclassifications are always picked up.
data/cache/ holds the last pull as a fallback if Savant is unavailable.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

CSV_URL = "https://baseballsavant.mlb.com/statcast_search/csv"

# Statcast game_type codes
REGULAR_SEASON = "R"
POSTSEASON = ("F", "D", "L", "W")


class SavantAdapter:
    name = "savant_csv"

    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir

    async def pitcher_corpus(self, pitcher_id: int, season: int, game_type: str) -> pd.DataFrame:
        raise NotImplementedError
