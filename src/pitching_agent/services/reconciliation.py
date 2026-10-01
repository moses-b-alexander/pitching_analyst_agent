"""Starter-exit completeness gate (architecture §5, SKILL.md §8).

Policy (decisions.md #6): the line computed from the MLB feed's plays is what gets printed.
The feed's boxscore is a second representation of the same game; while the two disagree
the line is not source-complete, so finalization waits. A missing corroborating line
(None) does not block.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields

from pitching_agent.models import PitcherLine
from pitching_agent.state import StarterState

CORE_FIELDS = ("outs", "pitches", "strikes", "hits", "runs", "earned_runs", "walks", "strikeouts")


def missing_core(line: PitcherLine) -> list[str]:
    return [f for f in CORE_FIELDS if getattr(line, f) is None]


def disagreements(primary: PitcherLine, other: PitcherLine) -> list[str]:
    """Fields both sources report that differ."""
    out = []
    for f in fields(PitcherLine):
        a, b = getattr(primary, f.name), getattr(other, f.name)
        if a is not None and b is not None and a != b:
            out.append(f.name)
    return out


@dataclass
class GateResult:
    state: StarterState
    missing: list[str] = field(default_factory=list)
    conflicts: dict[str, list[str]] = field(default_factory=dict)

    @property
    def status_line(self) -> str:
        if self.state is StarterState.FINALIZED:
            return "Starter final line source-complete."
        if self.state is StarterState.AWAITING_INHERITED:
            return "Starter exit detected; R/ER pending inherited runners."
        return "Starter exit detected; final line not yet source-complete."


def evaluate_gate(
    primary: PitcherLine,
    corroborating: dict[str, PitcherLine | None],
    *,
    inherited_runners_on_base: bool,
) -> GateResult:
    missing = missing_core(primary)
    conflicts = {
        name: diff
        for name, line in corroborating.items()
        if line is not None and (diff := disagreements(primary, line))
    }
    # Pitch count / mix and completed outcomes can freeze; R/ER wait on inherited runners.
    if inherited_runners_on_base:
        return GateResult(StarterState.AWAITING_INHERITED, missing, conflicts)
    if missing or conflicts:
        return GateResult(StarterState.RECONCILING, missing, conflicts)
    return GateResult(StarterState.FINALIZED, missing, conflicts)
