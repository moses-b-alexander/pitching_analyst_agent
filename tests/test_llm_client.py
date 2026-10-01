import asyncio
import json

import httpx
import pytest

from pitching_agent.config import LLMConfig
from pitching_agent.llm.client import LLMClient, LLMUnavailable

CFG = LLMConfig(base_url="http://test/v1/", model="qwen3:8b")


def _client(handler, cfg=CFG):
    return LLMClient(cfg, httpx.AsyncClient(base_url=cfg.base_url, transport=httpx.MockTransport(handler)))


def _reply(content):
    return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": content}}]})


def test_chat_sends_model_and_strips_thinking():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return _reply("<think>\ncounting pitches...\n</think>\n\nCurve is living below the zone.")

    out = asyncio.run(_client(handler).chat([{"role": "user", "content": "hi"}]))
    assert out == "Curve is living below the zone."
    assert seen["url"] == "http://test/v1/chat/completions"
    assert seen["body"]["model"] == "qwen3:8b" and "response_format" not in seen["body"]


def test_chat_json_requests_schema_and_parses():
    schema = {"type": "object", "properties": {"cls": {"type": "string"}}, "required": ["cls"]}

    def handler(request):
        body = json.loads(request.content)
        assert body["response_format"]["json_schema"]["schema"] == schema
        assert body["temperature"] == 0.0
        return _reply('{"cls": "location_spatial"}')

    assert asyncio.run(_client(handler).chat_json([{"role": "user", "content": "x"}], schema)) == {"cls": "location_spatial"}


def test_no_model_configured_is_unavailable():
    cfg = LLMConfig(base_url="http://test/v1/", model=None)
    with pytest.raises(LLMUnavailable, match="no model configured"):
        asyncio.run(_client(lambda r: _reply("x"), cfg).chat([]))


def test_unreachable_endpoint_is_unavailable():
    def handler(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(LLMUnavailable, match="cannot reach"):
        asyncio.run(_client(handler).chat([{"role": "user", "content": "hi"}]))


def test_http_error_is_unavailable():
    with pytest.raises(LLMUnavailable, match="404"):
        asyncio.run(_client(lambda r: httpx.Response(404, text="model not found")).chat([{"role": "user", "content": "x"}]))
