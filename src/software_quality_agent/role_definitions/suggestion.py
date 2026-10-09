"""Suggestion SDK role: prompt, tools and output contract."""

from __future__ import annotations

from typing import Any

from agents import Agent

from ..review_runtime.context import SuggestionContext
from ..review_runtime.contracts import WebResearchTask
from ..review_runtime.control import _input_builder, _nested_failure, _suggestion_tool_completion
from ..review_runtime.guardrails import suggestion_workspace_guardrail
from ..review_runtime.hooks import WorkspaceHooks
from ..tool_definitions.review_segments import get_review_segment
from ..tool_definitions.structure_navigation import STRUCTURE_QUERY_TOOLS
from ..tool_definitions.suggestions import get_suggestion_workspace, save_suggestion_draft
from ..tool_definitions.work_notes import get_work_notes
from .common import _settings


def create_suggestion_agent(
    model: Any, context: SuggestionContext, web: Agent[SuggestionContext]
) -> Agent[SuggestionContext]:
    suggestion_tools = [
        get_review_segment,
        get_work_notes,
        get_suggestion_workspace,
        save_suggestion_draft,
        *STRUCTURE_QUERY_TOOLS,
        web.as_tool(
            tool_name="research_suggestion_context",
            tool_description="调查修改建议需要的外部资料，不能作为 canonical 证据。",
            parameters=WebResearchTask,
            include_input_schema=True,
            failure_error_function=_nested_failure,
            input_builder=_input_builder({}, context=context),
        ),
    ]
    suggestion = Agent[SuggestionContext](
        name="suggestion agent",
        instructions=(
            """读取当前语段已持久化的完整评审工作区：原文、全部检查点、状态、理由、逐字证据、未解决问题、TLR 绑定、相关 canonical 上下文，以及已独立验证的整体评价（包括所有检查点均 supported 时仍存在的整体问题）。只在 assessment.suggestion_required=true 时工作，不重新进行一致性裁决。
整体修改绑定真实 issue_ids 及其 overall_evidence ID，不强行绑定无关检查点。形成一段面向编辑者的修改建议：保留正确内容，说明缺失、冲突、歧义及需澄清信息。不添加原文不存在的功能、条件、数值或机制，网络资料仅作外部背景。
收到 Validator 反馈时，读取并修订现有草稿，保留仍正确的建议，不另起无关联意见。每次迭代必须通过 save_suggestion_draft 即时保存，然后返回简短完成说明。
建议生成到建议验证合计最多两轮，第一轮反馈用于一次草稿修订，第二轮验证后保存真实结果并结束此阶段。修订反馈和完成说明使用容易理解的中文段落，说明具体问题、对应事实和修改内容。
查看设计原文使用证据返回的结构 location，必要时用 browse_document_structure 查真实标题及全部子章节。不会给你全文节点 UUID 列表，不猜标题编号与结构位置的对应。建议引用 canonical_node 时 identifier 填真实 location；评审证据仍使用已返回的 evidence_id，不能编索引。
全部问题说明、建议、理由和工作记录使用中文；工具名、字段名、状态枚举和需要写入的证据索引保持原样。"""
        ),
        tools=suggestion_tools,
        output_type=str,
        tool_use_behavior=_suggestion_tool_completion,
        output_guardrails=[suggestion_workspace_guardrail],
        hooks=WorkspaceHooks("suggestion"),
        **_settings(model, 8192, require_tool=True),
    )
    return suggestion
