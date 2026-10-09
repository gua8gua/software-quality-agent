"""Manager SDK role: prompt, tools and output contract."""

from __future__ import annotations

from typing import Any

from agents import Agent

from ..review_runtime.context import SuggestionContext
from ..review_runtime.contracts import (
    ReviewAnalysisTask,
    SuggestionTask,
    SuggestionValidationTask,
    WebResearchTask,
)
from ..review_runtime.control import (
    _assessment_needs_validation,
    _draft_enabled,
    _input_builder,
    _manager_tool_completion,
    _nested_config,
    _suggestion_validation_enabled,
)
from ..review_runtime.guardrails import manager_workspace_guardrail
from ..review_runtime.hooks import WorkspaceHooks
from ..tool_definitions.delegation import _unbounded_agent_tool
from ..tool_definitions.review_progress import get_review_progress
from ..tool_definitions.suggestions import get_suggestion_workspace
from ..tool_definitions.work_notes import get_work_notes
from .common import _settings


def create_manager_agent(
    model: Any,
    sentence_input: dict[str, Any],
    context: SuggestionContext,
    analysis: Agent[SuggestionContext],
    suggestion: Agent[SuggestionContext],
    validator: Agent[SuggestionContext],
    web: Agent[SuggestionContext],
    *,
    assessment_validator: Agent[SuggestionContext] | None = None,
) -> Agent[SuggestionContext]:
    manager_tools = [
        _unbounded_agent_tool(
            agent=analysis,
            tool_name="run_review_analysis",
            tool_description="完成当前语段的检查点创建、证据调查、状态更新和整体评价闭环。",
            parameters=ReviewAnalysisTask,
            input_builder=_input_builder({"sentence": sentence_input}, context=context),
            run_config=_nested_config(),
        ),
        _unbounded_agent_tool(
            agent=(assessment_validator or validator).clone(
                tools=[t for t in (assessment_validator or validator).tools if t.name != "save_suggestion_validation"]
            ),
            tool_name="validate_segment_assessment",
            tool_description="生成建议前，独立验证整个语段评价及整体问题证据。",
            parameters=ReviewAnalysisTask,
            is_enabled=_assessment_needs_validation,
            run_config=_nested_config(),
            input_builder=_input_builder(
                {"sentence": sentence_input, "validation_task": "overall_assessment"},
                context=context,
                required_stage="overall_assessment_proposed",
            ),
        ),
        _unbounded_agent_tool(
            agent=suggestion,
            tool_name="draft_modification_suggestion",
            tool_description="基于已完成工作区事实和真实证据生成修改建议草稿。",
            parameters=SuggestionTask,
            is_enabled=_draft_enabled,
            run_config=_nested_config(),
            input_builder=_input_builder(
                {"sentence": sentence_input},
                context=context,
                required_stage="overall_assessment_validated",
            ),
        ),
        _unbounded_agent_tool(
            agent=validator.clone(
                tools=[t for t in validator.tools if t.name != "validate_review_assessment"]
            ),
            tool_name="validate_modification_suggestion",
            tool_description="验证修改建议并返回明确修订指令。",
            parameters=SuggestionValidationTask,
            is_enabled=_suggestion_validation_enabled,
            run_config=_nested_config(),
            input_builder=_input_builder(
                {"sentence": sentence_input, "validation_task": "suggestion"},
                context=context,
                required_stage="overall_assessment_validated",
            ),
        ),
        get_work_notes,
        get_suggestion_workspace,
        get_review_progress,
        _unbounded_agent_tool(
            agent=web,
            tool_name="research_web_context",
            tool_description="只调查外部背景，不能作为 canonical 证据。",
            parameters=WebResearchTask,
            run_config=_nested_config(),
            input_builder=_input_builder({}, context=context),
        ),
    ]
    manager = Agent[SuggestionContext](
        name="review manager agent",
        instructions=(
            f"""只编排当前一个待评审源语段，不自行提取检查点、裁决满足度或生成建议。SDK Context 已绑定 specialist 的当前语段，不向调度工具传 review_id、sentence_id；只填写调查目标或修订反馈。
若后台已有完成的评审检查点，则复用真实 checkpoint；否则调用 run_review_analysis 并等待其保存检查点裁决和整体提案。整体结论必须经过 validate_segment_assessment 独立验证才有效。若被拒绝，让评审分析 Agent 从持久化反馈修订；无法可靠解决时保留 blocked，不当作设计缺陷。
独立接受后依据 assessment.suggestion_required 决定建议流程，不只看检查点状态：全部检查点 supported 也可能有经验证的整体问题。无经验证的业务问题则直接结束，不生成建议；否则调用建议 Agent，再调用建议 Validator，未通过则带保存的反馈交回建议 Agent 修订。
每个 specialist 返回后，读取 get_review_progress、get_suggestion_workspace 核对事实，不仅依赖子 Agent 的文字。get_review_progress.current_stage、next_required_action 是权威阶段，在编排说明中标注 CURRENT_STAGE。
评审分析到整体验证组成一轮完整语段处理，最多执行两轮：首次处理，以及根据第一轮验证反馈进行的一次修订重试。第二轮验证仍被拒绝时，保存中文原因并结束当前语段，批次继续下一语段。
建议生成到建议验证组成一轮建议处理，最多执行两轮：首次草稿，以及根据第一轮反馈进行的一次修订重试。草稿预算为 {context.max_suggestion_revisions} 次，第二轮结束后保存 accepted 或 unresolved 的真实结果。
以持久化工作区为业务真源，区分执行 blocked 与语义 unresolved；不重新执行 TLR，不改 canonical 原文，不调用旧后台 LLM 完成认知任务。返回简短编排说明，由应用投影已保存草稿和验证结果。
你不需要文档/节点 UUID 或全文候选列表。编排只使用阶段、状态、已保存验证结果；原文和结构位置由承担调查的 specialist 读取。所有编排说明与反馈使用中文。"""
        ),
        tools=manager_tools,
        output_type=str,
        tool_use_behavior=_manager_tool_completion,
        output_guardrails=[manager_workspace_guardrail],
        hooks=WorkspaceHooks("manager"),
        **_settings(model, 8192, require_tool=True),
    )
    return manager
