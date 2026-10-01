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
from pitching_agent.llm.client import LLMClient  # noqa: E402
from pitching_agent.services.chat import Chat  # noqa: E402
from pitching_agent.services.live import ReplaySource, run_live  # noqa: E402
from pitching_agent.services.tracker import GameTracker, Output  # noqa: E402
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


async def live(conn, cfg, game_id: int, replay_delay: float | None) -> None:
    """Follow a game until both starters' lines are final. With replay_delay, replay a finished game offline."""
    polling, output = cfg.raw.get("polling", {}), cfg.raw.get("output", {})
    tracker = GameTracker(
        lag=int(output.get("half_inning_lag", 1)),
        capsules=output.get("half_inning", "capsule_only") != "silent",
    )

    def emit(out: Output) -> None:
        print(f"\n{out.text}", flush=True)

    def on_feed(feed) -> None:
        info = tracker.info
        touch_game(conn, info.game_id, info.date, is_final=info.status == "Final")

    adapter = mlb.MLBStatsAdapter()
    llm = LLMClient(cfg.llm) if cfg.llm.model else None
    chat = Chat(tracker, conn, llm)
    try:
        if replay_delay is None:
            source, interval = adapter, float(polling.get("live_interval_s", 15))
        else:
            source, interval = ReplaySource(await adapter.live_feed(game_id)), replay_delay
        polling_task = asyncio.create_task(
            run_live(
                source,
                game_id,
                tracker,
                emit,
                interval=interval,
                reconcile_interval=float(polling.get("exit_reconcile_interval_s", 600)),
                give_up_after=float(polling.get("exit_give_up_after_game_end_s", 7200)),
                on_feed=on_feed if replay_delay is None else None,
                **({"sleep": _replay_sleep(replay_delay)} if replay_delay is not None else {}),
            )
        )
        chat_task = asyncio.create_task(chat_loop(chat))
        await asyncio.wait({polling_task, chat_task}, return_when=asyncio.FIRST_COMPLETED)
        if chat_task.done() and chat_task.result() == "quit":
            polling_task.cancel()
        elif chat_task.done():
            await polling_task  # stdin closed (not a terminal): just follow the game
        else:
            polling_task.result()  # surface any error
            print("\nBoth starters are final. Keep chatting, or /quit.", flush=True)
            await chat_task
    finally:
        await adapter.aclose()
        if llm:
            await llm.aclose()


async def chat_loop(chat: Chat) -> str:
    """Read typed lines without blocking the polling loop. Returns "quit" or "eof"."""
    loop = asyncio.get_running_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            return "eof"
        if line.strip().lower() in ("/quit", "quit", "exit"):
            return "quit"
        reply = await chat.handle(line)
        if reply:
            print(f"\n> {line.strip()}\n{reply}", flush=True)


def _replay_sleep(delay: float):
    async def sleep(_seconds: float) -> None:
        await asyncio.sleep(delay)  # fixed pace; ignore the loop's pregame / reconcile waits

    return sleep


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # stat lines use "·"; Windows consoles default to cp1252
    parser = argparse.ArgumentParser(description="Live starting-pitching analyst")
    parser.add_argument("--game", type=int, help="MLB gamePk")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--once", action="store_true", help="fetch once and print starter lines")
    parser.add_argument(
        "--replay",
        type=float,
        nargs="?",
        const=0.2,
        metavar="SECONDS_PER_PLAY",
        help="replay a finished game offline, one play per tick (default 0.2 s)",
    )
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
    try:
        asyncio.run(live(conn, cfg, args.game, args.replay))
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
