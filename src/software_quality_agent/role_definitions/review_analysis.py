"""Review Analysis SDK role: prompt, tools and output contract."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from agents import Agent

from ..review_runtime.context import SuggestionContext
from ..review_runtime.contracts import EvidenceInvestigationTask, WebResearchTask
from ..review_runtime.control import (
    _analysis_material_tool_enabled,
    _assessment_tool_completion,
    _conclusion_enabled,
    _evidence_input_builder,
    _fatal_nested_failure,
    _input_builder,
    _investigation_enabled,
    _nested_config,
)
from ..review_runtime.guardrails import analysis_workspace_guardrail
from ..review_runtime.hooks import WorkspaceHooks
from ..tool_definitions.delegation import _unbounded_agent_tool
from ..tool_definitions.material_sequence import read_next_tlr_material
from ..tool_definitions.overall_assessment import propose_review_assessment
from ..tool_definitions.review_checks import (
    complete_review_analysis,
    create_review_check,
    finalize_review_checks,
)
from ..tool_definitions.review_evidence import (
    assess_review_check,
    finalize_review_passage,
)
from ..tool_definitions.review_progress import finish_review_incomplete, get_review_investigation
from ..tool_definitions.review_segments import get_review_segment
from ..tool_definitions.structure_navigation import STRUCTURE_QUERY_TOOLS
from ..tool_definitions.work_notes import get_work_notes, record_work_note
from .common import _settings


def create_review_analysis_agent(
    model: Any,
    sentence_input: dict[str, Any],
    context: SuggestionContext,
    evidence: Agent[SuggestionContext],
    web: Agent[SuggestionContext],
) -> Agent[SuggestionContext]:
    analysis_tools = [
        get_review_segment,
        get_work_notes,
        record_work_note,
        create_review_check,
        finalize_review_checks,
        read_next_tlr_material,
        assess_review_check,
        finalize_review_passage,
        get_review_investigation,
        finish_review_incomplete,
        complete_review_analysis,
        propose_review_assessment,
        *STRUCTURE_QUERY_TOOLS,
        evidence.as_tool(
            tool_name="investigate_review_material",
            tool_description="在正式 TLR 已全部处理且仍有证据缺口时，结合结构查询结果调查一份额外 SDS 资料。",
            parameters=EvidenceInvestigationTask,
            include_input_schema=True,
            max_turns=context.passage_max_turns,
            run_config=_nested_config(),
            is_enabled=_investigation_enabled,
            # Evidence investigation is required for the current sentence.
            # A bounded child failure must terminate this attempt instead of
            # returning prose that made the parent repeat the same passage
            # error until its bounded passage-read budget.
            failure_error_function=_fatal_nested_failure,
            input_builder=_evidence_input_builder({"sentence": sentence_input}, context),
        ),
        _unbounded_agent_tool(
            agent=web,
            tool_name="research_external_context",
            tool_description="调查外部标准或项目，只作背景，不作为 canonical 证据。",
            parameters=WebResearchTask,
            input_builder=_input_builder({}, context=context),
            run_config=_nested_config(),
        ),
    ]
    analysis = Agent[SuggestionContext](
        name="review analysis agent",
        instructions=(
            """你在一次 OpenAI Agents SDK Runner 中完成当前需求语段的资料驱动评审闭环，不调用旧后台 LLM。
relation 记录当前资料与检查点的关系，status 记录检查点的累积判定。relation=context 允许同时提交 status=supported，使用有效逐字原文引文，说明本资料的上下文作用和累积满足依据。relation=supporting 也允许 status=supported；status=contradicted 使用有效 counter 证据。
评审分析到整体验证合计最多两轮，第一轮反馈用于一次完整语段修订，第二轮验证后结束此阶段。
固定流程：读完整需求 -> 创建并确认检查点 -> 切换下一份高优先 SDS 资料 -> 用这份资料评估全部检查点 -> 完成这份资料 -> 决定继续或停止 -> 保存每个检查点综合结论 -> 提交整体评价。
每次阶段转换公开标注 CURRENT_STAGE=<工具返回的阶段>、NEXT_ACTION=<下一动作>。工具的 current_stage/next_required_action 是权威进度，不自造阶段或跳过依赖。
1. get_review_segment 分页读完整源语段，保留条件、指代和前后依赖。当前 source_location/标题路径可通过 get_document_neighbors、read_document_content 查看邻近上下文。text_has_more 等分页标志为 true 必须续读，不能把预览当全文。
2. checks_finalized=false 时对照原文和已有检查点，只补充原文明示的 function_result（功能/结果）或 condition_constraint（条件/约束）。source_quote 必须逐字。create_review_check 即时保存 pending 检查点，finalize_review_checks 使用已返回的 check_id 确认完整集合。不增加原文没有的功能、数字或机制。
 3. 高优先 TLR 资料不需要你挑选：必须直接调用 read_next_tlr_material，由程序按已保存 TLR 顺序确定下一资料。正式 TLR 处理期间禁止调用 investigate_review_material；不要列举候选、索取全篇节点 ID 或自行填写候选绑定。返回 current_material_pending 时先完成当前资料，不另开资料。
4. 每次只处理当前 SDS 资料，但必须评估全部检查点。对每个 check_id 调用 assess_review_check：简述这份资料如何支持、反驳、帮助解释或无关。supporting/counter/context 必须附当前资料的逐字引文。所有检查点评估已保存后 finalize_review_passage；passage_id 是工具已返回的写入索引，不是可自行生成的文档 ID。当前资料读到不等于已完成评估；有剩余文本时按结构位置/偏移续读。
5. 完成当前资料后检查 can_stop_for_sufficient_evidence。完整检查点集合全部有效 supported 且无未解决反证时立刻停止扩展，不为读完列表而继续，历史异常照常保留。工具返回 retry_required 时，把错误原因用于修正本次失败操作，仅重试一次，不重新生成已保存的有效评估。再次失败则资料 blocked 并跳过，立即 read_next_tlr_material 继续其他独立资料，不重复查询状态。irrelevant/needs_context 的多余引文由程序忽略，不保存为证据。全部可继续的高优先任务耗尽后允许调查补充资料；仍无法形成可靠结论时调用 finish_review_incomplete 保留执行失败并返回管理 Agent，不把失败当“不实现”。
 6. 高优先资料耗尽且仍有缺口时，才调查额外资料。先用 list_document_branches/browse_document_structure/get_node_summary/read_document_content/get_document_neighbors 了解真实文档名、标题、节点摘要和子章节，再把明确的 investigation_goal 和 location 交给 investigate_review_material。额外调查最多 5 个资料段，单次调查最多 5 轮；不要直接调用额外资料打开工具。用户选定范围外原文可以查询作上下文，不能写为当前证据。不得复制其他语段结论。
7. 综合完整需求和全部保存证据，对每个检查点用 complete_review_analysis 分组保存最终状态和理由（finalize=false），全部有显式结论后才 finalize。不要把最后一份资料的相关性当综合结论，不用空列表替代判断。pending 是未完成；insufficient/uncertain 是证据语义，不能替代执行错误。未找到证据不等于全文绝对没有。
8. 检查点闭环完成后 propose_review_assessment 给中文整体评价。implemented=全部显式要求 supported 且无整体问题；uncovered=已调查范围全部缺少支持；issues=冲突、部分覆盖或需澄清。已存在子检查点问题只汇总到评价，不重复捏造 OverallIssue。
全部子检查点 supported 仍可能存在整体集成/顺序/约束问题，但独立 OverallIssue 必须有源原文 source_quote、具体解释和非空逐字设计证据；设计位置复制工具的 location。不添加原文没有的要求。无独立问题时 issues=[]。执行失败不是 issues/uncovered。
整体提案保存后交由独立 Validator，不自己宣布接受。恢复时优先读已保存工作状态/理由/证据，不重复已完成调查。Validator 拒绝后只按真实反馈修订，无法可靠修订则保留 blocked。
所有语义说明、理由和工作记录使用中文；check_id/evidence_id/passage_id 仅在相应写入工具需要时原样复制，不索取全文 UUID 列表。"""
        ),
        tools=[
            replace(tool, is_enabled=_conclusion_enabled)
            if tool.name == "complete_review_analysis"
            else replace(tool, is_enabled=_analysis_material_tool_enabled)
            if tool.name
            in {"read_next_tlr_material", "assess_review_check", "finalize_review_passage"}
            else tool
            for tool in analysis_tools
        ],
        output_type=str,
        tool_use_behavior=_assessment_tool_completion,
        output_guardrails=[analysis_workspace_guardrail],
        hooks=WorkspaceHooks("review_analysis"),
        **_settings(model, 8192, require_tool=True),
    )
    return analysis
