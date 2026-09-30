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
from pitching_agent.services.ingestion import poll_once  # noqa: E402
from pitching_agent.sources import mlb  # noqa: E402
from pitching_agent.store import connect, init_db, load_pas, load_pitches  # noqa: E402


async def snapshot(conn, game_id: int) -> None:
    """Ingest the current feed once and print each starter's line so far."""
    adapter = mlb.MLBStatsAdapter()
    try:
        res = await poll_once(adapter, conn, game_id)
        feed = await adapter.live_feed(game_id)
    finally:
        await adapter.aclose()
    info = res.game
    print(f"{info.away.abbrev} @ {info.home.abbrev} {info.date} | {info.detailed_status}"
          f" | +{res.pitches_inserted} pitches, {res.pitches_revised} revised")  # fmt: skip
    pitches, pas = load_pitches(conn, game_id), load_pas(conn, game_id)
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
    parser.add_argument("--once", action="store_true", help="ingest once and print starter lines")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    conn = connect(cfg.db_path)
    init_db(conn)

    roles = ", ".join(f"{r}={spec or 'unset'}" for r, spec in cfg.models.items())
    print(f"live-pitching-agent {__version__} | db={cfg.db_path} | {roles}")
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
