import copy

import pytest
from conftest import GAME, load_json_gz

from pitching_agent.services.resolve import describe, match_games, pick, team_keys

CUBS_G1, CUBS_G2, WHITE_SOX = 824703, 824706, 824544


@pytest.fixture(scope="module")
def games():
    """2026-09-25: 17 games, including CHC@BOS and BAL@NYY doubleheaders."""
    data = load_json_gz("schedule_2026-09-25.json.gz")
    return [g for d in data["dates"] for g in d["games"]]


def ids(found):
    return sorted(g["gamePk"] for g in found)


@pytest.mark.parametrize("query", ["twins", "Twins", "MIN", "minnesota", "rangers", "TEX MIN", "rangers at twins", "texas vs minnesota tonight"])
def test_one_team_or_both_finds_the_game(games, query):
    found = match_games(games, query)
    assert ids(found) == [GAME]
    assert pick(found)["gamePk"] == GAME


def test_naming_both_teams_beats_a_shared_city(games):
    assert ids(match_games(games, "chicago")) == sorted([CUBS_G1, CUBS_G2, WHITE_SOX])
    assert pick(match_games(games, "chicago")) is None  # two different matchups: never guess
    assert ids(match_games(games, "rockies chicago")) == [WHITE_SOX]


def test_full_nickname_beats_a_shared_word(games):
    assert ids(match_games(games, "white sox")) == [WHITE_SOX]
    assert ids(match_games(games, "red sox")) == [CUBS_G1, CUBS_G2]  # CHC @ BOS doubleheader
    assert ids(match_games(games, "sox")) == sorted([CUBS_G1, CUBS_G2, WHITE_SOX])  # genuinely ambiguous
    assert ids(match_games(games, "CWS")) == [WHITE_SOX]


def test_generic_words_do_not_match_on_their_own(games):
    assert match_games(games, "new") == []
    assert match_games(games, "narwhals") == []
    assert "new" not in team_keys({"abbreviation": "NYY", "name": "New York Yankees", "teamName": "Yankees"})


def test_doubleheader_resolves_to_live_then_upcoming(games):
    found = match_games(games, "cubs")
    assert ids(found) == [CUBS_G1, CUBS_G2]
    assert pick(found) is None  # both over

    def with_states(first, second):
        pair = copy.deepcopy(sorted(found, key=lambda g: g["gameDate"]))
        pair[0]["status"]["abstractGameState"], pair[1]["status"]["abstractGameState"] = first, second
        return pair

    assert pick(with_states("Live", "Preview"))["gamePk"] == CUBS_G1
    assert pick(with_states("Final", "Live"))["gamePk"] == CUBS_G2
    assert pick(with_states("Final", "Preview"))["gamePk"] == CUBS_G2
    assert pick(with_states("Preview", "Preview"))["gamePk"] == CUBS_G1


def test_describe(games):
    line = describe(next(g for g in games if g["gamePk"] == GAME))
    assert line.startswith(f"{GAME}  TEX @ MIN  ") and line.endswith("Final         Jacob deGrom vs Joe Ryan")
    assert describe(next(g for g in games if g["gamePk"] == CUBS_G2)).endswith("(game 2)")
