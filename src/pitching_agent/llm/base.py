"""Interpreter and telemetry protocols (architecture §10, provider usage section).

No state, analytics, or reconciliation code may import a concrete provider.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol


class AnalystLLM(Protocol):
    async def interpret_observation(self, context: dict[str, Any]) -> dict[str, Any]: ...

    async def summarize_checkpoint(self, context: dict[str, Any]) -> str: ...

    async def synthesize_starter_exit(self, context: dict[str, Any]) -> str: ...

    async def propose_tests(self, context: dict[str, Any]) -> list[dict[str, Any]]: ...


class TelemetryStatus(str, Enum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    PERMISSION_DENIED = "permission_denied"
    UNAVAILABLE = "unavailable"
    STALE = "stale"


@dataclass
class RequestUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_s: float | None = None


class ProviderTelemetry(Protocol):
    async def request_usage(self) -> RequestUsage: ...

    async def rate_limits(self) -> dict[str, Any] | None: ...

    async def account_usage(self) -> dict[str, Any] | None: ...
