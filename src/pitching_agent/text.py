"""Shared word matching for names typed by the viewer."""

from __future__ import annotations

import re

# Team-name words too generic to identify a team on their own.
GENERIC = {"new", "los", "san", "st", "city", "bay", "red", "white", "blue", "the"}


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())
