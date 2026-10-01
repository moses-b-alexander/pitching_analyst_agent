"""Decides what to print as the game advances. Pure: feed in, outputs out; no I/O, no model.

All state is recomputed from each (cumulative) feed, so a restart only needs one fetch.

Half-inning lag (decisions.md #1): with lag 1, a starter's capsule for a half-inning
prints when the *next* half-inning completes, i.e. after bottom N for the top-N pitcher
and after top N+1 for the bottom-N pitcher.

Starter exit (decisions.md #6, #8): a replacement appearing for the starter's side opens
the exit; the final line prints once the plays-derived line agrees with the feed's
boxscore and, for a mid-inning exit, that half-inning has ended (inherited runners resolved).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pitching_agent.analytics.lines import window_hits, window_line, window_mix
from pitching_agent.analytics.windows import InningWindow
from pitching_agent.compositor import capsule
from pitching_agent.models import Half, Pitch, PlateAppearance
from pitching_agent.services.reconciliation import evaluate_gate
from pitching_agent.sources import mlb
from pitching_agent.state import StarterState, transition

OPEN_EXIT_STATES = (StarterState.EXIT_CANDIDATE, StarterState.RECONCILING, StarterState.AWAITING_INHERITED)
CLOSED_STATES = (StarterState.FINALIZED, StarterState.UNRESOLVED)


@dataclass(frozen=True)
class Output:
    kind: str  # status | capsule | exit_detected | exit_final
    text: str
    pitcher_id: int | None = None


@dataclass
class StarterTrack:
    pitcher_id: int
    name: str
    team: str
    side: str  # fielding side: "home" pitches the top halves
    state: StarterState = StarterState.ACTIVE
    exit_index: int | None = None  # half-inning index where the replacement first appeared

    @property
    def label(self) -> str:
        return self.name.split()[-1].upper()


def half_index(inning: int, half: Half) -> int:
    return 2 * (inning - 1) + (0 if half is Half.TOP else 1)


def _half_label(index: int) -> str:
    return f"{'T' if index % 2 == 0 else 'B'}{index // 2 + 1}"


def _fielding_side(half: Half) -> str:
    return "home" if half is Half.TOP else "away"


class GameTracker:
    def __init__(self, *, lag: int = 1, capsules: bool = True) -> None:
        self.lag = lag
        self.capsules = capsules
        self.starters: dict[str, StarterTrack] = {}
        self.info: mlb.GameInfo | None = None
        self._printed: set[tuple[int, int]] = set()
        self._first = True
        self._announced_waiting = False
        self._pitches: list[Pitch] = []
        self._pas: list[PlateAppearance] = []

    # -- public state -------------------------------------------------------

    @property
    def is_final(self) -> bool:
        return self.info is not None and self.info.status == "Final"

    @property
    def is_preview(self) -> bool:
        return self.info is None or self.info.status == "Preview"

    @property
    def done(self) -> bool:
        """Game over and every starter's line is closed out."""
        return self.is_final and all(s.state in CLOSED_STATES for s in self.starters.values())

    def starter_capsule(self, s: StarterTrack, *, provisional: bool = False) -> str:
        return capsule(
            window_line(self._pitches, self._pas, s.pitcher_id),
            window_mix(self._pitches, s.pitcher_id),
            window_hits(self._pas, s.pitcher_id),
            include_ip=True,
            mix_provisional=provisional,
        )

    # -- update -------------------------------------------------------------

    def update(self, feed: dict[str, Any]) -> list[Output]:
        self.info = info = mlb.game_info(feed)
        self._pitches, self._pas = mlb.normalize(feed)
        names = {int(k[2:]): v for k, v in feed["gameData"].get("players", {}).items()}
        out: list[Output] = []

        if not self._pas:
            self._first = False  # watching from the start: nothing to catch up on
            if not self._announced_waiting:
                self._announced_waiting = True
                out.append(Output("status", f"Connected: {info.away.abbrev} @ {info.home.abbrev} {info.date} | {info.detailed_status}. Waiting for first pitch."))  # fmt: skip
            return out

        for pa in self._pas:
            side = _fielding_side(pa.half)
            if side not in self.starters:
                person = names.get(pa.pitcher_id, {})
                self.starters[side] = StarterTrack(
                    pa.pitcher_id, person.get("fullName", str(pa.pitcher_id)), getattr(info, side).abbrev, side
                )

        outs: dict[int, int] = {}
        for pa in self._pas:
            k = half_index(pa.inning, pa.half)
            outs[k] = outs.get(k, 0) + pa.outs_on_play
        last = max(outs)

        def complete(k: int) -> bool:
            return k < last or outs.get(k, 0) >= 3 or (self.is_final and k <= last)

        latest_complete = max((k for k in outs if complete(k)), default=-1)

        exit_outputs = self._exits(feed, complete)
        if self._first:
            out.append(self._catch_up(info))
        elif self.capsules:
            out.extend(self._due_capsules(latest_complete))
        self._mark_due(latest_complete)

        out.extend(exit_outputs)
        self._first = False
        return out

    def _pitched_halves(self, s: StarterTrack) -> list[int]:
        return sorted({half_index(p.inning, p.half) for p in self._pitches if p.pitcher_id == s.pitcher_id})

    def _is_due(self, k: int, latest_complete: int) -> bool:
        return self.is_final or latest_complete >= k + self.lag

    def _due_capsules(self, latest_complete: int) -> list[Output]:
        due = [
            (k, s)
            for s in self.starters.values()
            for k in self._pitched_halves(s)
            if (s.pitcher_id, k) not in self._printed and self._is_due(k, latest_complete)
        ]
        outputs = []
        for k, s in sorted(due, key=lambda d: d[0]):
            window = InningWindow(k // 2 + 1, k // 2 + 1)
            body = capsule(
                window_line(self._pitches, self._pas, s.pitcher_id, window),
                window_mix(self._pitches, s.pitcher_id, window),
                window_hits(self._pas, s.pitcher_id, window),
            )
            outputs.append(Output("capsule", f"{s.label} {_half_label(k)}\n{body}", s.pitcher_id))
        return outputs

    def _mark_due(self, latest_complete: int) -> None:
        for s in self.starters.values():
            for k in self._pitched_halves(s):
                if self._is_due(k, latest_complete):
                    self._printed.add((s.pitcher_id, k))

    def _catch_up(self, info: mlb.GameInfo) -> Output:
        """First look at a game already under way: one cumulative line per active starter, no backlog.

        Starters who have already exited are covered by their exit output instead.
        """
        lines = [f"Connected: {info.away.abbrev} @ {info.home.abbrev} {info.date} | {info.detailed_status}"]
        for side in ("away", "home"):
            s = self.starters.get(side)
            if s and s.state is StarterState.ACTIVE and any(p.pitcher_id == s.pitcher_id for p in self._pitches):
                lines.append(f"\n{s.label} ({s.team}) so far\n{self.starter_capsule(s)}")
        return Output("status", "\n".join(lines))

    # -- starter exits ------------------------------------------------------

    def _exits(self, feed: dict[str, Any], complete) -> list[Output]:
        out: list[Output] = []
        for s in self.starters.values():
            if s.state is StarterState.ACTIVE:
                replaced = next(
                    (pa for pa in self._pas if _fielding_side(pa.half) == s.side and pa.pitcher_id != s.pitcher_id), None
                )
                if replaced is None and not self.is_final:
                    continue
                s.exit_index = half_index(replaced.inning, replaced.half) if replaced else None
                s.state = transition(s.state, StarterState.EXIT_CANDIDATE)
                just_detected = True
            elif s.state in OPEN_EXIT_STATES:
                just_detected = False
            else:
                continue

            mid_inning = s.exit_index is not None and s.exit_index in self._pitched_halves(s)
            result = evaluate_gate(
                window_line(self._pitches, self._pas, s.pitcher_id),
                {"mlb_boxscore": mlb.box_line(feed["liveData"]["boxscore"], s.pitcher_id)},
                inherited_runners_on_base=mid_inning and not complete(s.exit_index),
            )
            if s.state is StarterState.EXIT_CANDIDATE:
                s.state = transition(s.state, StarterState.RECONCILING)
            if result.state is not s.state:
                s.state = transition(s.state, result.state)

            if s.state is StarterState.FINALIZED:
                out.append(Output("exit_final", f"{s.label} FINAL\n{self.starter_capsule(s)}", s.pitcher_id))
            elif just_detected:
                out.append(Output("exit_detected", f"{s.label}: {result.status_line}", s.pitcher_id))
        return out

    def give_up(self) -> list[Output]:
        """Stop reconciling: print the best-known line, labelled as not source-complete."""
        out = []
        for s in self.starters.values():
            if s.state in OPEN_EXIT_STATES:
                s.state = transition(s.state, StarterState.UNRESOLVED)
                out.append(
                    Output("exit_final", f"{s.label} FINAL (not source-complete)\n{self.starter_capsule(s)}", s.pitcher_id)
                )
        return out
