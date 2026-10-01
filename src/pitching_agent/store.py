"""SQLite store: viewer observations only, indexed by team and starting pitcher.

Game data is never stored. The MLB feed is cumulative, so a restart refetches it.
Observations are cleared on command or automatically 24 h after their game is
first seen Final (decisions.md #12).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA_VERSION = 4
OBSERVATION_TTL = timedelta(hours=24)

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Only what the 24 h clock needs.
CREATE TABLE IF NOT EXISTS games (
    game_id INTEGER PRIMARY KEY,
    date TEXT NOT NULL,
    final_seen_at TEXT
);

CREATE TABLE IF NOT EXISTS observations (
    observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER NOT NULL REFERENCES games(game_id),
    team TEXT NOT NULL,          -- starter's team abbreviation
    pitcher_id INTEGER NOT NULL,
    pitcher_name TEXT NOT NULL,
    inning INTEGER,              -- game state when typed; fixes the exploratory/prospective boundary
    half TEXT,
    raw_text TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS observations_by_pitcher ON observations (pitcher_id, game_id);
CREATE INDEX IF NOT EXISTS observations_by_team ON observations (team, game_id);
"""


@dataclass(frozen=True)
class Observation:
    observation_id: int
    game_id: int
    team: str
    pitcher_id: int
    pitcher_name: str
    inning: int | None
    half: str | None
    raw_text: str
    created_at: str


class SchemaMismatch(RuntimeError):
    pass


def connect(db_path: str | Path) -> sqlite3.Connection:
    if str(db_path) != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    has_meta = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'").fetchone()
    if has_meta:
        row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        if row and int(row["value"]) != SCHEMA_VERSION:
            # No migrations yet; fail loudly rather than run against a stale schema.
            raise SchemaMismatch(f"database schema v{row['value']}, code expects v{SCHEMA_VERSION}")
    conn.executescript(SCHEMA)
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
    conn.commit()


def touch_game(conn: sqlite3.Connection, game_id: int, date: str, *, is_final: bool) -> None:
    """Register a game and start its 24 h clock the first time it is seen Final."""
    with conn:
        conn.execute("INSERT OR IGNORE INTO games (game_id, date) VALUES (?, ?)", (game_id, date))
        if is_final:
            conn.execute(
                "UPDATE games SET final_seen_at = CURRENT_TIMESTAMP WHERE game_id = ? AND final_seen_at IS NULL",
                (game_id,),
            )


def add_observation(
    conn: sqlite3.Connection,
    *,
    game_id: int,
    team: str,
    pitcher_id: int,
    pitcher_name: str,
    inning: int | None,
    half: str | None,
    raw_text: str,
) -> int:
    with conn:
        cur = conn.execute(
            "INSERT INTO observations (game_id, team, pitcher_id, pitcher_name, inning, half, raw_text)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (game_id, team, pitcher_id, pitcher_name, inning, half, raw_text),
        )
    return cur.lastrowid


def observations(
    conn: sqlite3.Connection,
    *,
    game_id: int | None = None,
    pitcher_id: int | None = None,
    team: str | None = None,
) -> list[Observation]:
    """Observations filtered by any combination of game, starter, and team, oldest first."""
    filters = {"game_id": game_id, "pitcher_id": pitcher_id, "team": team}
    where = [f"{col} = ?" for col, val in filters.items() if val is not None]
    sql = "SELECT * FROM observations" + (" WHERE " + " AND ".join(where) if where else "")
    rows = conn.execute(sql + " ORDER BY observation_id", [v for v in filters.values() if v is not None])
    return [Observation(**dict(r)) for r in rows]


def clear_game(conn: sqlite3.Connection, game_id: int) -> int:
    """Delete a game's observations. Returns how many were removed."""
    with conn:
        n = conn.execute("DELETE FROM observations WHERE game_id = ?", (game_id,)).rowcount
        conn.execute("DELETE FROM games WHERE game_id = ?", (game_id,))
    return n


def purge_expired(conn: sqlite3.Connection, now: datetime | None = None, ttl: timedelta = OBSERVATION_TTL) -> list[int]:
    """Automatic clear for games Final longer than `ttl`. Returns the cleared game ids."""
    now = now or datetime.now(timezone.utc)
    cutoff = (now - ttl).strftime("%Y-%m-%d %H:%M:%S")  # SQLite CURRENT_TIMESTAMP format, UTC
    rows = conn.execute(
        "SELECT game_id FROM games WHERE final_seen_at IS NOT NULL AND final_seen_at <= ?", (cutoff,)
    ).fetchall()
    games = [r["game_id"] for r in rows]
    for game_id in games:
        clear_game(conn, game_id)
    return games
