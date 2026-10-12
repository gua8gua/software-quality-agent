"""review_evidence definitions for the SDK review workflow."""

from __future__ import annotations

import json
from typing import Literal

from agents import RunContextWrapper
from pydantic import Field

from ..review_runtime.context import SuggestionContext
from ..review_runtime.contracts import PassageCheckAssessment
from .common import (
    _annotate_phase,
    _dump,
    _get,
    _passage_failure,
    _runtime,
    _set_review_phase,
    _tool_decorator,
    _workspace,
    _write,
)


@_tool_decorator(timeout=30.0)
async def read_review_passage(
    ctx: RunContextWrapper[SuggestionContext],
    node_id: str,
    start_offset: int = Field(0, ge=0),
    text_limit: int = Field(4000, ge=1, le=8000),
    candidate_id: str | None = None,
) -> str:
    """打开一个精确 SDS 原文范围，用于对全部检查点评估。
    当前选定范围内节点返回可评估的 passage_id；范围外 TLR 节点仍可读取，但返回不含 passage_id 的低优先级 read_only 上下文。
    node_id、candidate_id 从 TLR 或搜索结果取得，不用标题或猜测值。source_node_id 是需求，不是设计证据。高优先候选使用 get_mandatory_tlr_nodes 返回同一项的 items[].node_id、candidate_id。无候选的补充搜索结果用 JSON null，不用字符串 "None" 或猜测 ID。has_more_text=true 时从 end_offset 继续。范围是临时评审 checkpoint，不是新的 canonical 切块或检索单元。"""
    context = _runtime(ctx)
    candidate_binding = candidate_id or None
    if context.review_pipeline == "fixed_tlr" and candidate_binding is None:
        raise ValueError("固定 TLR 管线不注册补充资料；使用 read_next_tlr_material 读取固定候选。")
    node = json.loads(
        await _get(
            ctx,
            "get_canonical_node",
            f"/api/v1/projects/{context.project_id}/information/nodes/{node_id}",
            {"text_start": start_offset, "text_limit": text_limit},
        )
    )
    text = str(node.get("text") or "")
    if not text:
        raise ValueError("passage has no textual canonical content")
    in_selected_nodes = (
        not context.bound_target_node_ids or node_id in context.bound_target_node_ids
    )
    in_selected_artifacts = (
        not context.bound_target_artifact_ids
        or node.get("artifact_id") in context.bound_target_artifact_ids
    )
    if not in_selected_nodes or not in_selected_artifacts:
        # TLR reads are intentionally broader than the persisted review scope.
        # An unconnected node is useful discovery context, but it must not be
        # registered as a current passage or silently become evidence.
        return _dump(
            {
                "execution_status": "read_only",
                "operation": "read_review_passage",
                "passage_id": None,
                "node_id": node_id,
                "candidate_id": candidate_binding,
                "artifact_id": node.get("artifact_id"),
                "text": text,
                "text_start": start_offset,
                "end_offset": start_offset + len(text),
                "text_total_chars": node.get("text_total_chars", len(text)),
                "has_more_text": node.get("has_more_text", False),
                "already_read": node.get("already_read", False),
                "repeat_read_count": node.get("repeat_read_count", 0),
                "repeat_read_warning": node.get("repeat_read_warning"),
                "investigation_priority": "low_unconnected_tlr",
                "read_scope": "unconnected_tlr_read_only",
                "canonical_evidence": False,
                "current_stage": "read_only_context",
                "instruction": "此 canonical 节点在用户选定目标范围外，但可低优先级阅读。has_more_text=true 时从 end_offset 继续。本次只读未创建 passage 或证据；需保存评估时使用用户选定的目标节点。",
            }
        )
    # Lifecycle constraints govern state-changing passage registration, not
    # access to unrelated canonical context.
    if context.store.stage_complete("review_analysis_verified"):
        context.store.tool_error("read_review_passage", "analysis_lifecycle_completed")
        return _dump(
            {
                "execution_status": "blocked",
                "operation": "read_review_passage",
                "current_stage": "propose_overall_assessment",
                "error_code": "analysis_lifecycle_completed",
                "instruction": "检查点裁决已经完成；可用 read_document_content 只读上下文，或调用 propose_review_assessment。不要注册新资料段。",
            }
        )
    workspace = await _workspace(context)
    sentence = next(
        (s for s in workspace.get("sentences", []) if s.get("sentence_id") == context.sentence_id),
        None,
    )
    if sentence is None or not sentence.get("checks_finalized"):
        context.store.tool_error("read_review_passage", "checkset_not_finalized")
        return _dump(
            {
                "execution_status": "blocked",
                "operation": "read_review_passage",
                "current_stage": "extract_checks",
                "error_code": "checkset_not_finalized",
                "node_id": node_id,
                "instruction": "本请求未创建资料段。先读取完整原文和已有检查点，补充缺失项并 finalize_review_checks，再调查证据。只读上下文用 read_document_content。",
            }
        )
    # Reopening an already-created range with a different optional candidate
    # binding is not a new investigation.  If its prior execution is blocked,
    # return that durable state instead of asking the backend to mutate the
    # foreign-key binding or replay the same failed assessment.
    end_offset = start_offset + len(text)
    existing = next(
        (
            p
            for p in workspace.get("passages", [])
            if p.get("sentence_id") == context.sentence_id
            and p.get("design_node_id") == node_id
            and p.get("start_offset") == start_offset
            and p.get("end_offset") == end_offset
        ),
        None,
    )
    if existing and existing.get("status") == "blocked":
        return _dump(
            {
                "passage_id": existing.get("passage_id"),
                "node_id": node_id,
                "current_stage": "blocked_execution",
                "candidate_id": existing.get("candidate_id"),
                "start_offset": start_offset,
                "end_offset": end_offset,
                "execution_status": "blocked",
                "error_code": existing.get("error_code") or "passage_execution_failed",
                "error_message": existing.get("error_message") or "passage is already blocked",
                "instruction": "不要重试或重新绑定本 blocked 资料段；选择其他范围，或保留 blocked 结束。",
            }
        )
    # A null candidate binding means this is a supplementary investigation
    # passage (usually from bounded BM25), rather than a mandatory formal-TLR
    # candidate. Mandatory items must be exhausted first, and supplementary
    # material has a durable per-segment cap so an unbounded Runner cannot
    # turn search into an endless list walk. Re-reading an existing range was
    # handled above and remains idempotent.
    if candidate_binding is None and existing is None:
        investigation = await context.client.get(
            f"/api/v1/projects/{context.project_id}/reviews/{context.review_id}"
            f"/sentences/{context.sentence_id}/investigation"
        )
        mandatory_remaining = investigation.get("mandatory_unattempted_node_ids",
                                                 investigation.get("mandatory_remaining_node_ids")) or []
        if mandatory_remaining:
            context.store.tool_error(
                "read_review_passage", "supplementary_before_mandatory_complete"
            )
            return _dump(
                {
                    "execution_status": "blocked",
                    "operation": "read_review_passage",
                    "current_stage": "select_mandatory_sds_passage",
                    "error_code": "supplementary_before_mandatory_complete",
                    "mandatory_remaining_node_ids": mandatory_remaining,
                    "instruction": "先用 read_next_tlr_material 完成剩余高优先资料的阅读和评估，再由 Review Analysis 通过 investigate_review_material 调查补充资料。",
                }
            )
        supplemental = [
            p
            for p in workspace.get("passages", [])
            if p.get("sentence_id") == context.sentence_id and not p.get("candidate_id")
        ]
        if len(supplemental) >= context.supplemental_passage_limit:
            context.store.tool_error("read_review_passage", "supplementary_passage_limit_reached")
            return _dump(
                {
                    "execution_status": "blocked",
                    "operation": "read_review_passage",
                    "current_stage": "supplementary_sds_search_or_conclude",
                    "error_code": "supplementary_passage_limit_reached",
                    "supplemental_passage_count": len(supplemental),
                    "supplemental_passage_limit": context.supplemental_passage_limit,
                    "instruction": "配置的额外 SDS 资料数量已用尽。根据已保存证据和检查点形成结论，不再打开新资料段。",
                }
            )
    result = json.loads(
        await _write(
            ctx,
            "read_review_passage",
            "POST",
            f"/api/v1/projects/{context.project_id}/reviews/{context.review_id}/passages",
            {
                "sentence_id": context.sentence_id,
                "node_id": node_id,
                "start_offset": start_offset,
                "end_offset": end_offset,
                "candidate_id": candidate_binding,
            },
        )
    )
    context.store.data["active_passage_id"] = result["passage_id"]
    _set_review_phase(
        context,
        "assess_current_passage",
        "对每个已确认检查点调用 assess_review_check，再调用 finalize_review_passage。",
    )
    context.store._save()
    return _dump(
        {
            **result,
            "heading_path": node.get("heading_path"),
            "has_more_text": node.get("has_more_text", False),
            "already_read": node.get("already_read", False),
            "repeat_read_count": node.get("repeat_read_count", 0),
            "repeat_read_warning": node.get("repeat_read_warning"),
            "investigation_priority": "current_tlr" if candidate_binding else "low_unconnected_tlr",
            "read_scope": "current_review_passage",
            "current_stage": "assess_current_passage",
            "next_required_action": (
                "先对全部已确认检查点调用 assess_review_check，再 finalize_review_passage；此前不要打开其他资料段。"
            ),
            "instruction": "用本范围评估全部已确认检查点；此处未提及不等于设计未实现",
        }
    )


@_tool_decorator(timeout=30.0)
async def assess_review_passage(
    ctx: RunContextWrapper[SuggestionContext],
    passage_id: str,
    decisions: list[PassageCheckAssessment],
    finalize: bool = True,
) -> str:
    """一起保存当前资料对所有检查点的逐字证据和判断，不建立各点独立调查。
    status 是基于全部已保存证据的累积判断，relation 只表达当前资料关系。检查点多时分组 finalize=false，最后组 finalize=true。当前资料未提及的检查点也须记录 irrelevant、理由和 quotes=[]。supporting/counter/context 使用本资料逐字 exact_quote；代码计算偏移，不自行数位置。"""
    context = _runtime(ctx)
    workspace = await _workspace(context)
    if not any(
        p.get("passage_id") == passage_id and p.get("sentence_id") == context.sentence_id
        for p in workspace.get("passages", [])
    ):
        raise ValueError("passage is outside current Agent sentence")
    existing = next(
        (
            p
            for p in workspace.get("passages", [])
            if p.get("passage_id") == passage_id and p.get("sentence_id") == context.sentence_id
        ),
        None,
    )
    if existing and existing.get("status") == "blocked":
        # A failed passage is an execution fact, not a new semantic result.
        # Prevent replay of the same rejected request while preserving its
        # error code/message for the manager and verifier.
        return _dump(
            {
                "passage_id": passage_id,
                "execution_status": "blocked",
                "error_code": existing.get("error_code") or "passage_execution_failed",
                "error_message": existing.get("error_message") or "passage is already blocked",
                "instruction": "不要重试本 blocked 资料段。",
            }
        )
    page = await context.client.get(
        f"/api/v1/projects/{context.project_id}/information/nodes/{existing['design_node_id']}",
        {
            "text_start": existing["start_offset"],
            "text_limit": existing["end_offset"] - existing["start_offset"],
        },
    )
    try:
        payload = locate_passage_quotes(
            decisions, str(page.get("text") or ""), existing["start_offset"]
        )
    except ValueError as exc:
        context.store.tool_error("assess_review_passage", str(exc))
        return await _passage_failure(ctx, passage_id, "assess_review_passage", "evidence_quote_invalid", exc)
    return await _write(
        ctx,
        "assess_review_passage",
        "POST",
        f"/api/v1/projects/{context.project_id}/reviews/{context.review_id}/passages/{passage_id}/assess",
        {"decisions": payload, "finalize": finalize},
    )


@_tool_decorator(timeout=30.0)
async def assess_review_check(
    ctx: RunContextWrapper[SuggestionContext],
    passage_id: str,
    check_id: str,
    relation: Literal["supporting", "counter", "context", "irrelevant", "needs_context"],
    status: Literal["pending", "supported", "contradicted", "insufficient", "uncertain"],
    note: str = Field(min_length=1, max_length=2000),
    exact_quotes: list[str] = Field(default_factory=list, max_length=8),  # noqa: B008
) -> str:
    """即时保存一个资料段对一个检查点的判断，避免输出庞大嵌套数组。
    传真实 passage_id、check_id、关系、累积状态、理由与逐字引文。所有检查点逐项保存后再调用 finalize_review_passage。仍执行后台原子写入和严格引用校验，工具不会发明判断或证据。"""
    context = _runtime(ctx)
    workspace = await _workspace(context)
    passage = next(
        (
            p
            for p in workspace.get("passages", [])
            if p.get("passage_id") == passage_id and p.get("sentence_id") == context.sentence_id
        ),
        None,
    )
    if passage is None:
        raise ValueError("passage is outside current Agent sentence")
    if passage.get("status") == "blocked":
        return _dump({"passage_id": passage_id, "execution_status": "blocked", "skipped": True,
                      "error_code": passage.get("error_code"), "error_message": passage.get("error_message"),
                      "next_required_action": "此资料已失败并跳过，调用 read_next_tlr_material 继续其他独立资料。"})
    if not any(
        c.get("check_id") == check_id and c.get("sentence_id") == context.sentence_id
        for c in workspace.get("checks", [])
    ):
        raise ValueError("check is outside current Agent sentence")
    node = json.loads(
        await _get(
            ctx,
            "get_canonical_node",
            f"/api/v1/projects/{context.project_id}/information/nodes/{passage['design_node_id']}",
            {
                "text_start": passage["start_offset"],
                "text_limit": passage["end_offset"] - passage["start_offset"],
            },
        )
    )
    text = str(node.get("text") or "")
    payload = {
        "check_id": check_id,
        "relation": relation,
        "status": status,
        "note": note,
        "quotes": [] if relation in {"irrelevant", "needs_context"}
        else [{"exact_quote": quote} for quote in exact_quotes],
    }
    try:
        decisions = locate_passage_quotes(
            [PassageCheckAssessment.model_validate(payload)], text, passage["start_offset"]
        )
    except ValueError as exc:
        context.store.tool_error("assess_review_check", str(exc))
        return await _passage_failure(ctx, passage_id, "assess_review_check", "evidence_quote_invalid", exc)
    raw = await _write(
        ctx,
        "assess_review_check",
        "POST",
        f"/api/v1/projects/{context.project_id}/reviews/{context.review_id}/passages/{passage_id}/assess",
        {"decisions": decisions, "finalize": False},
    )
    if json.loads(raw).get("execution_status") in {"retry_required", "blocked"}:
        return raw
    _set_review_phase(
        context,
        "assess_current_passage",
        "对本资料涉及的每个已确认检查点逐项调用 assess_review_check，之后 finalize_review_passage。",
    )
    return _annotate_phase(
        raw,
        "assess_current_passage",
        "对本资料涉及的每个已确认检查点逐项调用 assess_review_check，之后 finalize_review_passage。",
    )


@_tool_decorator(timeout=30.0)
async def finalize_review_passage(
    ctx: RunContextWrapper[SuggestionContext], passage_id: str
) -> str:
    """根据已经保存的逐检查点决策完成当前资料段。
    确定性投影工作区事实，后台再次验证每条逐字引用、candidate 绑定和检查点集合条件。"""
    context = _runtime(ctx)
    workspace = await _workspace(context)
    passage = next(
        (
            p
            for p in workspace.get("passages", [])
            if p.get("passage_id") == passage_id and p.get("sentence_id") == context.sentence_id
        ),
        None,
    )
    if passage is None:
        raise ValueError("passage is outside current Agent sentence")
    if passage.get("status") == "blocked":
        return _dump({"passage_id": passage_id, "execution_status": "blocked", "skipped": True,
                      "error_code": passage.get("error_code"), "error_message": passage.get("error_message"),
                      "next_required_action": "此资料已失败并跳过，不改为 completed；继续其他独立资料。"})
    if passage.get("status") == "completed":
        # assess() already completes a range once its last check is saved.
        # Re-reading completion is idempotent, even after the sentence closes.
        coverage = await context.client.get(
            f"/api/v1/projects/{context.project_id}/reviews/{context.review_id}"
            f"/sentences/{context.sentence_id}/investigation"
        )
        return _dump(
            {
                **coverage,
                "passage_id": passage_id,
                "passage_status": "completed",
                "already_completed": True,
                "current_stage": "select_next_sds_passage_or_conclude",
                "next_required_action": "调用 get_review_investigation 并遵循 current_stage，不重新打开已经完成的资料段。",
            }
        )
    evidence = {row.get("evidence_id"): row for row in workspace.get("evidence", [])}
    decisions = []
    for assessment in passage.get("assessments", []):
        quotes = []
        for evidence_id in assessment.get("evidence_ids", []):
            if evidence_id not in evidence:
                raise ValueError("saved_passage_evidence_missing")
            row = evidence[evidence_id]
            if (
                row.get("design_node_id") != passage["design_node_id"]
                or row.get("validation_status") != "valid"
                or not passage["start_offset"]
                <= row["start_offset"]
                < row["end_offset"]
                <= passage["end_offset"]
            ):
                raise ValueError("saved_passage_evidence_invalid")
            quotes.append({key: row[key] for key in ("exact_quote", "start_offset", "end_offset")})
        decisions.append(
            {
                "check_id": assessment["check_id"],
                "relation": assessment["relation"],
                "status": assessment["resulting_status"],
                "note": assessment["note"],
                "quotes": quotes,
            }
        )
    if not decisions:
        return _dump(
            {
                "passage_id": passage_id,
                "execution_status": "blocked",
                "error_code": "passage_has_no_saved_assessments",
                "error_message": "尚无已保存的逐检查点决策，先评估每个检查点。",
            }
        )
    raw = await _write(
        ctx,
        "finalize_review_passage",
        "POST",
        f"/api/v1/projects/{context.project_id}/reviews/{context.review_id}/passages/{passage_id}/assess",
        {"decisions": decisions, "finalize": True},
    )
    if json.loads(raw).get("execution_status") in {"retry_required", "blocked"}:
        return raw
    _set_review_phase(
        context,
        "select_next_sds_passage_or_conclude",
        "调用 get_review_investigation；证据充分则综合裁决每个检查点，否则选择下一个允许的资料段。",
    )
    return _annotate_phase(
        raw,
        "select_next_sds_passage_or_conclude",
        "调用 get_review_investigation；证据充分则综合裁决每个检查点，否则选择下一个允许的资料段。",
    )


def locate_passage_quotes(
    decisions: list[PassageCheckAssessment], text: str, start: int
) -> list[dict]:
    """Same unique exact-string anchoring used for source checks; no fuzzy matching.

    Only the registered passage may supply evidence. Missing, ambiguous and
    paraphrased quotes are rejected; the backend independently revalidates all
    computed offsets, candidate ownership and the canonical fingerprint.
    """
    payload = []
    for decision in decisions:
        row = decision.model_dump()
        row["quotes"] = []
        for quote in decision.quotes:
            if text.count(quote.exact_quote) != 1:
                raise ValueError("evidence_quote_missing_or_ambiguous_in_passage")
            offset = start + text.index(quote.exact_quote)
            row["quotes"].append(
                {
                    "exact_quote": quote.exact_quote,
                    "start_offset": offset,
                    "end_offset": offset + len(quote.exact_quote),
                }
            )
        payload.append(row)
    return payload


@_tool_decorator(timeout=30.0)
async def record_passage_execution_error(
    ctx: RunContextWrapper[SuggestionContext], passage_id: str, error_code: str, error_message: str
) -> str:
    """供宿主恢复路径记录资料执行错误，不暴露为 Agent 工具。
    模型不能通过调用它证明服务或传输出错；错误仅由 SDK/宿主异常路径记录，此辅助函数用于受控管理恢复与历史 checkpoint 查看。"""
    context = _runtime(ctx)
    workspace = await _workspace(context)
    if not any(
        p.get("passage_id") == passage_id and p.get("sentence_id") == context.sentence_id
        for p in workspace.get("passages", [])
    ):
        raise ValueError("passage is outside current Agent sentence")
    return await _write(
        ctx,
        "record_passage_execution_error",
        "POST",
        f"/api/v1/projects/{context.project_id}/reviews/{context.review_id}/passages/{passage_id}/error",
        {"error_code": error_code, "error_message": error_message},
    )


@_tool_decorator(timeout=30.0)
async def record_review_evidence(
    ctx: RunContextWrapper[SuggestionContext],
    check_id: str,
    node_id: str,
    exact_quote: str = Field(min_length=1),
    relation: Literal["supporting", "counter", "context"] = "context",
    candidate_id: str | None = None,
) -> str:
    """在 canonical 原文中定位唯一范围并校验后保存逐字证据。"""
    context = _runtime(ctx)
    workspace = await _workspace(context)
    if not any(
        c.get("check_id") == check_id and c.get("sentence_id") == context.sentence_id
        for c in workspace.get("checks", [])
    ):
        raise ValueError("check is outside current Agent sentence")
    # Do not fetch canonical text for a node that is outside the user-bound
    # target scope.  The backend rejects it too, but the host must not expose
    # that text to the model before the rejection is returned.
    if context.bound_target_node_ids and node_id not in context.bound_target_node_ids:
        raise ValueError("evidence node outside selected TLR node scope")
    node_path = f"/api/v1/projects/{context.project_id}/information/nodes/{node_id}"
    parts = []
    offset = 0
    while True:
        page = json.loads(
            await _get(
                ctx, "get_canonical_node", node_path, {"text_start": offset, "text_limit": 8000}
            )
        )
        chunk = str(page.get("text") or "")
        if not chunk and page.get("has_more_text"):
            raise ValueError("canonical_text_page_did_not_advance")
        parts.append(chunk)
        offset += len(chunk)
        if not page.get("has_more_text"):
            break
    full_text = "".join(parts)
    if full_text.count(exact_quote) != 1:
        raise ValueError("evidence_quote_missing_or_ambiguous")
    start_offset = full_text.index(exact_quote)
    end_offset = start_offset + len(exact_quote)
    return await _write(
        ctx,
        "record_review_evidence",
        "POST",
        f"/api/v1/projects/{context.project_id}/reviews/{context.review_id}/evidence",
        {
            "check_id": check_id,
            "design_node_id": node_id,
            "start_offset": start_offset,
            "end_offset": end_offset,
            "exact_quote": exact_quote,
            "relation": relation,
            "source": "sdk_review_analysis",
            "candidate_id": candidate_id,
        },
    )
