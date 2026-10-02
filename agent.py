"""CLI entry point: `python agent.py --game <gamePk>`."""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import httpx  # noqa: E402

from pitching_agent import __version__  # noqa: E402
from pitching_agent.analytics.lines import window_hits, window_line, window_mix, window_mix_by_hand  # noqa: E402
from pitching_agent.compositor import capsule  # noqa: E402
from pitching_agent.config import load_config  # noqa: E402
from pitching_agent.llm.client import LLMClient  # noqa: E402
from pitching_agent.services.chat import Chat  # noqa: E402
from pitching_agent.services.live import ReplaySource, run_live  # noqa: E402
from pitching_agent.services.pregame import Baselines  # noqa: E402
from pitching_agent.services.resolve import describe, latest_played, match_games, named_teams, pick  # noqa: E402
from pitching_agent.sources.savant import SavantAdapter  # noqa: E402
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
        print(
            capsule(
                window_line(pitches, pas, pid),
                window_mix(pitches, pid),
                window_hits(pas, pid),
                include_ip=True,
                mix_by_hand=window_mix_by_hand(pitches, pid),
            )
        )


async def live(conn, cfg, game_id: int, replay_delay: float | None) -> None:
    """Follow a game until both starters' lines are final. With replay_delay, replay a finished game offline."""
    polling, output = cfg.raw.get("polling", {}), cfg.raw.get("output", {})
    tracker = GameTracker(
        lag=int(output.get("half_inning_lag", 1)),
        capsules=output.get("half_inning", "capsule_only") != "silent",
    )

    def emit(out: Output) -> None:
        print(f"\n{out.text}", flush=True)

    adapter = mlb.MLBStatsAdapter()
    savant = SavantAdapter(cfg.cache_dir)
    baselines = Baselines(adapter, savant, emit)
    llm = LLMClient(cfg.llm) if cfg.llm.model else None
    stats_cfg = cfg.raw.get("stats") or {}
    chat = Chat(
        tracker, conn, llm, baselines=baselines.frames, alpha=cfg.alpha, mean_method=stats_cfg.get("mean_test", "permutation")
    )

    def on_feed(feed) -> None:
        info = tracker.info
        baselines.ensure(tracker)  # season lines + baseline for any starter not loaded yet
        if replay_delay is None:
            touch_game(conn, info.game_id, info.date, is_final=info.status == "Final")

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
                on_feed=on_feed,
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
        await baselines.wait()
        await adapter.aclose()
        await savant.aclose()
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


async def find_game(teams: list[str], on: date | None) -> int | None:
    """Resolve team names to a gamePk, printing what was found. None if there is no single answer."""
    adapter = mlb.MLBStatsAdapter()
    try:
        days = [on] if on else [date.today()]
        if on is None and datetime.now().hour < 6:
            days.insert(0, days[0] - timedelta(days=1))  # a late game may still be running after midnight
        query = " ".join(teams)
        for i, day in enumerate(days):
            games = await adapter.resolve_games(day)
            matches = match_games(games, query) if teams else []
            if i < len(days) - 1:  # yesterday only counts if that game is still in progress
                matches = [g for g in matches if g["status"]["abstractGameState"] == "Live"]
                if not matches:
                    continue
            chosen = pick(matches)
            if chosen:
                print(f"Following: {describe(chosen)}")
                return chosen["gamePk"]
            if matches:
                matchups = {(g["teams"]["away"]["team"]["id"], g["teams"]["home"]["team"]["id"]) for g in matches}
                if len(matchups) == 1:
                    print(f"Both games of that doubleheader on {day} are over. Pick one with --game:")
                else:
                    print(f"More than one game on {day} fits {query!r}. Name both teams or use --game:")
                listing = matches
            elif teams:
                print(f"No game on {day} fits {query!r}. Games that day:")
                listing = games
            else:
                print(f"Games on {day} (name a team, or use --game):")
                listing = games
            for g in sorted(listing, key=lambda g: g["gameDate"]):
                print("  " + describe(g))
            if not listing:
                print("  none")
        return None
    finally:
        await adapter.aclose()


async def find_latest(teams: list[str], on: date | None) -> int | None:
    """Resolve a team (or two) to the most recent game it actually played, on or before `on`."""
    end = on or date.today()
    adapter = mlb.MLBStatsAdapter()
    try:
        found, ambiguous = named_teams(await adapter.teams(end.year), " ".join(teams))
        if not found:
            print(f"No team fits {' '.join(teams)!r}.")
            return None
        if ambiguous or len(found) > 2:
            print("Which team: " + " or ".join(t["name"] for t in found) + "?")
            return None
        opponent = found[1]["id"] if len(found) == 2 else None
        for days_back in (21, 365):  # a recent window first; it is a much smaller request
            games = await adapter.team_games(found[0]["id"], end - timedelta(days=days_back), end)
            game = latest_played(games, opponent)
            if game:
                print(f"Following ({game['officialDate']}): {describe(game)}")
                return game["gamePk"]
        versus = f" against the {found[1]['teamName']}" if opponent else ""
        print(f"No game played by the {found[0]['teamName']}{versus} in the year up to {end}.")
        return None
    finally:
        await adapter.aclose()


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # stat lines use "·"; Windows consoles default to cp1252
    parser = argparse.ArgumentParser(description="Live starting-pitching analyst")
    parser.add_argument("teams", nargs="*", help="team name(s), e.g. twins or TEX MIN; lists the day's games if omitted")
    parser.add_argument("--game", type=int, help="MLB gamePk (instead of team names)")
    parser.add_argument("--date", type=date.fromisoformat, help="game date YYYY-MM-DD (default: today)")
    parser.add_argument(
        "--latest",
        action="store_true",
        help="use the team's most recent game, in progress or finished (on or before --date)",
    )
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
        try:
            if args.latest and not args.teams:
                print("--latest needs a team name, e.g. python agent.py twins --latest")
                return 1
            finder = find_latest if args.latest else find_game
            args.game = asyncio.run(finder(args.teams, args.date))
        except httpx.HTTPError as e:
            print(f"Could not reach the MLB schedule ({type(e).__name__}). Try again, or use --game.")
            return 1
        if args.game is None:
            return 1 if args.teams else 0
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
