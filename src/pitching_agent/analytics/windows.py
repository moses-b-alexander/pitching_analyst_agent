"""Inning-window semantics (architecture §7, SKILL.md §4).

Innings are the narrative unit. A window is never silently re-cut by pitch count,
and never spans a pitching change: callers filter by appearance before windowing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_PATTERN = re.compile(r"^\s*I?(\d+)\s*(?:[-–—]\s*I?(\d+))?\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class InningWindow:
    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start < 1 or self.end < self.start:
            raise ValueError(f"invalid inning window {self.start}-{self.end}")

    @classmethod
    def parse(cls, text: str) -> InningWindow:
        """Accepts `I2`, `2`, `I1–I3`, `I3-I5`, `3-5`."""
        m = _PATTERN.match(text)
        if not m:
            raise ValueError(f"not an inning window: {text!r}")
        start = int(m.group(1))
        end = int(m.group(2)) if m.group(2) else start
        return cls(start, end)

    def contains(self, inning: int) -> bool:
        return self.start <= inning <= self.end

    def precedes(self, other: InningWindow) -> bool:
        """True if this window ends before `other` begins (prospective ordering)."""
        return self.end < other.start

    def __str__(self) -> str:
        return f"I{self.start}" if self.start == self.end else f"I{self.start}–I{self.end}"
