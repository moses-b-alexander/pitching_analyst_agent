"""Chat client for any OpenAI-compatible endpoint (Ollama, llama.cpp, hosted open-weight providers).

The model never supplies numbers: callers pass computed stat lines and test results in,
and use `json_schema` to force menu choices into valid JSON.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

from pitching_agent.config import LLMConfig

_THINK = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


class LLMUnavailable(RuntimeError):
    """No model configured, or the endpoint cannot be reached. The agent stays facts-only."""


class LLMClient:
    def __init__(self, cfg: LLMConfig, client: httpx.AsyncClient | None = None) -> None:
        self.cfg = cfg
        headers = {}
        if cfg.api_key_env and os.environ.get(cfg.api_key_env):
            headers["Authorization"] = f"Bearer {os.environ[cfg.api_key_env]}"
        # Local models can take a while to load into VRAM on the first call.
        self._client = client or httpx.AsyncClient(base_url=cfg.base_url, headers=headers, timeout=180.0)

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        json_schema: dict[str, Any] | None = None,
        temperature: float = 0.3,
    ) -> str:
        if not self.cfg.model:
            raise LLMUnavailable("no model configured (config.yaml llm.model)")
        body: dict[str, Any] = {"model": self.cfg.model, "messages": messages, "temperature": temperature}
        if self.cfg.reasoning_effort:
            # "none" turns off a reasoning model's hidden thinking (qwen3:8b: ~12 s -> ~1 s per call).
            body["reasoning_effort"] = self.cfg.reasoning_effort
        if json_schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "response", "schema": json_schema, "strict": True},
            }
        try:
            resp = await self._client.post("chat/completions", json=body)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise LLMUnavailable(f"{e.response.status_code} from model endpoint: {e.response.text[:200]}") from e
        except httpx.HTTPError as e:
            raise LLMUnavailable(f"cannot reach model endpoint {self.cfg.base_url}: {e}") from e
        content = resp.json()["choices"][0]["message"].get("content") or ""
        # Reasoning models may inline their scratch work; only the answer is wanted.
        return _THINK.sub("", content).strip()

    async def chat_json(self, messages: list[dict[str, str]], schema: dict[str, Any]) -> dict[str, Any]:
        return json.loads(await self.chat(messages, json_schema=schema, temperature=0.0))

    async def aclose(self) -> None:
        await self._client.aclose()
