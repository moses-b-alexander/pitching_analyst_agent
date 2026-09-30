import pytest

from pitching_agent.analytics.windows import InningWindow
from pitching_agent.models import InferenceType
from pitching_agent.services.hypothesis import inference_type


@pytest.mark.parametrize(
    "text,expected",
    [("I2", (2, 2)), ("2", (2, 2)), ("I1–I3", (1, 3)), ("I3-I5", (3, 5)), ("3 - 5", (3, 5))],
)
def test_parse(text, expected):
    w = InningWindow.parse(text)
    assert (w.start, w.end) == expected


@pytest.mark.parametrize("bad", ["", "I0", "I5-I3", "fifth"])
def test_parse_rejects(bad):
    with pytest.raises(ValueError):
        InningWindow.parse(bad)


def test_str_roundtrip():
    assert str(InningWindow.parse("I1-I3")) == "I1–I3"
    assert str(InningWindow.parse("I2")) == "I2"


def test_prospective_when_frozen_before_later_window():
    assert inference_type(InningWindow(2, 2), InningWindow(3, 5), frozen_before_test=True) is InferenceType.PROSPECTIVE


def test_exploratory_when_testing_generating_window():
    assert inference_type(InningWindow(1, 3), InningWindow(1, 3), frozen_before_test=True) is InferenceType.EXPLORATORY


def test_exploratory_when_overlapping_or_not_frozen():
    assert inference_type(InningWindow(1, 3), InningWindow(3, 5), frozen_before_test=True) is InferenceType.EXPLORATORY
    assert inference_type(InningWindow(2, 2), InningWindow(3, 5), frozen_before_test=False) is InferenceType.EXPLORATORY
