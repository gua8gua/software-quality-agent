"""Validator SDK role: prompt, tools and output contract."""

from __future__ import annotations

from typing import Any

from agents import Agent

from ..review_runtime.context import SuggestionContext
from ..review_runtime.control import _assessment_tool_completion
from ..review_runtime.guardrails import validator_workspace_guardrail
from ..review_runtime.hooks import WorkspaceHooks
from ..tool_definitions.overall_assessment import validate_review_assessment
from ..tool_definitions.review_segments import get_review_segment
from ..tool_definitions.saved_results import get_saved_tool_result
from ..tool_definitions.structure_navigation import STRUCTURE_QUERY_TOOLS
from ..tool_definitions.suggestions import get_suggestion_workspace, save_suggestion_validation
from ..tool_definitions.work_notes import get_work_notes
from .common import _settings


def create_validator_agent(model: Any) -> Agent[SuggestionContext]:
    validator = Agent[SuggestionContext](
        name="review and suggestion validator agent",
        instructions=(
            """根据 validation_task 独立验证已保存的整体评审事实或修改建议。
validation_task=overall_assessment 时，通过 get_review_segment 分页读完整源语段、每个检查点的状态/理由/证据及整体提案。检查是否漏掉原文要求、条件和依赖，整体问题是否有逐字证据，范围和结论措辞是否成立。全部检查点 supported 不证明原文已完整覆盖；整体异常与 supported 子项并存时必须有具体 canonical 证据和合理解释。
区分历史执行失败与当前语义事实。历史 timeout/MaxTurns 本身不是语义缺陷。检查点闭环按 can_stop_for_sufficient_evidence 完成时，不因高优先节点尚未穷尽就拒绝，但仍检查原文覆盖、逐字证据、未解决反证和整体含义。使用真实 assessment.proposal_fingerprint 调用 validate_review_assessment 保存 accepted/rejected 与实质性的中文理由；此任务不生成建议。
validation_task=suggestion 时，将最新建议与工作区事实核对。检查所有异常检查点和已接受的整体问题是否覆盖；不将正常内容或执行失败描述成设计缺陷。每个事实主张必须对应有效 canonical/评审证据，不把 uncertain/insufficient 写成确定缺陷，不把网络资料作 canonical 证据，不新增无依据功能、条件、数值或机制。
返回明确问题及简洁修订指令，不替建议 Agent 重写建议。读取最新草稿 iteration，用 save_suggestion_validation 保存准确绑定的验证反馈，然后返回简短完成说明。
按证据返回的 location 读取 canonical 原文，必要时用结构目录查看标题和全部下级章节；不获取全文 UUID 列表、不猜标题编号。只在写验证反馈时使用已返回的提案指纹、草稿版本和证据索引。
验证理由和修订反馈使用容易理解的中文段落，说明当前结论是什么、对应哪一条原文要求、证据能解释到什么程度，以及下一轮需要修改的具体内容。通过时说明成立依据，拒绝时说明具体缺口和可执行的修订目标。
证据关系 relation 与检查点累积状态 status 分别记录。relation=context 可以与 status=supported 同时保存；使用有效逐字原文引文，并在理由中说明当前资料的上下文作用及累积判定依据。relation=supporting 与 status=supported 也允许同时保存。status=contradicted 使用有效 counter 证据。
所有验证理由、问题和修改指令使用中文；工具名、字段名、状态枚举和需要写入的索引保持原样。"""
        ),
        tools=[
            get_review_segment,
            get_work_notes,
            get_suggestion_workspace,
            get_saved_tool_result,
            save_suggestion_validation,
            validate_review_assessment,
            *STRUCTURE_QUERY_TOOLS,
        ],
        output_type=str,
        tool_use_behavior=_assessment_tool_completion,
        output_guardrails=[validator_workspace_guardrail],
        hooks=WorkspaceHooks("validator"),
        **_settings(model, 4096, require_tool=True),
    )
    return validator
