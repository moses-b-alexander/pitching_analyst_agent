"""CLI entry point: `python agent.py --game <gamePk>`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from pitching_agent import __version__  # noqa: E402
from pitching_agent.config import load_config  # noqa: E402
from pitching_agent.store import connect, init_db  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Live starting-pitching analyst")
    parser.add_argument("--game", type=int, help="MLB gamePk")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    conn = connect(cfg.db_path)
    init_db(conn)

    roles = ", ".join(f"{r}={spec or 'unset'}" for r, spec in cfg.models.items())
    print(f"live-pitching-agent {__version__} | db={cfg.db_path} | {roles}")
    if args.game is None:
        print("No --game given. Live ingestion not yet implemented.")
        return 0
    print(f"Game {args.game}: live ingestion not yet implemented.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
