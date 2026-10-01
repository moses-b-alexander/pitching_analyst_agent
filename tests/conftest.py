import gzip
import json
from pathlib import Path

import pandas as pd
import pytest

FIXTURES = Path(__file__).parent / "fixtures"

GAME = 823652  # TEX @ MIN, 2026-09-25: deGrom vs Joe Ryan
DEGROM, RYAN = 594798, 657746
MID_EXIT_TIMECODE = "20260926_014558"  # ~90 s after deGrom removed, B5, PA in progress


def _require(name: str) -> Path:
    path = FIXTURES / name
    if not path.exists():
        pytest.skip(f"{name} missing; run: python scripts/fetch_fixtures.py")
    return path


def load_json_gz(name: str):
    with gzip.open(_require(name), "rt", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def final_feed():
    return load_json_gz(f"feed_{GAME}_final.json.gz")


@pytest.fixture(scope="session")
def mid_feed():
    return load_json_gz(f"feed_{GAME}_{MID_EXIT_TIMECODE}.json.gz")


@pytest.fixture(scope="session")
def boxscore():
    return load_json_gz(f"box_{GAME}.json.gz")


@pytest.fixture(scope="session")
def savant_season_ryan():
    """Ryan's full 2026 regular season, including game 823652."""
    return pd.read_csv(_require(f"savant_season_2026_{RYAN}.csv.gz"))


@pytest.fixture(scope="session")
def savant_heart_ryan():
    """The pitches Savant's own attack-zone filter (heart, zones 1-9) returns for Ryan's 2026 season."""
    return pd.read_csv(_require(f"savant_heart_2026_{RYAN}.csv.gz"))


@pytest.fixture(scope="session")
def savant_ryan():
    return pd.read_csv(_require(f"savant_{GAME}_{RYAN}.csv.gz"))
