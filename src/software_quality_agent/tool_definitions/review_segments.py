"""review_segments definitions for the SDK review workflow."""

from __future__ import annotations

from agents import RunContextWrapper
from pydantic import Field

from ..review_runtime.context import SuggestionContext
from .common import _dump, _get, _runtime, _set_review_phase, _tool_decorator


@_tool_decorator(timeout=30.0)
async def get_review_segment(
    ctx: RunContextWrapper[SuggestionContext],
    check_offset: int = Field(0, ge=0),
    check_limit: int = Field(100, ge=1, le=100),
    evidence_offset: int = Field(0, ge=0),
    evidence_limit: int = Field(100, ge=1, le=100),
    text_start: int = Field(0, ge=0),
    text_limit: int = Field(4000, ge=1, le=8000),
) -> str:
    """读取一个评审语段的原文、检查点、理由、状态及逐字证据。
    直接读取宿主已绑定的当前语段，不需要填写任务 ID。
    check_offset/evidence_offset 为各自列表游标；text_has_more=true 时用 text_next_start 继续。
    其他工件原文通过结构位置查询；此工具不改变当前任务。"""
    context: SuggestionContext = ctx.context
    sentence_id = context.sentence_id
    review_id = context.review_id
    is_current_sentence = review_id == context.review_id and sentence_id == context.sentence_id
    workspace = await context.client.get(
        f"/api/v1/projects/{context.project_id}/reviews/{review_id}/workspace"
    )
    sentence = next(
        (item for item in workspace.get("sentences", []) if item.get("sentence_id") == sentence_id),
        None,
    )
    if sentence is None:
        raise ValueError("sentence_id is not present in this review workspace")
    checks = [
        item for item in workspace.get("checks", []) if item.get("sentence_id") == sentence_id
    ]
    check_ids = {item.get("check_id") for item in checks}
    evidence = [item for item in workspace.get("evidence", []) if item.get("check_id") in check_ids]
    call_index = context.store.tool_call(
        "get_review_segment",
        {
            "review_id": review_id,
            "sentence_id": sentence_id,
            "check_offset": check_offset,
            "check_limit": check_limit,
            "evidence_offset": evidence_offset,
            "evidence_limit": evidence_limit,
            "text_start": text_start,
            "text_limit": text_limit,
        },
    )
    text_value = str(sentence.get("text") or "")
    sentence_page = {
        **sentence,
        "text": text_value[text_start : text_start + text_limit],
        "text_start": text_start,
        "text_total": len(text_value),
        "text_has_more": text_start + text_limit < len(text_value),
        "text_next_start": text_start + text_limit
        if text_start + text_limit < len(text_value)
        else None,
    }
    passage_rows = [
        item for item in workspace.get("passages", []) if item.get("sentence_id") == sentence_id
    ]
    current_stage = (
        "extract_checks"
        if not sentence.get("checks_finalized")
        else "assess_current_passage"
        if any(item.get("status") in {"pending", "in_progress"} for item in passage_rows)
        else "select_mandatory_sds_passage"
    )
    next_required_action = (
        "仅创建原文明确支持的缺失检查点，然后调用 finalize_review_checks。"
        if current_stage == "extract_checks"
        else "用当前资料评估每个检查点并完成该资料段。"
        if current_stage == "assess_current_passage"
        else "用 read_next_tlr_material 切换下一份高优先 SDS 资料。"
    )
    if is_current_sentence:
        # Reading the source is not a request to restart investigation. Use
        # the same scope-aware state projection as the progress tools.
        from .common import _review_phase

        scope = await context.client.get(
            f"/api/v1/projects/{context.project_id}/reviews/{review_id}"
            f"/sentences/{sentence_id}/investigation")
        current_stage, next_required_action = _review_phase(scope, sentence, pipeline=context.review_pipeline)
        if context.store.stage_complete("overall_assessment_validated"):
            current_stage, next_required_action = "draft_suggestion_or_complete", "仅存在已确认问题时生成建议，否则完成。"
        elif context.store.stage_complete("overall_assessment_proposed"):
            current_stage, next_required_action = "validate_overall_assessment", "返回管理 Agent 调度独立整体审核，不重新打开资料。"
        elif context.store.stage_complete("review_analysis_verified"):
            current_stage, next_required_action = "propose_overall_assessment", "综合结论已保存，提交整体评价，不重启调查。"
        _set_review_phase(context, current_stage, next_required_action)
    result = {
        "source": "review_workspace",
        "review_id": review_id,
        "sentence": sentence_page,
        "checks": checks[check_offset : check_offset + check_limit],
        "evidence": evidence[evidence_offset : evidence_offset + evidence_limit],
        "check_total": len(checks),
        "evidence_total": len(evidence),
        "next_check_offset": check_offset + check_limit
        if check_offset + check_limit < len(checks)
        else None,
        "next_evidence_offset": evidence_offset + evidence_limit
        if evidence_offset + evidence_limit < len(evidence)
        else None,
        "current_stage": current_stage if is_current_sentence else "read_only_context",
        "next_required_action": next_required_action
        if is_current_sentence
        else "修改检查点或证据前返回当前语段。",
        "read_scope": "current_review_sentence"
        if is_current_sentence
        else "other_review_sentence_read_only",
        "investigation_priority": "current_review"
        if is_current_sentence
        else "low_other_review_sentence",
    }
    context.store.tool_success(call_index, result)
    return _dump(result)


@_tool_decorator(timeout=30.0)
async def get_review_history(
    ctx: RunContextWrapper[SuggestionContext],
    run_id: str | None = None,
    source_node_id: str | None = None,
    offset: int = Field(0, ge=0),
    limit: int = Field(20, ge=1, le=100),
) -> str:
    """查询本项目真实 review_id、requirement_node_id。
    过滤项为 null 时列出全部评审，不只当前 TLR/源节点。用返回的 review_id 查 get_review_workspace_page 获取 sentence_id，再用 get_review_segment 读原文、检查点、理由和证据。其他评审结论仅为低优先级上下文，不是当前事实。"""
    context = _runtime(ctx)
    return await _get(
        ctx,
        "get_review_history",
        f"/api/v1/projects/{context.project_id}/reviews",
        {
            "tlr_run_id": run_id,
            "requirement_node_id": source_node_id,
            "offset": offset,
            "limit": limit,
        },
    )


@_tool_decorator(timeout=30.0)
async def get_review_workspace_page(
    ctx: RunContextWrapper[SuggestionContext],
    sentence_offset: int = Field(0, ge=0),
    sentence_limit: int = Field(50, ge=1, le=100),
    check_offset: int = Field(0, ge=0),
    check_limit: int = Field(100, ge=1, le=200),
    review_id: str = "",
) -> str:
    """按明确的语段/检查点分页读取评审索引，查找真实 sentence_id。
    完整单语段事实仍需 get_review_segment。review_id 为空用当前工作区；其他工作区 ID 从 get_review_history 取得，仅可读作上下文。"""
    context: SuggestionContext = ctx.context
    review_id = review_id or context.review_id
    workspace = await context.client.get(
        f"/api/v1/projects/{context.project_id}/reviews/{review_id}/workspace"
    )
    sentences = workspace.get("sentences", [])
    checks = workspace.get("checks", [])
    page_sentences = sentences[sentence_offset : sentence_offset + sentence_limit]
    page_ids = {item.get("sentence_id") for item in page_sentences}
    page_checks = [item for item in checks if item.get("sentence_id") in page_ids]
    return _dump(
        {
            "review": {
                key: workspace.get(key)
                for key in (
                    "review_id",
                    "status",
                    "tlr_run_id",
                    "requirement_node_id",
                    "summary",
                    "plan",
                )
            },
            "sentences": page_sentences,
            "checks": page_checks[check_offset : check_offset + check_limit],
            "sentence_total": len(sentences),
            "check_total": len(page_checks),
            "next_sentence_offset": sentence_offset + sentence_limit
            if sentence_offset + sentence_limit < len(sentences)
            else None,
            "next_check_offset": check_offset + check_limit
            if check_offset + check_limit < len(page_checks)
            else None,
            "read_scope": "current_review"
            if review_id == context.review_id
            else "other_review_read_only",
            "investigation_priority": "current_review"
            if review_id == context.review_id
            else "low_other_review",
        }
    )
