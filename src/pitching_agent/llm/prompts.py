"""Prompt templates. The behavioral contract is skills/live-starting-pitching-analyst/SKILL.md."""

from __future__ import annotations

from pathlib import Path

SKILL_PATH = Path(__file__).resolve().parents[3] / "skills" / "live-starting-pitching-analyst" / "SKILL.md"


def load_skill() -> str:
    return SKILL_PATH.read_text(encoding="utf-8")
