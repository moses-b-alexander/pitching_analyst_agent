from datetime import datetime, timedelta, timezone

import pytest

from pitching_agent.store import (
    SchemaMismatch,
    add_observation,
    clear_game,
    connect,
    init_db,
    observations,
    purge_expired,
    touch_game,
)

GAME, OTHER = 823652, 823653
DEGROM, RYAN = 594798, 657746


@pytest.fixture
def conn():
    c = connect(":memory:")
    init_db(c)
    touch_game(c, GAME, "2026-09-25", is_final=False)
    touch_game(c, OTHER, "2026-09-26", is_final=False)
    add = lambda game, team, pid, name, text: add_observation(  # noqa: E731
        c, game_id=game, team=team, pitcher_id=pid, pitcher_name=name, inning=2, half="top", raw_text=text
    )
    add(GAME, "MIN", RYAN, "Joe Ryan", "sweeper looks sharp")
    add(GAME, "TEX", DEGROM, "Jacob deGrom", "his velo looks cooked")
    add(GAME, "MIN", RYAN, "Joe Ryan", "splitter is staying up")
    add(OTHER, "MIN", 1, "Other Starter", "curve is buried")
    return c


def test_schema_is_observations_only(conn):
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables - {"sqlite_sequence"} == {"meta", "games", "observations"}
    init_db(conn)  # idempotent


def test_lookup_by_pitcher_and_by_team(conn):
    assert [o.raw_text for o in observations(conn, pitcher_id=RYAN)] == ["sweeper looks sharp", "splitter is staying up"]
    assert len(observations(conn, team="MIN")) == 3  # across games
    assert len(observations(conn, team="MIN", game_id=GAME)) == 2
    obs = observations(conn, game_id=GAME, team="TEX")[0]
    assert (obs.pitcher_name, obs.inning, obs.half, obs.raw_text) == ("Jacob deGrom", 2, "top", "his velo looks cooked")


def test_clear_command_removes_only_that_game(conn):
    assert clear_game(conn, GAME) == 3
    assert observations(conn, game_id=GAME) == []
    assert len(observations(conn, game_id=OTHER)) == 1


def test_auto_clear_24h_after_final(conn):
    touch_game(conn, GAME, "2026-09-25", is_final=True)
    seen = conn.execute("SELECT final_seen_at FROM games WHERE game_id = ?", (GAME,)).fetchone()[0]
    t0 = datetime.strptime(seen, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)

    assert purge_expired(conn, now=t0 + timedelta(hours=23, minutes=59)) == []
    assert len(observations(conn, game_id=GAME)) == 3

    assert purge_expired(conn, now=t0 + timedelta(hours=24)) == [GAME]
    assert observations(conn, game_id=GAME) == []
    assert len(observations(conn, game_id=OTHER)) == 1  # not Final, never auto-clears
    assert purge_expired(conn, now=t0 + timedelta(days=30)) == []


def test_final_clock_starts_once(conn):
    touch_game(conn, GAME, "2026-09-25", is_final=True)
    conn.execute("UPDATE games SET final_seen_at = '2026-09-26 03:00:00' WHERE game_id = ?", (GAME,))
    touch_game(conn, GAME, "2026-09-25", is_final=True)
    assert conn.execute("SELECT final_seen_at FROM games WHERE game_id = ?", (GAME,)).fetchone()[0] == "2026-09-26 03:00:00"


def test_stale_schema_is_refused():
    c = connect(":memory:")
    init_db(c)
    c.execute("UPDATE meta SET value = '1' WHERE key = 'schema_version'")
    with pytest.raises(SchemaMismatch):
        init_db(c)
