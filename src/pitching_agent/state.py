"""Session modes and the starter-exit completeness state machine."""

from __future__ import annotations

from enum import Enum


class SessionMode(str, Enum):
    PREGAME = "pregame"
    LIVE = "live"
    POSTGAME = "postgame"
    OUT_OF_SCOPE = "out_of_scope"  # bullpen/opener game that doesn't fit the SP contract


class StarterState(str, Enum):
    ACTIVE = "active"
    EXIT_CANDIDATE = "exit_candidate"
    RECONCILING = "reconciling"
    AWAITING_INHERITED = "awaiting_inherited_runner_resolution"
    FINALIZED = "finalized"
    UNRESOLVED = "unresolved"  # gave up polling (decisions.md #8)


_ALLOWED: dict[StarterState, set[StarterState]] = {
    StarterState.ACTIVE: {StarterState.EXIT_CANDIDATE},
    # A candidate may be a false alarm (e.g. mound visit misread) and revert.
    StarterState.EXIT_CANDIDATE: {StarterState.RECONCILING, StarterState.ACTIVE, StarterState.UNRESOLVED},
    StarterState.RECONCILING: {
        StarterState.AWAITING_INHERITED,
        StarterState.FINALIZED,
        StarterState.UNRESOLVED,
    },
    StarterState.AWAITING_INHERITED: {StarterState.RECONCILING, StarterState.FINALIZED, StarterState.UNRESOLVED},
    StarterState.FINALIZED: set(),
    StarterState.UNRESOLVED: {StarterState.RECONCILING},
}


class InvalidTransition(ValueError):
    pass


def transition(current: StarterState, target: StarterState) -> StarterState:
    if target not in _ALLOWED[current]:
        raise InvalidTransition(f"{current.value} -> {target.value}")
    return target
