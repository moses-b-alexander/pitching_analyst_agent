"""Download the MLB/Savant test fixtures into tests/fixtures/ (gitignored).

MLBAM terms permit only individual, non-commercial, non-bulk use
(http://gdx.mlb.com/components/copyright.txt), so this data is fetched
locally and never committed.

    python scripts/fetch_fixtures.py [--force]
"""

from __future__ import annotations

import argparse
import gzip
import json
import time
from pathlib import Path

import httpx

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
UA = {"User-Agent": "live-pitching-agent/0.1 (test fixtures)"}

GAME = 823652  # TEX @ MIN, 2026-09-25
MID_TIMECODE = "20260926_014558"
RYAN = 657746

FEED = f"https://statsapi.mlb.com/api/v1.1/game/{GAME}/feed/live"
SAVANT = (
    "https://baseballsavant.mlb.com/statcast_search/csv?all=true&type=details&player_type=pitcher"
    f"&game_date_gt=2026-09-25&game_date_lt=2026-09-25&hfGT=R%7C&team=MIN&pitchers_lookup%5B%5D={RYAN}"
)

SAVANT_SEASON = (
    "https://baseballsavant.mlb.com/statcast_search/csv?all=true&type=details&player_type=pitcher"
    f"&hfSea=2026%7C&hfGT=R%7C&pitchers_lookup%5B%5D={RYAN}"
)

JSON_FIXTURES = {
    f"feed_{GAME}_final.json.gz": (FEED, None),
    f"feed_{GAME}_{MID_TIMECODE}.json.gz": (FEED, {"timecode": MID_TIMECODE}),
    f"box_{GAME}.json.gz": (f"https://statsapi.mlb.com/api/v1/game/{GAME}/boxscore", None),
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="re-download existing files")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    with httpx.Client(headers=UA, timeout=60) as client:
        for name, (url, params) in JSON_FIXTURES.items():
            path = OUT / name
            if path.exists() and not args.force:
                print(f"skip  {name}")
                continue
            resp = client.get(url, params=params)
            resp.raise_for_status()
            with gzip.open(path, "wt", encoding="utf-8") as f:
                json.dump(resp.json(), f, separators=(",", ":"))
            print(f"wrote {name}")
            time.sleep(1)  # be polite

        for name, url in {
            f"savant_{GAME}_{RYAN}.csv.gz": SAVANT,
            f"savant_season_2026_{RYAN}.csv.gz": SAVANT_SEASON,
            # Savant's own "heart" attack-zone filter (zones 1-9), to check our definition against
            f"savant_heart_2026_{RYAN}.csv.gz": SAVANT_SEASON + "&hfNewZones=" + "".join(f"{i}%7C" for i in range(1, 10)),
        }.items():
            path = OUT / name
            if path.exists() and not args.force:
                print(f"skip  {name}")
                continue
            resp = client.get(url)
            resp.raise_for_status()
            path.write_bytes(gzip.compress(resp.content))
            print(f"wrote {name}")
            time.sleep(1)


if __name__ == "__main__":
    main()
