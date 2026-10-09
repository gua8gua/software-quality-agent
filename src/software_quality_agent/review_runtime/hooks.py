"""hooks definitions for the SDK review workflow."""

from __future__ import annotations

import json
from typing import Any

from agents import AgentHooks
from .reading import start_read_scope


class WorkspaceHooks(AgentHooks):
    """Persist observable lifecycle boundaries in the business checkpoint."""

    def __init__(self, stage: str):
        self.stage = stage

    def _stage(self, context: Any) -> str:
        if (
            self.stage == "validator"
            and context.context.store.data.get("specialist_activity", {}).get("tool") == "validate_segment_assessment"
        ):
            return "assessment_validator"
        return "suggestion_validator" if self.stage == "validator" else self.stage

    async def on_start(self, context: Any, agent: Any) -> None:
        runtime = context.context
        current_stage = self._stage(context)
        runtime.store.data["current_model_agent"] = agent.name
        start_read_scope(runtime.store, agent.name, current_stage)
        # The SDK does not expose the nested Runner turn counter to the model.
        # Record the model-call baseline at specialist start so the input
        # filter can report the remaining passage-read turns explicitly.
        runtime.store.data.setdefault("agent_turn_bases", {})[current_stage] = len(
            runtime.store.data.get("model_calls", [])
        )
        if current_stage == "suggestion":
            runtime.store.data["suggestion_start_draft_count"] = len(
                runtime.store.data.get("suggestion_drafts", [])
            )
            runtime.store._save()
        elif current_stage == "suggestion_validator":
            runtime.store.data["validator_start_feedback_count"] = len(
                runtime.store.data.get("validation_feedback", [])
            )
            runtime.store._save()
        elif current_stage == "assessment_validator":
            runtime.store.transition("overall_assessment_validation", "running")
        tool_input = getattr(context, "tool_input", None)
        check_id = getattr(tool_input, "check_id", None)
        stage = f"{current_stage}:{check_id}" if check_id else current_stage
        runtime.store.transition(stage, "running")

    async def on_end(self, context: Any, agent: Any, output: Any) -> None:
        runtime = context.context
        tool_input = getattr(context, "tool_input", None)
        check_id = getattr(tool_input, "check_id", None)
        current_stage = self._stage(context)
        stage = f"{current_stage}:{check_id}" if check_id else current_stage
        runtime.store.transition(stage, "completed", output=output)

    async def on_tool_end(self, context: Any, agent: Any, tool: Any, result: Any) -> None:
        runtime = context.context
        call_id = getattr(context, "tool_call_id", None)
        if call_id:
            value = result
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except ValueError:
                    pass
            runtime.store.data.setdefault("sdk_tool_results", {})[call_id] = {
                "tool": tool.name,
                "output": value,
                "arguments": getattr(context, "tool_arguments", None),
            }
            runtime.store._save()
