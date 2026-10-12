"""Runtime transport configuration derived from application settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .profiles import profile_for


@dataclass(frozen=True)
class ModelTransportConfig:
    model: str
    base_url: str
    api_key: str
    context_window: int
    safety_tokens: int
    health_timeout_seconds: float
    call_timeout_seconds: float
    provider_max_output_tokens: int | None
    continuation_limit: int

    @classmethod
    def from_settings(cls, settings: Any) -> ModelTransportConfig:
        model = settings.suggestion_model or "qwen35-9b"
        profile = profile_for(model)
        return cls(
            model=model,
            base_url=(settings.suggestion_base_url or "").rstrip("/"),
            api_key=settings.suggestion_api_key,
            context_window=getattr(settings, "suggestion_context_window", profile.default_context_window),
            safety_tokens=getattr(settings, "suggestion_context_safety_tokens", 512),
            health_timeout_seconds=getattr(settings, "suggestion_model_health_timeout_seconds", 4.0),
            call_timeout_seconds=float(getattr(settings, "suggestion_model_call_timeout_seconds", 180.0)),
            provider_max_output_tokens=getattr(settings, "suggestion_provider_max_output_tokens", None),
            continuation_limit=int(getattr(settings, "suggestion_truncation_continuation_limit", profile.continuation_limit)),
        )
