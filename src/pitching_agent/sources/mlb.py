"""MLB Stats API adapter — authoritative live source (decisions.md #6).

The endpoints are public but undocumented; keep every schema assumption in this
module and cover it with recorded fixtures under tests/fixtures/.

Field mapping to Savant conventions (verified pitch-by-pitch against Savant CSV
for game 823652, see tests/test_mlb_normalize.py):

- pfx_x = -breaks.breakHorizontal / 12, pfx_z = breaks.breakVerticalInduced / 12  (feet)
  coordinates.pfxX/pfxZ are a different (40 ft) convention and are NOT used.
- release_pos_x/z = trajectory extrapolated to y = 60.5 - extension
  (coordinates.x0/z0 are at y = 50 ft, not release).
- plate_x/z = trajectory at y = 17/24 ft (mid-plate). Raw pX/pZ sit ~0.9 in higher.
- Official strikes include balls in play (details.isInPlay), which have isStrike=False.
- Pitch counts on playEvents are post-pitch; Savant balls/strikes are pre-pitch.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import httpx

from pitching_agent.models import Half, Pitch, PitcherLine, PlateAppearance
from pitching_agent.sources.base import USER_AGENT

BASE = "https://statsapi.mlb.com"
PLATE_Y_FT = 17 / 24
MOUND_TO_PLATE_FT = 60.5

HIT_LETTERS = {"single": "S", "double": "D", "triple": "T"}


class MLBStatsAdapter:
    name = "mlb_live"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(
            base_url=BASE, headers={"User-Agent": USER_AGENT}, timeout=15.0
        )

    async def _get(self, path: str, **params: Any) -> dict[str, Any]:
        resp = await self._client.get(path, params=params or None)
        resp.raise_for_status()
        return resp.json()

    async def resolve_games(self, on: date) -> list[dict[str, Any]]:
        data = await self._get(
            "/api/v1/schedule", sportId=1, date=on.isoformat(), hydrate="probablePitcher,team"
        )
        return [g for d in data.get("dates", []) for g in d.get("games", [])]

    async def live_feed(self, game_id: int, timecode: str | None = None) -> dict[str, Any]:
        """Full GUMBO feed; `timecode` (YYYYMMDD_HHMMSS) fetches a historical snapshot for replay."""
        params = {"timecode": timecode} if timecode else {}
        return await self._get(f"/api/v1.1/game/{game_id}/feed/live", **params)

    async def timecodes(self, game_id: int) -> list[str]:
        resp = await self._client.get(f"/api/v1.1/game/{game_id}/feed/live/timestamps")
        resp.raise_for_status()
        return resp.json()

    async def boxscore(self, game_id: int) -> dict[str, Any]:
        return await self._get(f"/api/v1/game/{game_id}/boxscore")

    async def person(self, player_id: int) -> dict[str, Any]:
        data = await self._get(f"/api/v1/people/{player_id}")
        return data["people"][0]

    async def pitcher_line(self, game_id: int, pitcher_id: int) -> PitcherLine | None:
        return box_line(await self.boxscore(game_id), pitcher_id)

    async def aclose(self) -> None:
        await self._client.aclose()


# ---------------------------------------------------------------------------
# Normalization (pure functions over the raw feed)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TeamInfo:
    id: int
    abbrev: str
    name: str


@dataclass(frozen=True)
class GameInfo:
    game_id: int
    date: str
    away: TeamInfo
    home: TeamInfo
    status: str  # Preview | Live | Final
    detailed_status: str
    probable_away: int | None
    probable_home: int | None
    inning: int | None
    half: Half | None
    timecode: str | None


def game_info(feed: dict[str, Any]) -> GameInfo:
    gd = feed["gameData"]
    ls = feed["liveData"].get("linescore", {})

    def team(side: str) -> TeamInfo:
        t = gd["teams"][side]
        return TeamInfo(t["id"], t["abbreviation"], t["name"])

    def probable(side: str) -> int | None:
        return (gd.get("probablePitchers", {}).get(side) or {}).get("id")

    half = ls.get("inningHalf")
    return GameInfo(
        game_id=feed["gamePk"],
        date=gd["datetime"]["officialDate"],
        away=team("away"),
        home=team("home"),
        status=gd["status"]["abstractGameState"],
        detailed_status=gd["status"]["detailedState"],
        probable_away=probable("away"),
        probable_home=probable("home"),
        inning=ls.get("currentInning"),
        half=Half(half.lower()) if half else None,
        timecode=feed.get("metaData", {}).get("timeStamp"),
    )


def actual_starters(feed: dict[str, Any]) -> dict[str, int | None]:
    """First pitcher used by each side, from the live boxscore (None before first pitch)."""
    teams = feed["liveData"]["boxscore"]["teams"]
    return {side: (teams[side]["pitchers"] or [None])[0] for side in ("away", "home")}


def _at_y(c: dict[str, float], y: float) -> tuple[float, float]:
    """Constant-acceleration trajectory position (x, z) where the pitch crosses depth y."""
    a, b, cc = 0.5 * c["aY"], c["vY0"], c["y0"] - y
    t = (-b - math.sqrt(b * b - 4 * a * cc)) / (2 * a)
    return (
        c["x0"] + c["vX0"] * t + 0.5 * c["aX"] * t * t,
        c["z0"] + c["vZ0"] * t + 0.5 * c["aZ"] * t * t,
    )


_TRAJ_KEYS = ("x0", "y0", "z0", "vX0", "vY0", "vZ0", "aX", "aY", "aZ")


def _pitch_geometry(pd_: dict[str, Any]) -> dict[str, float | None]:
    c = pd_.get("coordinates", {})
    b = pd_.get("breaks", {})
    ext = pd_.get("extension")
    out: dict[str, float | None] = {
        "plate_x": c.get("pX"),
        "plate_z": c.get("pZ"),
        "release_pos_x": None,
        "release_pos_z": None,
        "pfx_x": -b["breakHorizontal"] / 12 if b.get("breakHorizontal") is not None else None,
        "pfx_z": b["breakVerticalInduced"] / 12 if b.get("breakVerticalInduced") is not None else None,
    }
    if all(c.get(k) is not None for k in _TRAJ_KEYS):
        out["plate_x"], out["plate_z"] = _at_y(c, PLATE_Y_FT)
        if ext is not None:
            out["release_pos_x"], out["release_pos_z"] = _at_y(c, MOUND_TO_PLATE_FT - ext)
    return out


def _ts(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def normalize(feed: dict[str, Any]) -> tuple[list[Pitch], list[PlateAppearance]]:
    """Every pitch and plate appearance in the feed, attributed to the pitcher who threw it.

    Mid-PA pitching changes are handled by tracking pitching_substitution events, so
    pitches before the change stay with the outgoing pitcher.
    """
    game_id = feed["gamePk"]
    pitches: list[Pitch] = []
    pas: list[PlateAppearance] = []
    on_mound: dict[str, int] = {}  # fielding side -> pitcher id
    prev_outs = 0
    prev_half_key: tuple[int, str] | None = None

    for play in feed["liveData"]["plays"]["allPlays"]:
        about, matchup = play["about"], play["matchup"]
        half = Half(about["halfInning"])
        fielding = "home" if half is Half.TOP else "away"
        half_key = (about["inning"], half.value)
        if half_key != prev_half_key:
            prev_outs, prev_half_key = 0, half_key
        on_mound.setdefault(fielding, matchup["pitcher"]["id"])

        balls = strikes = 0
        last_hit_data: dict[str, Any] | None = None
        for ev in play["playEvents"]:
            det = ev.get("details", {})
            if det.get("eventType") == "pitching_substitution" and ev.get("player"):
                on_mound[fielding] = ev["player"]["id"]
            if ev.get("isPitch"):
                pd_ = ev.get("pitchData", {})
                hd = ev.get("hitData") or {}
                if hd:
                    last_hit_data = hd
                geo = _pitch_geometry(pd_)
                pitches.append(
                    Pitch(
                        game_id=game_id,
                        pitcher_id=on_mound[fielding],
                        batter_id=matchup["batter"]["id"],
                        at_bat_number=about["atBatIndex"] + 1,
                        pitch_number=ev["pitchNumber"],
                        inning=about["inning"],
                        half=half,
                        balls=balls,
                        strikes=strikes,
                        pitch_type=(det.get("type") or {}).get("code"),
                        description=(det.get("call") or {}).get("description") or det.get("description"),
                        is_strike=bool(det.get("isStrike") or det.get("isInPlay")),
                        release_speed=pd_.get("startSpeed"),
                        release_extension=pd_.get("extension"),
                        sz_top=pd_.get("strikeZoneTop"),
                        sz_bot=pd_.get("strikeZoneBottom"),
                        spin_rate=(pd_.get("breaks") or {}).get("spinRate"),
                        launch_speed=hd.get("launchSpeed"),
                        launch_angle=hd.get("launchAngle"),
                        timestamp=_ts(ev.get("startTime")),
                        play_id=ev.get("playId"),
                        **geo,
                    )
                )
            if "count" in ev:
                balls, strikes = ev["count"]["balls"], ev["count"]["strikes"]

        complete = bool(about.get("isComplete"))
        event_type = play["result"].get("eventType") if complete else None
        outs_after = play["count"]["outs"]
        pitcher_id = matchup["pitcher"]["id"]
        runs = [
            ((r["details"].get("responsiblePitcher") or {}).get("id", pitcher_id), bool(r["details"].get("earned")))
            for r in play.get("runners", [])
            if r["movement"].get("end") == "score"
        ]
        pas.append(
            PlateAppearance(
                game_id=game_id,
                at_bat_index=about["atBatIndex"],
                inning=about["inning"],
                half=half,
                pitcher_id=pitcher_id,
                batter_id=matchup["batter"]["id"],
                bat_side=matchup["batSide"]["code"],
                is_complete=complete,
                event_type=event_type,
                outs_on_play=max(outs_after - prev_outs, 0) if complete else 0,
                hit_code=hit_code(event_type, last_hit_data) if complete else None,
                runs=runs,
            )
        )
        if complete:
            prev_outs = outs_after

    return pitches, pas


def hit_code(event_type: str | None, hit_data: dict[str, Any] | None) -> str | None:
    """Retrosheet-style hit notation. Uses only the fielder location the feed reports; never guesses."""
    if event_type == "home_run":
        return "HR"
    letter = HIT_LETTERS.get(event_type or "")
    if letter is None:
        return None
    return letter + ((hit_data or {}).get("location") or "")


def box_line(box: dict[str, Any], pitcher_id: int) -> PitcherLine | None:
    """Pitcher line from a boxscore (standalone endpoint or feed liveData.boxscore)."""
    for side in ("away", "home"):
        player = box["teams"][side]["players"].get(f"ID{pitcher_id}")
        if player and player.get("stats", {}).get("pitching"):
            s = player["stats"]["pitching"]
            return PitcherLine(
                outs=s.get("outs"),
                pitches=s.get("numberOfPitches"),
                strikes=s.get("strikes"),
                hits=s.get("hits"),
                runs=s.get("runs"),
                earned_runs=s.get("earnedRuns"),
                walks=s.get("baseOnBalls"),
                strikeouts=s.get("strikeOuts"),
                home_runs=s.get("homeRuns"),
                batters_faced=s.get("battersFaced"),
            )
    return None


def truncate_feed(feed: dict[str, Any], n_plays: int) -> dict[str, Any]:
    """The feed as it would have looked after its first `n_plays` plays (offline replay and tests).

    Game state is rebuilt from the last kept play. The boxscore is cleared because it
    cannot be rewound, so replayed states carry no corroborating line.
    """
    plays = feed["liveData"]["plays"]["allPlays"]
    if n_plays >= len(plays):
        return feed
    kept = plays[:n_plays]
    box = feed["liveData"]["boxscore"]
    linescore: dict[str, Any] = {}
    if kept:
        about = kept[-1]["about"]
        linescore = {"currentInning": about["inning"], "inningHalf": about["halfInning"].capitalize()}
    return {
        **feed,
        "metaData": {**feed.get("metaData", {}), "timeStamp": f"replay_{n_plays:04d}", "wait": 0},
        "gameData": {
            **feed["gameData"],
            "status": {
                "abstractGameState": "Live" if kept else "Preview",
                "detailedState": "In Progress" if kept else "Pre-Game",
            },
        },
        "liveData": {
            **feed["liveData"],
            "plays": {**feed["liveData"]["plays"], "allPlays": kept},
            "linescore": linescore,
            "boxscore": {
                **box,
                "teams": {s: {**box["teams"][s], "players": {}, "pitchers": []} for s in ("away", "home")},
            },
        },
    }
