"""Deterministic factual lines. Never LLM output (architecture §9, SKILL.md Task 1).

Missing (unverified) fields render as pending; nothing is guessed to fill the template.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from pitching_agent.models import PitcherLine

SEP = " · "

LEGEND = "\n".join(
    [
        "¹ viewer obs supported · ² partial/mixed · ³ not supported · ⁴ unresolved",
        "ᵃ thesis strengthened · ᵇ partially supported/qualified · ᶜ weakened · ᵈ corrected/reframed · ᵉ unresolved",
    ]
)


def _pct(n: int, total: int) -> int:
    # Round half up; Python's round() is banker's rounding.
    return math.floor(100 * n / total + 0.5)


def format_ip(outs: int) -> str:
    return f"{outs // 3}.{outs % 3}"


def format_line(line: PitcherLine, *, include_ip: bool = False) -> str:
    """`Line: 17 P · 11S/6B | 1 R · 3 H | 2 K · 1 BB`

    With include_ip (starter exit): `Line: 4.2 IP · 83 P · 58S/25B | 1 R/ER · 5 H | 4 K · 1 BB`
    """
    core = (line.pitches, line.strikes, line.runs, line.hits, line.strikeouts, line.walks)
    if any(v is None for v in core) or (include_ip and line.outs is None):
        return "Line: pending"

    balls = line.pitches - line.strikes
    count = f"{line.pitches} P{SEP}{line.strikes}S/{balls}B"
    if include_ip:
        count = f"{format_ip(line.outs)} IP{SEP}{count}"

    if include_ip and line.earned_runs is not None:
        runs = f"{line.runs} R/ER" if line.runs == line.earned_runs else f"{line.runs} R ({line.earned_runs} ER)"
    else:
        runs = f"{line.runs} R"

    return f"Line: {count} | {runs}{SEP}{line.hits} H | {line.strikeouts} K{SEP}{line.walks} BB"


def format_mix(counts: Mapping[str, int] | None, *, provisional: bool = False) -> str:
    """`Mix: 4S 8 (47%) · SI 3 (18%)` in the caller's order (the pitcher's arsenal order)."""
    if not counts:
        return "Mix: exact counts pending"
    total = sum(counts.values())
    body = SEP.join(f"{pt} {n} ({_pct(n, total)}%)" for pt, n in counts.items())
    return f"Mix: {body}" + (" [provisional]" if provisional else "")


def format_hits(hits: Sequence[str]) -> str:
    """Retrosheet-style hit line, e.g. `Hits: S8 · S7 · D9`."""
    return "Hits: " + (SEP.join(hits) if hits else "none")


def capsule(
    line: PitcherLine,
    mix: Mapping[str, int] | None,
    hits: Sequence[str],
    *,
    include_ip: bool = False,
    mix_provisional: bool = False,
) -> str:
    return "\n".join(
        [
            format_line(line, include_ip=include_ip),
            format_mix(mix, provisional=mix_provisional),
            format_hits(hits),
        ]
    )
