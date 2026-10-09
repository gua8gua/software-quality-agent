"""Web Research SDK role: prompt, tools and output contract."""

from __future__ import annotations

from typing import Any

from agents import Agent

from ..review_runtime.context import SuggestionContext
from ..review_runtime.hooks import WorkspaceHooks
from ..tool_definitions.web import read_external_web_page, search_external_web
from .common import _settings


def create_web_research_agent(model: Any) -> Agent[SuggestionContext]:
    web = Agent[SuggestionContext](
        name="web research agent",
        instructions="""仅在评审确实需要外部背景资料时调查标准、论文、官方文档或仍在维护的项目。返回真实网址和简短的事实说明。外部资料永远不能作为工件原文（canonical）证据。所有解释、调查摘要和工作记录使用中文，工具名、字段名、状态枚举和真实 ID 保持原样。""",
        tools=[search_external_web, read_external_web_page],
        output_type=str,
        hooks=WorkspaceHooks("web_research"),
        **_settings(model, 4096),
    )
    return web
