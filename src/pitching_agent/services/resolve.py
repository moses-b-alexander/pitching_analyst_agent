"""Find the game to follow from team names instead of a gamePk.

Works on the MLB schedule payload (hydrate=team,probablePitcher). Never guesses between
different matchups: if the words fit more than one, the caller lists them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pitching_agent.text import GENERIC, tokens

_FILLER = {"at", "vs", "v", "versus", "game", "tonight", "today"}


def team_keys(team: dict[str, Any]) -> set[str]:
    """Words that identify a team: abbreviation, city, nickname."""
    words = {team.get("abbreviation", "").lower()}
    for field in ("name", "teamName", "locationName", "clubName"):
        words.update(tokens(team.get(field) or ""))
    return words - GENERIC - {""}


def _team_score(team: dict[str, Any], words: list[str]) -> int:
    """2 if the query has the team's abbreviation or full nickname ("white sox"), 1 for any identifying word, else 0."""
    phrase = f" {' '.join(words)} "
    nickname = " ".join(tokens(team.get("teamName") or ""))
    if team.get("abbreviation", "").lower() in words or (nickname and f" {nickname} " in phrase):
        return 2
    return 1 if set(words) & team_keys(team) else 0


def match_games(games: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    """The games that fit the query best: naming both teams beats one, and an exact nickname
    beats a shared word, so "white sox" is not also the Red Sox and "chicago" stays ambiguous."""
    words = [w for w in tokens(query) if w not in _FILLER]
    scored = [(sum(_team_score(g["teams"][side]["team"], words) for side in ("away", "home")), g) for g in games]
    best = max((n for n, _ in scored), default=0)
    return [g for n, g in scored if n == best] if best else []


def named_teams(teams: list[dict[str, Any]], query: str) -> tuple[list[dict[str, Any]], bool]:
    """Which teams the query names, and whether that is ambiguous.

    "rangers twins" names two teams (different words point at each). "chicago" or "sox"
    is one word that fits two teams: ambiguous, so the caller asks instead of guessing.
    """
    words = [w for w in tokens(query) if w not in _FILLER]
    scored = [(_team_score(t, words), t) for t in teams]
    best = max((n for n, _ in scored), default=0)
    if not best:
        return [], False
    found = [t for n, t in scored if n == best]
    if len(found) == 1:
        return found, False
    evidence = [frozenset(set(words) & team_keys(t)) for t in found]
    distinct = len(found) == 2 and not (evidence[0] & evidence[1])
    return found, not distinct


_NOT_PLAYED = {"Postponed", "Cancelled", "Suspended"}


def latest_played(games: list[dict[str, Any]], opponent_id: int | None = None) -> dict[str, Any] | None:
    """The most recent game that is in progress or was actually played, optionally against one opponent."""

    def played(g: dict[str, Any]) -> bool:
        status = g["status"]
        if status["abstractGameState"] == "Live":
            return True
        return status["abstractGameState"] == "Final" and status["detailedState"] not in _NOT_PLAYED

    def involves(g: dict[str, Any]) -> bool:
        return opponent_id is None or opponent_id in (g["teams"]["away"]["team"]["id"], g["teams"]["home"]["team"]["id"])

    eligible = [g for g in games if played(g) and involves(g)]
    return max(eligible, key=lambda g: g["gameDate"], default=None)


def pick(matches: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The one game to follow, or None if the matches are ambiguous.

    A doubleheader (same two teams) resolves to the game in progress, else the next one not yet final.
    """
    if len(matches) == 1:
        return matches[0]
    matchups = {(g["teams"]["away"]["team"]["id"], g["teams"]["home"]["team"]["id"]) for g in matches}
    if len(matchups) != 1:
        return None
    ordered = sorted(matches, key=lambda g: g["gameDate"])
    for state in ("Live", "Preview"):
        for g in ordered:
            if g["status"]["abstractGameState"] == state:
                return g
    return None  # both games of the doubleheader are over


def describe(game: dict[str, Any]) -> str:
    away, home = game["teams"]["away"], game["teams"]["home"]
    start = datetime.fromisoformat(game["gameDate"].replace("Z", "+00:00")).astimezone()

    def starter(side: dict[str, Any]) -> str:
        return (side.get("probablePitcher") or {}).get("fullName", "TBD")

    number = f" (game {game['gameNumber']})" if game.get("doubleHeader") in ("Y", "S") else ""
    return (
        f"{game['gamePk']}  {away['team']['abbreviation']:>3} @ {home['team']['abbreviation']:<3}"
        f"  {start:%I:%M %p}  {game['status']['detailedState']:<12}  {starter(away)} vs {starter(home)}{number}"
    )
