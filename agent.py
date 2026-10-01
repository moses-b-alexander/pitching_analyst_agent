"""CLI entry point: `python agent.py --game <gamePk>`."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from pitching_agent import __version__  # noqa: E402
from pitching_agent.analytics.lines import window_hits, window_line, window_mix  # noqa: E402
from pitching_agent.compositor import capsule  # noqa: E402
from pitching_agent.config import load_config  # noqa: E402
from pitching_agent.sources import mlb  # noqa: E402
from pitching_agent.store import clear_game, connect, init_db, purge_expired, touch_game  # noqa: E402


async def snapshot(conn, game_id: int) -> None:
    """Fetch the current feed once and print each starter's line so far."""
    adapter = mlb.MLBStatsAdapter()
    try:
        feed = await adapter.live_feed(game_id)
    finally:
        await adapter.aclose()
    info = mlb.game_info(feed)
    touch_game(conn, info.game_id, info.date, is_final=info.status == "Final")
    print(f"{info.away.abbrev} @ {info.home.abbrev} {info.date} | {info.detailed_status}")
    pitches, pas = mlb.normalize(feed)
    names = {int(k[2:]): v["fullName"] for k, v in feed["gameData"]["players"].items()}
    for side, pid in mlb.actual_starters(feed).items():
        if pid is None:
            continue
        print(f"\n{names.get(pid, pid)} ({getattr(info, side).abbrev} SP)")
        print(capsule(window_line(pitches, pas, pid), window_mix(pitches, pid), window_hits(pas, pid), include_ip=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Live starting-pitching analyst")
    parser.add_argument("--game", type=int, help="MLB gamePk")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--once", action="store_true", help="fetch once and print starter lines")
    parser.add_argument("--clear-game", type=int, metavar="GAMEPK", help="delete a game's saved observations")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    conn = connect(cfg.db_path)
    init_db(conn)

    print(f"live-pitching-agent {__version__} | db={cfg.db_path} | model={cfg.llm.model or 'none (facts-only)'}")

    for game_id in purge_expired(conn):
        print(f"Auto-cleared observations for game {game_id} (final > 24 h).")
    if args.clear_game is not None:
        print(f"Cleared game {args.clear_game}: {clear_game(conn, args.clear_game)} observations")
        return 0
    if args.game is None:
        print("No --game given.")
        return 0
    if args.once:
        asyncio.run(snapshot(conn, args.game))
        return 0
    print(f"Game {args.game}: live loop not yet implemented; use --once.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
