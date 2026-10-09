"""Model-specific limits and output continuation policy."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelProfile:
    family: str
    default_context_window: int
    default_output_tokens: int
    max_output_tokens: int
    continuation_limit: int


_DEFAULT = ModelProfile("openai-compatible", 16_384, 8_192, 16_384, 8)
_PROFILES = {
    "deepseek": ModelProfile("deepseek", 1_000_000, 32_768, 384_000, 8),
    "deepseek-chat": ModelProfile("deepseek", 1_000_000, 32_768, 384_000, 8),
    "deepseek-flash": ModelProfile("deepseek", 1_000_000, 32_768, 384_000, 8),
    "deepseek-v4-pro": ModelProfile("deepseek", 1_000_000, 32_768, 384_000, 8),
    "qwen": ModelProfile("qwen", 32_768, 8_192, 32_768, 8),
    "qwen3": ModelProfile("qwen", 32_768, 8_192, 32_768, 8),
}


def profile_for(model: str | None) -> ModelProfile:
    name = (model or "").lower()
    for key, profile in _PROFILES.items():
        if name == key or name.startswith(key + "-") or key in name:
            return profile
    return _DEFAULT


def output_budget(
    model: str | None,
    *,
    requested: int | None,
    provider_max: int | None = None,
    context_window: int | None = None,
    safety_tokens: int = 512,
) -> int | None:
    """Clamp a requested output budget to provider metadata/profile limits."""
    profile = profile_for(model)
    ceiling = provider_max or profile.max_output_tokens
    if context_window:
        ceiling = min(ceiling, max(1, context_window - safety_tokens))
    if requested is None:
        requested = profile.default_output_tokens
    return max(1, min(requested, ceiling))
