"""Pitcher line / mix / hits over an inning window, computed from normalized pitches and PAs.

Always scoped to one pitcher, so a window never spans a pitching change (architecture §7).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from pitching_agent.analytics.windows import InningWindow
from pitching_agent.models import Pitch, PitcherLine, PlateAppearance

STRIKEOUTS = {"strikeout", "strikeout_double_play", "strikeout_triple_play"}
WALKS = {"walk", "intent_walk"}
HITS = {"single", "double", "triple", "home_run"}

# Display order for the Mix line: fastballs, then breaking, then offspeed.
PITCH_ORDER = ["FF", "SI", "FC", "SL", "ST", "SV", "CU", "KC", "CS", "CH", "FS", "FO", "SC", "KN", "EP"]


def _in(window: InningWindow | None, inning: int) -> bool:
    return window is None or window.contains(inning)


def window_line(
    pitches: Iterable[Pitch],
    pas: Iterable[PlateAppearance],
    pitcher_id: int,
    window: InningWindow | None = None,
) -> PitcherLine:
    ps = [p for p in pitches if p.pitcher_id == pitcher_id and _in(window, p.inning)]
    done = [a for a in pas if a.pitcher_id == pitcher_id and a.is_complete and _in(window, a.inning)]
    runs = [earned for a in pas if _in(window, a.inning) for pid, earned in a.runs if pid == pitcher_id]
    return PitcherLine(
        outs=sum(a.outs_on_play for a in done),
        pitches=len(ps),
        strikes=sum(1 for p in ps if p.is_strike),
        hits=sum(1 for a in done if a.event_type in HITS),
        runs=len(runs),
        earned_runs=sum(runs),
        walks=sum(1 for a in done if a.event_type in WALKS),
        strikeouts=sum(1 for a in done if a.event_type in STRIKEOUTS),
        home_runs=sum(1 for a in done if a.event_type == "home_run"),
        batters_faced=len(done),
    )


def window_mix(pitches: Iterable[Pitch], pitcher_id: int, window: InningWindow | None = None) -> dict[str, int] | None:
    """Pitch-type counts in display order. None if any pitch is still unclassified (mix pending)."""
    types = [p.pitch_type for p in pitches if p.pitcher_id == pitcher_id and _in(window, p.inning)]
    if not types or any(t is None for t in types):
        return None
    counts = Counter(types)
    rank = {t: i for i, t in enumerate(PITCH_ORDER)}
    return {t: counts[t] for t in sorted(counts, key=lambda t: (rank.get(t, len(rank)), t))}


def window_hits(pas: Iterable[PlateAppearance], pitcher_id: int, window: InningWindow | None = None) -> list[str]:
    return [
        a.hit_code
        for a in sorted(pas, key=lambda a: a.at_bat_index)
        if a.pitcher_id == pitcher_id and a.is_complete and a.hit_code and _in(window, a.inning)
    ]
