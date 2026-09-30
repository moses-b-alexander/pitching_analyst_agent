"""SQLite store. Authoritative for game state, observations, and hypotheses.

Restart recovery is a V1 requirement (decisions.md #5), so everything a live
session needs to resume must be written here, not held only in memory.

Local-only; raw observations are kept indefinitely. JSON session export/import
is a V1 feature (decisions.md #12).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

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
    launch_speed REAL,
    launch_angle REAL,
    timestamp TEXT,
    source TEXT NOT NULL,
    source_revision INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (game_id, at_bat_number, pitch_number)
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
    body TEXT NOT NULL
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


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()
