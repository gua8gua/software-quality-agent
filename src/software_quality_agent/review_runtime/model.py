"""Compatibility import for the model runtime package.

Provider configuration and interface dispatch live in ``model_runtime``;
existing workflow callers continue to use this narrow import boundary.
"""

from ..model_runtime.provider import ObservedChatCompletionsModel, build_model

_model_for = build_model

__all__ = ["ObservedChatCompletionsModel", "_model_for"]
