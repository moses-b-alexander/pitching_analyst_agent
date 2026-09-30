"""ESPN site API — secondary box-line corroboration and fallback (decisions.md #6).

Requires mapping MLB gamePk -> ESPN event id (by date + teams).
"""

from __future__ import annotations

from pitching_agent.models import PitcherLine

SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/summary"


class ESPNAdapter:
    name = "espn"

    async def pitcher_line(self, game_id: int, pitcher_id: int) -> PitcherLine | None:
        raise NotImplementedError
