"""SQLite store. Authoritative for game state, observations, and hypotheses.

Restart recovery is a V1 requirement (decisions.md #5), so everything a live
session needs to resume must be written here, not held only in memory.

Local-only; raw observations are kept indefinitely. JSON session export/import
is a V1 feature (decisions.md #12).
"""

from __future__ import annotations

import json
import sqlite3
import zlib
from collections.abc import Iterable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from pitching_agent.models import Half, Pitch, PlateAppearance

SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS games (
    game_id INTEGER PRIMARY KEY,
    date TEXT NOT NULL,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    status TEXT,
    mode TEXT NOT NULL DEFAULT 'pregame',
    inning INTEGER,
    half TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS players (
    player_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    throws TEXT,
    bats TEXT
);

-- Tracked starters and their team membership (decisions.md #2).
CREATE TABLE IF NOT EXISTS session_starters (
    game_id INTEGER NOT NULL REFERENCES games(game_id),
    pitcher_id INTEGER NOT NULL REFERENCES players(player_id),
    team_id INTEGER NOT NULL,
    team_abbrev TEXT NOT NULL,
    team_name TEXT NOT NULL,
    starter_state TEXT NOT NULL DEFAULT 'active',
    PRIMARY KEY (game_id, pitcher_id)
);

CREATE TABLE IF NOT EXISTS pitcher_appearances (
    appearance_id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER NOT NULL REFERENCES games(game_id),
    pitcher_id INTEGER NOT NULL REFERENCES players(player_id),
    starter_bool INTEGER NOT NULL,
    start_time TEXT,
    end_time TEXT,
    finalized_bool INTEGER NOT NULL DEFAULT 0,
    outs INTEGER,
    pitches INTEGER,
    strikes INTEGER,
    hits INTEGER,
    runs INTEGER,
    earned_runs INTEGER,
    walks INTEGER,
    strikeouts INTEGER,
    home_runs INTEGER,
    batters_faced INTEGER,
    UNIQUE (game_id, pitcher_id)
);

CREATE TABLE IF NOT EXISTS pitches (
    game_id INTEGER NOT NULL,
    at_bat_number INTEGER NOT NULL,
    pitch_number INTEGER NOT NULL,
    appearance_id INTEGER REFERENCES pitcher_appearances(appearance_id),
    pitcher_id INTEGER NOT NULL,
    batter_id INTEGER NOT NULL,
    inning INTEGER NOT NULL,
    half TEXT NOT NULL,
    balls INTEGER NOT NULL,
    strikes INTEGER NOT NULL,
    pitch_type TEXT,
    description TEXT,
    is_strike INTEGER,
    event TEXT,
    release_speed REAL,
    release_pos_x REAL,
    release_pos_z REAL,
    release_extension REAL,
    plate_x REAL,
    plate_z REAL,
    sz_top REAL,
    sz_bot REAL,
    pfx_x REAL,
    pfx_z REAL,
    spin_rate REAL,
    launch_speed REAL,
    launch_angle REAL,
    timestamp TEXT,
    play_id TEXT,
    source TEXT NOT NULL,
    source_revision INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (game_id, at_bat_number, pitch_number)
);

CREATE TABLE IF NOT EXISTS plate_appearances (
    game_id INTEGER NOT NULL,
    at_bat_index INTEGER NOT NULL,
    inning INTEGER NOT NULL,
    half TEXT NOT NULL,
    pitcher_id INTEGER NOT NULL,
    batter_id INTEGER NOT NULL,
    bat_side TEXT NOT NULL,
    is_complete INTEGER NOT NULL,
    event_type TEXT,
    outs_on_play INTEGER NOT NULL DEFAULT 0,
    hit_code TEXT,
    runs_json TEXT NOT NULL DEFAULT '[]',  -- [[responsible_pitcher_id, earned], ...]
    source TEXT NOT NULL,
    PRIMARY KEY (game_id, at_bat_index)
);

-- Prior values of revisable fields (pitch_type, scoring). Never silently mutate history.
CREATE TABLE IF NOT EXISTS field_revisions (
    revision_id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER NOT NULL,
    entity TEXT NOT NULL,
    entity_key TEXT NOT NULL,
    field TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    source TEXT NOT NULL,
    observed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS raw_snapshots (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER NOT NULL,
    source TEXT NOT NULL,
    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    timecode TEXT,
    body BLOB NOT NULL,  -- zlib-compressed JSON
    UNIQUE (game_id, source, timecode)
);

CREATE TABLE IF NOT EXISTS observations (
    observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER NOT NULL,
    pitcher_id INTEGER,
    inning INTEGER,
    half TEXT,
    raw_text TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    problem_classes TEXT,
    primary_class TEXT,
    source TEXT NOT NULL DEFAULT 'viewer',
    interpreted INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS hypotheses (
    hypothesis_id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER NOT NULL,
    pitcher_id INTEGER NOT NULL,
    observation_id INTEGER REFERENCES observations(observation_id),
    statement TEXT NOT NULL,
    metric_definition TEXT,
    baseline_definition TEXT,
    generated_window TEXT,
    frozen_at TEXT,
    status TEXT NOT NULL DEFAULT 'candidate',
    inference_type TEXT,
    test_window TEXT,
    result_json TEXT
);

CREATE TABLE IF NOT EXISTS summaries (
    summary_id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER NOT NULL,
    pitcher_id INTEGER,
    kind TEXT NOT NULL,  -- pregame | half_inning | starter_exit | postgame
    inning INTEGER,
    half TEXT,
    body TEXT NOT NULL,
    model_role_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Resolved model per role, for audit (architecture §10).
CREATE TABLE IF NOT EXISTS session_models (
    game_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    spec TEXT NOT NULL,
    set_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Cross-game analytical preferences (decisions.md #4). Hypotheses do not live here.
CREATE TABLE IF NOT EXISTS preferences (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    if str(db_path) != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


class SchemaMismatch(RuntimeError):
    pass


def init_db(conn: sqlite3.Connection) -> None:
    has_meta = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'").fetchone()
    if has_meta:
        row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        if row and int(row["value"]) != SCHEMA_VERSION:
            # No migrations yet; fail loudly rather than run against a stale schema.
            raise SchemaMismatch(f"database schema v{row['value']}, code expects v{SCHEMA_VERSION}")
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Raw snapshots (replay / restart recovery)
# ---------------------------------------------------------------------------


def save_snapshot(conn: sqlite3.Connection, game_id: int, source: str, timecode: str | None, body: Any) -> bool:
    """Store a raw source payload once per timecode. Returns True if it was new."""
    blob = zlib.compress(json.dumps(body, separators=(",", ":")).encode())
    cur = conn.execute(
        "INSERT OR IGNORE INTO raw_snapshots (game_id, source, timecode, body) VALUES (?, ?, ?, ?)",
        (game_id, source, timecode, blob),
    )
    return cur.rowcount == 1


def load_snapshots(conn: sqlite3.Connection, game_id: int, source: str) -> list[tuple[str | None, Any]]:
    rows = conn.execute(
        "SELECT timecode, body FROM raw_snapshots WHERE game_id = ? AND source = ? ORDER BY snapshot_id",
        (game_id, source),
    )
    return [(r["timecode"], json.loads(zlib.decompress(r["body"]))) for r in rows]


# ---------------------------------------------------------------------------
# Normalized pitches / PAs
# ---------------------------------------------------------------------------

_PITCH_COLS = [
    "game_id", "at_bat_number", "pitch_number", "pitcher_id", "batter_id", "inning", "half",
    "balls", "strikes", "pitch_type", "description", "is_strike", "event",
    "release_speed", "release_pos_x", "release_pos_z", "release_extension",
    "plate_x", "plate_z", "sz_top", "sz_bot", "pfx_x", "pfx_z", "spin_rate",
    "launch_speed", "launch_angle", "timestamp", "play_id",
]  # fmt: skip

# Fields whose changes are logged rather than silently overwritten (architecture §5).
REVISABLE_PITCH_FIELDS = ("pitch_type",)


def _pitch_row(p: Pitch) -> dict[str, Any]:
    d = asdict(p)
    d["half"] = p.half.value
    d["timestamp"] = p.timestamp.isoformat() if p.timestamp else None
    return {k: d[k] for k in _PITCH_COLS}


def upsert_pitches(conn: sqlite3.Connection, pitches: Iterable[Pitch], source: str) -> dict[str, int]:
    """Insert new pitches; update changed ones, logging revisable-field changes. Returns counts."""
    stats = {"inserted": 0, "revised": 0}
    placeholders = ", ".join(f":{c}" for c in _PITCH_COLS)
    updates = ", ".join(f"{c} = :{c}" for c in _PITCH_COLS[3:])
    for p in pitches:
        row = _pitch_row(p)
        key = (p.game_id, p.at_bat_number, p.pitch_number)
        old = conn.execute(
            "SELECT pitch_type, source_revision FROM pitches WHERE game_id=? AND at_bat_number=? AND pitch_number=?",
            key,
        ).fetchone()
        if old is None:
            conn.execute(
                f"INSERT INTO pitches ({', '.join(_PITCH_COLS)}, source) VALUES ({placeholders}, :source)",
                {**row, "source": source},
            )
            stats["inserted"] += 1
            continue
        changed = [f for f in REVISABLE_PITCH_FIELDS if old[f] != row[f]]
        for f in changed:
            conn.execute(
                "INSERT INTO field_revisions (game_id, entity, entity_key, field, old_value, new_value, source)"
                " VALUES (?, 'pitch', ?, ?, ?, ?, ?)",
                (p.game_id, f"{p.at_bat_number}:{p.pitch_number}", f, old[f], row[f], source),
            )
        revision = old["source_revision"] + (1 if changed else 0)
        stats["revised"] += bool(changed)
        conn.execute(
            f"UPDATE pitches SET {updates}, source = :source, source_revision = :rev"
            " WHERE game_id = :game_id AND at_bat_number = :at_bat_number AND pitch_number = :pitch_number",
            {**row, "source": source, "rev": revision},
        )
    return stats


def upsert_pas(conn: sqlite3.Connection, pas: Iterable[PlateAppearance], source: str) -> None:
    conn.executemany(
        "INSERT OR REPLACE INTO plate_appearances (game_id, at_bat_index, inning, half, pitcher_id, batter_id,"
        " bat_side, is_complete, event_type, outs_on_play, hit_code, runs_json, source)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (a.game_id, a.at_bat_index, a.inning, a.half.value, a.pitcher_id, a.batter_id, a.bat_side,
             int(a.is_complete), a.event_type, a.outs_on_play, a.hit_code, json.dumps(a.runs), source)
            for a in pas
        ],
    )  # fmt: skip


def load_pitches(conn: sqlite3.Connection, game_id: int) -> list[Pitch]:
    rows = conn.execute(
        f"SELECT {', '.join(_PITCH_COLS)}, source_revision FROM pitches WHERE game_id = ?"
        " ORDER BY at_bat_number, pitch_number",
        (game_id,),
    )
    out = []
    for r in rows:
        d = dict(r)
        d["half"] = Half(d["half"])
        d["is_strike"] = None if d["is_strike"] is None else bool(d["is_strike"])
        d["timestamp"] = None  # not needed for analytics; raw snapshot keeps it
        out.append(Pitch(**d))
    return out


def load_pas(conn: sqlite3.Connection, game_id: int) -> list[PlateAppearance]:
    rows = conn.execute("SELECT * FROM plate_appearances WHERE game_id = ? ORDER BY at_bat_index", (game_id,))
    return [
        PlateAppearance(
            game_id=r["game_id"], at_bat_index=r["at_bat_index"], inning=r["inning"], half=Half(r["half"]),
            pitcher_id=r["pitcher_id"], batter_id=r["batter_id"], bat_side=r["bat_side"],
            is_complete=bool(r["is_complete"]), event_type=r["event_type"], outs_on_play=r["outs_on_play"],
            hit_code=r["hit_code"], runs=[tuple(x) for x in json.loads(r["runs_json"])],
        )
        for r in rows
    ]  # fmt: skip
