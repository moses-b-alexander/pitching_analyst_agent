"""Config loading and model-role parsing."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DETERMINISTIC = "deterministic"
ROLES = ("exec", "facts", "stats")


@dataclass(frozen=True)
class ModelSpec:
    """A resolved `provider:model` spec, or the deterministic (no-LLM) backend."""

    provider: str
    model: str | None = None

    @classmethod
    def parse(cls, raw: str) -> ModelSpec:
        raw = raw.strip()
        if raw == DETERMINISTIC:
            return cls(provider=DETERMINISTIC)
        provider, sep, model = raw.partition(":")
        if not sep or not provider or not model:
            # Never silently reinterpret an ambiguous name (architecture §10).
            raise ValueError(f"model spec must be 'provider:model' or '{DETERMINISTIC}', got {raw!r}")
        return cls(provider=provider, model=model)

    def __str__(self) -> str:
        return self.provider if self.model is None else f"{self.provider}:{self.model}"


@dataclass
class Config:
    db_path: Path
    cache_dir: Path
    models: dict[str, ModelSpec | None]
    raw: dict[str, Any] = field(default_factory=dict)


def load_config(path: str | Path = "config.yaml") -> Config:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    models: dict[str, ModelSpec | None] = {}
    for role in ROLES:
        spec = (data.get("models") or {}).get(role)
        models[role] = ModelSpec.parse(spec) if spec else None
    return Config(
        db_path=Path(data.get("db_path", "data/baseball.sqlite")),
        cache_dir=Path(data.get("cache_dir", "data/cache")),
        models=models,
        raw=data,
    )
