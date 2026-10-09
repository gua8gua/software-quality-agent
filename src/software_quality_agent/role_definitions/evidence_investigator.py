"""Evidence Investigator SDK role: prompt, tools and output contract."""

from __future__ import annotations

from typing import Any

from agents import Agent

from ..review_runtime.context import SuggestionContext
from ..review_runtime.control import _terminal_tool_completion
from ..review_runtime.hooks import WorkspaceHooks
from ..tool_definitions.material_sequence import open_supplementary_material
from ..tool_definitions.review_progress import get_review_investigation
from ..tool_definitions.review_segments import get_review_segment
from ..tool_definitions.structure_navigation import STRUCTURE_QUERY_TOOLS
from .common import _settings


def create_evidence_investigator_agent(model: Any) -> Agent[SuggestionContext]:
    evidence = Agent[SuggestionContext](
        name="evidence investigator agent",
        instructions=(
            """你是资料驱动的证据调查 Agent，只查事实，不裁决检查点。一次子任务只打开下一份 SDS 资料，然后交给评审分析 Agent 对全部检查点评估。
先读取当前完整需求语段和调查状态，不把检查点割裂成独立需求。工具的 current_stage、next_required_action 是权威阶段。
正式 TLR 资料由评审分析 Agent 按保存顺序读取，本 Agent 不处理高优先 TLR。只有高优先资料耗尽且仍有缺口时，才调查补充资料。输入必须包含 Review Analysis 通过结构查询确认的 location；可用 get_node_summary 或 browse_document_structure 核对标题和摘要，但不能自行改成另一个目标。结构 location 例如 设计文档1:/2/4 是实际树路径，不是标题编号。复制工具返回的 location，不能把 3.2.4 章节号或 Docling ref 当作位置。必要时在已确认的分支内用 search_document_content 调查，再用 open_supplementary_material 注册一份正文。最多注册 5 个补充资料段；本次调查最多 5 轮。
可读取本项目其他 canonical 原文作为低优先上下文，不把其他需求的结论复制为当前事实。用户目标范围外原文只作上下文，不作为当前审核证据；此限制由工具校验。原文分页未读完时按返回的游标续读，不把预览当全文。
成功打开一份资料后立即返回，不评估或修改检查点，不遍历全部候选。执行 blocked 不代表需求缺陷。外部资料不是 canonical 证据。
每轮公开说明当前 CURRENT_STAGE 和下一动作；passage_read_budget.turns_remaining 是本次单份資料调查的剩余轮数，不是整个需求任务的上限。说明和工作记录用中文，保留工具字段和结构位置原样。"""
        ),
        tools=[
            get_review_segment,
            get_review_investigation,
            open_supplementary_material,
            *STRUCTURE_QUERY_TOOLS,
        ],
        output_type=str,
        tool_use_behavior=_terminal_tool_completion,
        hooks=WorkspaceHooks("evidence"),
        **_settings(model, 8192, require_tool=True),
    )
    return evidence
