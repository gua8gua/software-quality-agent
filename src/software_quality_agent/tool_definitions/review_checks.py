"""review_checks definitions for the SDK review workflow."""

from __future__ import annotations

import json
from typing import Literal

from agents import RunContextWrapper
from pydantic import Field

from ..review_runtime.context import SuggestionContext
from ..review_runtime.contracts import CheckConclusion
from .common import (
    _annotate_phase,
    _dump,
    _runtime,
    _set_review_phase,
    _tool_decorator,
    _workspace,
    _write,
)


@_tool_decorator(timeout=30.0)
async def finalize_review_checks(
    ctx: RunContextWrapper[SuggestionContext], check_ids: list[str]
) -> str:
    """确认检查点提取已覆盖完整源原文；仅存在部分检查点不能视为完成。"""
    context = _runtime(ctx)
    raw = await _write(
        ctx,
        "finalize_review_checks",
        "POST",
        f"/api/v1/projects/{context.project_id}/reviews/{context.review_id}"
        f"/sentences/{context.sentence_id}/finalize-checks",
        {"check_ids": check_ids},
    )
    _set_review_phase(
        context,
        "select_mandatory_sds_passage",
        "调用 read_next_tlr_material 按正式顺序切换高优先资料，不选择候选 ID。",
    )
    return _annotate_phase(
        raw,
        "select_mandatory_sds_passage",
        "调用 read_next_tlr_material 按正式顺序切换高优先资料，不选择候选 ID。",
    )


@_tool_decorator(timeout=30.0)
async def create_review_check(
    ctx: RunContextWrapper[SuggestionContext],
    category: Literal["function_result", "condition_constraint"],
    statement: str = Field(min_length=1, max_length=2000),
    source_quote: str = Field(min_length=1),
) -> str:
    """即时保存检查点，source_quote 必须是源语段中唯一可定位的逐字引文。"""
    context = _runtime(ctx)
    sentence_id = context.sentence_id
    workspace = await _workspace(context)
    sentence = next(
        (row for row in workspace.get("sentences", []) if row.get("sentence_id") == sentence_id),
        None,
    )
    if sentence is None:
        raise ValueError("sentence_not_found")
    source_text = str(sentence.get("text") or "")
    if source_text.count(source_quote) != 1:
        raise ValueError("source_quote_missing_or_ambiguous")
    source_start = int(sentence.get("start_offset") or 0) + source_text.index(source_quote)
    source_end = source_start + len(source_quote)
    raw = await _write(
        ctx,
        "create_review_check",
        "POST",
        f"/api/v1/projects/{context.project_id}/reviews/{context.review_id}/checks",
        {
            "sentence_id": sentence_id,
            "category": category,
            "statement": statement,
            "source_start": source_start,
            "source_end": source_end,
        },
    )
    return _annotate_phase(
        raw, "extract_checks", "继续提取原文明确支持的检查点，覆盖完整原文后确认检查点集合。"
    )


@_tool_decorator(timeout=30.0)
async def update_review_check(
    ctx: RunContextWrapper[SuggestionContext],
    check_id: str,
    status: Literal["pending", "supported", "contradicted", "insufficient", "uncertain"],
    note: str = Field(default="", max_length=2000),
) -> str:
    """证据已保存后才持久化当前检查点状态。"""
    context = _runtime(ctx)
    return await _write(
        ctx,
        "update_review_check",
        "PATCH",
        f"/api/v1/projects/{context.project_id}/reviews/{context.review_id}/checks/{check_id}",
        {"status": status, "note": note},
    )


@_tool_decorator(timeout=30.0)
async def complete_review_analysis(
    ctx: RunContextWrapper[SuggestionContext],
    conclusions: list[CheckConclusion],
    finalize: bool = True,
) -> str:
    """完成资料驱动调查后，保存全部检查点的综合结论；大量结论可分组提交。
    每次一个或小组检查点用 finalize=false。每点提供基于全部已保存证据的累积状态和理由，不用最后资料的相关性说明代替最终理由。finalize=true 要求当前资料指纹下每个检查点都有显式结论。空 conclusions 只能结束已有完整结论台账，不能复制资料说明生成结论。"""
    context = _runtime(ctx)
    sentence_id = context.sentence_id
    result = json.loads(
        await _write(
            ctx,
            "complete_review_analysis",
            "POST",
            f"/api/v1/projects/{context.project_id}/reviews/{context.review_id}"
            f"/sentences/{sentence_id}/conclude-investigation",
            {"conclusions": [d.model_dump() for d in conclusions], "finalize": finalize,
             "review_pipeline": context.review_pipeline},
        )
    )
    if result.get("completed"):
        context.store.transition("review_analysis_verified", "completed", output=result)
    _set_review_phase(
        context,
        "propose_overall_assessment" if result.get("completed") else "conclude_checks",
        "基于检查点综合结论调用 propose_review_assessment。"
        if result.get("completed")
        else "提交其余检查点综合结论，最后一组再 finalize。",
    )
    result["current_stage"] = (
        "propose_overall_assessment" if result.get("completed") else "conclude_checks"
    )
    result["next_required_action"] = (
        "基于检查点累积结论调用 propose_review_assessment。"
        if result.get("completed")
        else "对剩余 check_ids 分组保存综合结论，finalize=false，最后一组再 finalize。"
    )
    return _dump(result)
