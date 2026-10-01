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
