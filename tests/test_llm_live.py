"""Opt-in checks against the real configured model: RUN_LLM_TESTS=1 pytest tests/test_llm_live.py

Skipped by default because they need the local model server and take a few seconds.
"""

import asyncio
import os
from pathlib import Path

import pytest

from pitching_agent.config import load_config
from pitching_agent.llm.client import LLMClient
from pitching_agent.llm.prompts import CLASSIFY_SCHEMA, CLASSIFY_SYSTEM, METRICS

pytestmark = pytest.mark.skipif(os.environ.get("RUN_LLM_TESTS") != "1", reason="set RUN_LLM_TESTS=1 to run")

# None of these appear as examples in the prompt.
PROBES = {
    "curve is buried way more": "location_spatial",
    "he's lost a couple ticks since the 3rd": "fatigue_trend",
    "way more sweepers than normal": "usage_proportion",
    "ryan is throwing a ton of sweepers": "usage_proportion",
    "his splitter has more drop tonight": "continuous_shape",
    "only throwing the change to lefties": "matchup_interaction",
    "they look late on the heater": "hitter_response",
    "he goes changeup every time after a sinker": "sequence_transition",
    "he can't hit his spots with the slider": "command_precision",
}


def test_classifies_unseen_observations():
    cfg = load_config(Path(__file__).resolve().parents[1] / "config.yaml").llm

    async def run():
        client = LLMClient(cfg)
        try:
            out = {}
            for text in PROBES:
                out[text] = await client.chat_json(
                    [{"role": "system", "content": CLASSIFY_SYSTEM}, {"role": "user", "content": text}], CLASSIFY_SCHEMA
                )
            return out
        finally:
            await client.aclose()

    results = asyncio.run(run())
    wrong = {t: r["primary_class"] for t, r in results.items() if r["primary_class"] != PROBES[t]}
    assert all(r["metric"] in METRICS for r in results.values())
    assert len(wrong) <= 1, wrong  # small models are allowed one miss
    for text in ("way more sweepers than normal", "ryan is throwing a ton of sweepers"):
        assert results[text]["metric"] == "usage_share", (text, results[text])
    seq = results["he goes changeup every time after a sinker"]
    assert (seq["pitch_type"], seq["previous_pitch_type"], seq["metric"]) == ("CH", "SI", "share_after_previous_pitch_type"), seq
    assert results["curve is buried way more"]["previous_pitch_type"] is None
