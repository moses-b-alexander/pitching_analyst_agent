"""Config loading."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class LLMConfig:
    """One OpenAI-compatible endpoint (Ollama, llama.cpp, or a hosted open-weight provider)."""

    base_url: str
    model: str | None  # None: no model configured; the agent runs facts-only
    api_key_env: str | None = None
    reasoning_effort: str | None = None  # sent as-is when set; "none" disables thinking


@dataclass
class Config:
    db_path: Path
    cache_dir: Path
    llm: LLMConfig
    raw: dict[str, Any] = field(default_factory=dict)


def load_config(path: str | Path = "config.yaml") -> Config:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    llm = data.get("llm") or {}
    return Config(
        db_path=Path(data.get("db_path", "data/baseball.sqlite")),
        cache_dir=Path(data.get("cache_dir", "data/cache")),
        llm=LLMConfig(
            base_url=llm.get("base_url", "http://localhost:11434/v1"),
            model=llm.get("model"),
            api_key_env=llm.get("api_key_env"),
            reasoning_effort=llm.get("reasoning_effort"),
        ),
        raw=data,
    )
