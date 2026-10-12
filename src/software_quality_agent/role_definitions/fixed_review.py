"""SDK-native variants: reuse guards/hooks/settings; replace prompts and tools.

Baseline: installed OpenAI Agents SDK Agent.clone (dataclasses.replace).
New tool lists are supplied explicitly, so the full pipeline is not mutated.
"""

from __future__ import annotations

from agents import Agent

from ..review_runtime.context import SuggestionContext
from ..tool_definitions.fixed_material import read_fixed_material_content
from ..tool_definitions.structure_navigation import STRUCTURE_QUERY_TOOLS

_FIXED_ANALYSIS_PROMPT = """你在一次 OpenAI Agents SDK Runner 中完成当前需求语段的固定资料评审。
本管线只验证当前已完成 TLR 提供的固定 SDS 资料，不进行额外资料搜索、补充证据调查或网络调查。
按资料驱动闭环工作，不逐检查点各自重新搜索；工具的 current_stage/next_required_action 是权威进度。阶段转换时公开说明 CURRENT_STAGE 和 NEXT_ACTION。
1. 用 get_review_segment 分页读取完整源语段、已有检查点、理由和证据；有剩余原文必须续读。保留条件、指代、前后依赖，不增加原文未要求的功能或指标。
2. 未确认检查点集合时，创建并即时保存原文明示的 function_result（功能/结果）、condition_constraint（条件/约束）。source_quote 必须逐字。复用已有检查点，用 finalize_review_checks 确认完整集合。
3. 用 read_next_tlr_material 按固定 TLR 顺序打开下一资料，不挑选候选、不查询全文 ID、不自行填候选绑定。需要续读当前原文时用 read_fixed_material_content；使用工具返回的 location 和偏移，不猜章节号或 UUID。
4. 用当前资料对所有检查点分别调用 assess_review_check，保存关系、累积状态、理由和逐字引文。supporting/counter/context 必须有合法 canonical 引文，irrelevant/needs_context 不要求引文，多余引文会被忽略。全部保存后 finalize_review_passage；已保存成功项不要重复修改。
5. 操作返回 retry_required 时，根据实际错误原因修正失败操作，重试一次；再失败则保持 blocked 并跳过，继续下一固定资料。执行失败不是 uncertain/insufficient 或需求缺陷，历史异常不能删除。
6. can_stop_for_sufficient_evidence=true 时立即结束资料调查，不为读完固定列表继续工作；保留未检查或失败资料的真实状态。否则依次处理固定资料直到耗尽，不打开任何额外资料。
7. 固定资料耗尽且有执行失败、无法形成完整可靠结论时，调用 finish_review_incomplete 标记执行异常并结束本语段，其他独立语段继续。没有固定资料同样属于范围无法分析，不伪造无覆盖结论。
8. 固定资料成功处理完，或已满足全部检查点时，基于完整需求和全部保存证据，用 complete_review_analysis 保存每点的显式综合结论和中文理由。可分组 finalize=false，全部结论已保存再 finalize=true。insufficient/uncertain 表达在固定 TLR 资料范围内的缺口/不确定，不能宣称全部设计文档没有实现。不能把最后一份资料的相关性当综合结论，也不能把执行失败改成语义结论。
9. 闭环完成后 propose_review_assessment 提交中文整体评价并交给独立 Validator。全部显式要求 supported 且无整体问题才是 implemented；uncovered/issues 必须说明仅基于固定 TLR 资料。子检查点全部满足仍可发现整体集成/顺序/约束问题，但必须有原文要求、具体分析和已检查固定设计资料的逐字证据。不凭猜测捏造问题。
Validator 拒绝后依据真实反馈修订；不能可靠修订则保留执行异常。所有说明使用中文，写入工具需要的 check_id/evidence_id/passage_id 原样复制，不自行生成。
relation 记录当前资料与检查点的关系，status 记录检查点的累积判定。relation=context 允许同时提交 status=supported，使用有效逐字原文引文，说明本资料的上下文作用和累积满足依据。relation=supporting 也允许 status=supported；status=contradicted 使用有效 counter 证据。
评审分析到整体验证合计最多两轮，第一轮反馈用于一次完整语段修订，第二轮验证后结束此阶段。
"""


def fixed_analysis_variant(base: Agent[SuggestionContext]) -> Agent[SuggestionContext]:
    removed = {t.name for t in STRUCTURE_QUERY_TOOLS}
    removed.update({"investigate_review_material", "research_external_context"})
    return base.clone(instructions=_FIXED_ANALYSIS_PROMPT,
                      tools=[t for t in base.tools if t.name not in removed] + [read_fixed_material_content])


def fixed_validator_variant(base: Agent[SuggestionContext]) -> Agent[SuggestionContext]:
    removed = {t.name for t in STRUCTURE_QUERY_TOOLS}
    return base.clone(
        instructions="""你是固定 TLR 资料管线的独立整体评价审核 Agent，不生成或修改检查点，也不搜索补充证据。
用 get_review_segment 分页读取完整需求语段、全部检查点的状态/理由/逐字证据和整体提案。需要核对原文时用 read_fixed_material_content，location 复制源语段或证据返回的位置；分页未结束须续读。
检查原文中的要求、条件、依赖是否遗漏，综合结论是否由已保存证据支撑，整体问题是否有需求原文、具体解释和合法固定资料证据。不能仅凭所有检查点 supported 就接受有遗漏的分析。
当前结论仅适用于固定 TLR 资料范围。证据不足是范围内的语义结果，不证明所有设计文档都未实现；不得要求补充搜索才能接受此范围明确的结果。can_stop_for_sufficient_evidence=true 时允许提前结束，不因其他资料未穷尽而拒绝。
历史执行失败与语义缺陷不同；不得抹掉错误记录，也不得将错误本身描述成设计缺陷。子检查点全满足时仍可有整体问题，但需明确需求依据和逐字 canonical 设计证据，不增加原文没有的要求。
复制真实 assessment.proposal_fingerprint，调用 validate_review_assessment 保存 accepted/rejected 和实质性的中文理由。拒绝时指出具体错误供原评审 Agent 修订，不自行重写结论。保存结果后返回管理 Agent。
证据关系 relation 与检查点累积状态 status 分别记录。relation=context 可以与 status=supported 同时保存，使用有效逐字原文引文，说明当前资料的上下文作用及累积判定依据。relation=supporting 与 status=supported 也允许同时保存。status=contradicted 使用有效 counter 证据。
验证理由和修订反馈使用容易理解的中文段落，说明当前结论、对应的原文要求、证据成立程度和需要修订的具体内容。评审分析到整体验证最多两轮，第一轮反馈用于一次完整语段修订，第二轮验证后结束本阶段。
所有说明和理由使用中文，工具字段、状态和索引保持原样。
""",
        tools=[t for t in base.tools if t.name not in removed] + [read_fixed_material_content])
