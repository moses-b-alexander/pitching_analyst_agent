from datetime import datetime, timedelta, timezone

from conftest import GAME, RYAN

from pitching_agent.services.ingestion import ingest_feed
from pitching_agent.store import clear_game_analysis, connect, init_db, purge_expired

OTHER_GAME = 1


def _db_with_analysis(feed):
    conn = connect(":memory:")
    init_db(conn)
    ingest_feed(conn, feed)
    conn.execute("INSERT INTO games (game_id, date, home_team, away_team) VALUES (?, '2026-09-26', 'A', 'B')", (OTHER_GAME,))
    for game in (GAME, OTHER_GAME):
        cur = conn.execute(
            "INSERT INTO observations (game_id, pitcher_id, raw_text) VALUES (?, ?, 'curve looks lower')", (game, RYAN)
        )
        conn.execute(
            "INSERT INTO hypotheses (game_id, pitcher_id, observation_id, statement, status)"
            " VALUES (?, ?, ?, 'more CU below zone', 'frozen')",
            (game, RYAN, cur.lastrowid),
        )
        conn.execute("INSERT INTO summaries (game_id, kind, body) VALUES (?, 'half_inning', 'x')", (game,))
    conn.execute("INSERT INTO preferences (key, value_json) VALUES ('favored_classes', '[]')")
    conn.commit()
    return conn


def _count(conn, table, game=GAME):
    return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE game_id = ?", (game,)).fetchone()[0]


def test_clear_command_removes_only_that_games_analysis(final_feed):
    conn = _db_with_analysis(final_feed)
    counts = clear_game_analysis(conn, GAME)
    assert counts == {"hypotheses": 1, "observations": 1, "summaries": 1}
    assert _count(conn, "observations") == _count(conn, "hypotheses") == 0
    assert _count(conn, "pitches") > 0  # pitch data kept
    assert _count(conn, "observations", OTHER_GAME) == 1  # other games untouched
    assert conn.execute("SELECT COUNT(*) FROM preferences").fetchone()[0] == 1


def test_auto_clear_after_24h_from_final(final_feed):
    conn = _db_with_analysis(final_feed)
    final_seen = conn.execute("SELECT final_seen_at FROM games WHERE game_id = ?", (GAME,)).fetchone()[0]
    assert final_seen is not None
    t0 = datetime.strptime(final_seen, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)

    assert purge_expired(conn, now=t0 + timedelta(hours=23, minutes=59)) == []
    assert _count(conn, "observations") == 1

    assert purge_expired(conn, now=t0 + timedelta(hours=24)) == [GAME]
    assert _count(conn, "observations") == _count(conn, "hypotheses") == 0
    assert _count(conn, "observations", OTHER_GAME) == 1  # never went Final
    assert purge_expired(conn, now=t0 + timedelta(hours=48)) == []  # already cleared


def test_live_game_never_auto_clears(mid_feed):
    conn = _db_with_analysis(mid_feed)
    assert purge_expired(conn, now=datetime.now(timezone.utc) + timedelta(days=30)) == []
    assert _count(conn, "observations") == 1
