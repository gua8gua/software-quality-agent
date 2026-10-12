"""delegation definitions for the SDK review workflow."""

from __future__ import annotations

import inspect
import json
from typing import Any

from agents import Agent, ModelBehaviorError, RunConfig, Runner
from agents.strict_schema import ensure_strict_json_schema
from agents.tool import FunctionTool
from agents.tool_context import ToolContext
from pydantic import BaseModel, TypeAdapter, ValidationError

from ..review_runtime.context import SuggestionContext
from ..review_runtime.control import _fatal_nested_failure
from .common import _sdk_tool_failure
from ..review_runtime.limits import begin_specialist


def _unbounded_agent_tool(
    *,
    agent: Agent[SuggestionContext],
    tool_name: str,
    tool_description: str,
    parameters: type[BaseModel],
    run_config: RunConfig | dict[str, Any] | None = None,
    input_builder: Any = None,
    is_enabled: Any = True,
) -> FunctionTool:
    """Run the complex segment specialist without an SDK default turn cap.

    The installed SDK's ``Agent.as_tool(max_turns=None)`` substitutes its
    default ten-turn value.  The review-analysis loop is intentionally not a
    bounded reading subtask, so this adapter invokes the official Runner with
    ``max_turns=None`` explicitly.  Reading a single SDS passage still uses
    the native bounded agent tool below.
    """
    adapter = TypeAdapter(parameters)

    async def invoke(tool_context: ToolContext[Any], input_json: str) -> str:
        try:
            params = adapter.dump_python(adapter.validate_json(input_json), mode="json")
            resolved = (
                input_builder({"params": params})
                if input_builder
                else json.dumps(params, ensure_ascii=False, separators=(",", ":"))
            )
            if inspect.isawaitable(resolved):
                resolved = await resolved
        except (TypeError, ValueError, ValidationError, RuntimeError) as exc:
            return _sdk_tool_failure(
                tool_context, ModelBehaviorError(f"invalid_tool_arguments:{tool_name}:{exc}")
            )
        previous_activity = tool_context.context.store.data.get("specialist_activity")
        previous_agent = tool_context.context.store.data.get("current_model_agent")
        begin_specialist(tool_context.context.store, tool_name)
        tool_context.context.store.data["current_model_agent"] = agent.name
        from ..review_runtime.reading import start_read_scope
        start_read_scope(tool_context.context.store, agent.name, tool_name)
        try:
            result = await Runner.run(
                agent, resolved, context=tool_context.context, run_config=run_config, max_turns=None
            )
            return str(result.final_output or "")
        except Exception as exc:
            return _fatal_nested_failure(tool_context, exc)
        finally:
            tool_context.context.store.data["specialist_activity"] = previous_activity or {"tool": "manager"}
            tool_context.context.store.data["current_model_agent"] = previous_agent
            tool_context.context.store._save()

    return FunctionTool(
        name=tool_name,
        description=tool_description,
        params_json_schema=ensure_strict_json_schema(adapter.json_schema()),
        on_invoke_tool=invoke,
        timeout_seconds=None,
        is_enabled=is_enabled,
        _is_agent_tool=True,
        _agent_instance=agent,
    )
