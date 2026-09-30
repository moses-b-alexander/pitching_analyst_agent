"""Live ingestion: poll primary source, persist raw snapshots, normalize, upsert.

Never calls the LLM. User observations never block this loop.
The GUMBO feed is cumulative, so any single snapshot rebuilds full game state;
replaying all stored snapshots in order also rebuilds the revision history.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from pitching_agent.sources import mlb
from pitching_agent.store import load_snapshots, prune_snapshots, save_snapshot, upsert_pas, upsert_pitches

SOURCE = "mlb_live"


@dataclass
class IngestResult:
    game: mlb.GameInfo
    new_snapshot: bool
    pitches_inserted: int
    pitches_revised: int


def ingest_feed(conn: sqlite3.Connection, feed: dict[str, Any], *, store_snapshot: bool = True) -> IngestResult:
    info = mlb.game_info(feed)
    with conn:
        new = save_snapshot(conn, info.game_id, SOURCE, info.timecode, feed) if store_snapshot else False
        conn.execute(
            "INSERT INTO games (game_id, date, home_team, away_team, status, inning, half) VALUES (?,?,?,?,?,?,?)"
            " ON CONFLICT(game_id) DO UPDATE SET status=excluded.status, inning=excluded.inning,"
            " half=excluded.half, updated_at=CURRENT_TIMESTAMP",
            (info.game_id, info.date, info.home.abbrev, info.away.abbrev, info.status, info.inning,
             info.half.value if info.half else None),
        )  # fmt: skip
        pitches, pas = mlb.normalize(feed)
        stats = upsert_pitches(conn, pitches, SOURCE)
        upsert_pas(conn, pas, SOURCE)
        if info.status == "Final":
            conn.execute(
                "UPDATE games SET final_seen_at = CURRENT_TIMESTAMP WHERE game_id = ? AND final_seen_at IS NULL",
                (info.game_id,),
            )
            prune_snapshots(conn, info.game_id, SOURCE)
    return IngestResult(info, new, stats["inserted"], stats["revised"])


async def poll_once(adapter: mlb.MLBStatsAdapter, conn: sqlite3.Connection, game_id: int) -> IngestResult:
    return ingest_feed(conn, await adapter.live_feed(game_id))


def replay(conn: sqlite3.Connection, game_id: int) -> IngestResult | None:
    """Restart recovery (decisions.md #5): rebuild normalized state from stored snapshots."""
    result = None
    for _, feed in load_snapshots(conn, game_id, SOURCE):
        result = ingest_feed(conn, feed, store_snapshot=False)
    return result
