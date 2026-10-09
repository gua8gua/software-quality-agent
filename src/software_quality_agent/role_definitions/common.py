"""Shared SDK settings and post-assembly role augmentation."""

from __future__ import annotations

from typing import Any

from agents import Agent, ModelSettings

from ..model_runtime.profiles import output_budget
from ..review_runtime.context import SuggestionContext
from ..tool_definitions.saved_results import get_saved_tool_result


def _settings(model: Any, max_tokens: int | None, *, require_tool: bool = False) -> dict[str, Any]:
    model_name = getattr(model, "model", None)
    max_tokens = output_budget(
        model_name,
        requested=max_tokens,
        provider_max=getattr(model, "provider_max_output_tokens", None),
        context_window=getattr(model, "provider_context_window", None),
    )
    options: dict[str, Any] = {
        "model_settings": ModelSettings(
            temperature=0.0,
            parallel_tool_calls=False,
            max_tokens=max_tokens,
            # Review specialists have durable write/terminal tools for every
            # successful step. Requiring a tool call prevents a verbose prose
            # "final answer" from consuming the output budget before the required
            # completion/assessment write. The web-only role remains free to return
            # a research note after its search tools.
            tool_choice="required" if require_tool else None,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
    }
    # SDK defaults reset tool_choice after the first tool. These specialists
    # have persisted tool terminals, so keep required throughout the run;
    # a prose offer to act must not replace the authorized business action.
    options["reset_tool_choice"] = not require_tool
    if model is not None:
        options["model"] = model
    return options


def finalize_roles(
    result: dict[str, Agent[SuggestionContext]],
) -> dict[str, Agent[SuggestionContext]]:
    for agent in result.values():
        if not any(t.name == "get_saved_tool_result" for t in agent.tools):
            agent.tools.append(get_saved_tool_result)
        agent.instructions += " 大型工具结果以 saved_sdk_tool_output、call_id 和字段索引呈现，并非空结果。用 get_saved_tool_result(call_id, field_path, offset, limit) 读取所需小页，文档查询使用返回的 location；不要读取内部 UUID 或全文成员列表。不从省略内容推断事实，不反复请求同一超大页。"
    return result
