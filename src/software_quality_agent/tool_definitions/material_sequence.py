"""Advance official TLR material in its saved order, without model ID selection."""

from __future__ import annotations

import json

from agents import RunContextWrapper
from pydantic import Field

from ..review_runtime.context import SuggestionContext
from ..review_runtime.navigation import locate_node, resolve_location
from .common import _dump, _runtime, _tool_decorator, _workspace
from .review_evidence import read_review_passage


def next_unattempted_offset(passages: list[dict], node_id: str, total: int) -> int:
    """Already attempted ranges (including blocked) are not silently retried.

    A blocked range remains blocked in backend coverage. Skipping it for cursor
    progression does NOT accept its evidence or mark the node inspected.
    """
    ranges = sorted((int(p["start_offset"]), int(p["end_offset"])) for p in passages
                    if p.get("design_node_id") == node_id)
    start = 0
    for left, right in ranges:
        if left > start:
            break
        start = max(start, right)
    return min(start, total)


async def _open(ctx, node_id: str, candidate_id: str | None, start: int, limit: int) -> dict:
    raw = await read_review_passage.on_invoke_tool(ctx, json.dumps(
        {"node_id": node_id, "candidate_id": candidate_id,
         "start_offset": start, "text_limit": limit}, ensure_ascii=False))
    try:
        value = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"资料读取未成功：{raw}") from exc
    return {**value, **await locate_node(_runtime(ctx), node_id)}


@_tool_decorator(timeout=30.0)
async def read_next_tlr_material(ctx: RunContextWrapper[SuggestionContext],
                                 text_limit: int = Field(4000, ge=1, le=8000)) -> str:
    """切换到当前需求语块的下一份高优先 TLR 资料，不用挑选候选或填写 ID。
    资料按正式 TLR 已保存的顺序推进。当前资料未评估完不能换资料。
    所有检查点已有有效支持时结束调查；否则依次阅读，读完后再决定是否补充查目录。
    返回本份资料的语义原文、章节位置、passage_id 与下一动作；并非新增 TLR。"""
    context = _runtime(ctx)
    if context.store.stage_complete("review_analysis_verified"):
        return _dump({"execution_status": "ready_to_conclude", "next_required_action": "不再调查，提交整体评价。"})
    workspace = await _workspace(context)
    sentence = next((s for s in workspace.get("sentences", []) if s.get("sentence_id") == context.sentence_id), {})
    if not sentence.get("checks_finalized"):
        raise ValueError("先完成并确认检查点集合，才能切换高优先资料")
    passages = [p for p in workspace.get("passages", []) if p.get("sentence_id") == context.sentence_id
                and p.get("checkset_version") == sentence.get("checkset_version")]
    investigation = await context.client.get(
        f"/api/v1/projects/{context.project_id}/reviews/{context.review_id}/sentences/{context.sentence_id}/investigation")
    if investigation.get("can_stop_for_sufficient_evidence"):
        return _dump({"execution_status": "ready_to_conclude", "can_stop_for_sufficient_evidence": True,
                      "next_required_action": "全部检查点已有有效支持且无反证。立即结束调查，保存综合结论；历史异常和未完成资料原样保留。"})
    active = next((p for p in passages if p.get("status") in {"pending", "in_progress"}), None)
    if active:
        context.store.data["active_passage_id"] = active["passage_id"]
        context.store._save()
        return _dump({"execution_status": "current_material_pending", "passage_id": active["passage_id"],
                      **await locate_node(context, active["design_node_id"]),
                      "next_required_action": "先用当前资料评估全部检查点并 finalize_review_passage，不跳过当前资料。"})
    prefix = f"/api/v1/projects/{context.project_id}/information"
    offset, seen = 0, set()
    while True:
        page = await context.client.get(
            prefix + f"/tlr-runs/{context.bound_run_id}/nodes/{context.bound_source_node_id}/mandatory",
            {"offset": offset, "limit": 100, "review_id": context.review_id})
        for candidate in page.get("items", []):
            node_id = candidate["node_id"]
            if node_id in seen:
                continue
            seen.add(node_id)
            node = await context.client.get(prefix + f"/nodes/{node_id}", {"text_start": 0, "text_limit": 1})
            total = int(node.get("text_total_chars") or 0)
            start = next_unattempted_offset(passages, node_id, total)
            if start < total:
                return _dump(await _open(ctx, node_id, candidate.get("candidate_id"), start, text_limit))
            if not total:
                raise ValueError("高优先 TLR 资料没有可读取的原文；不伪造空资料评估")
        if not page.get("has_more"):
            break
        next_offset = page.get("next_offset")
        if not isinstance(next_offset, int) or next_offset <= offset:
            raise ValueError("TLR material cursor did not advance")
        offset = next_offset
    blocked = [p for p in passages if p.get("status") in {"blocked", "failed"}]
    context.store.data["active_passage_id"] = None
    context.store._save()
    return _dump({"execution_status": "priority_materials_exhausted",
                  "review_pipeline": context.review_pipeline,
                  "blocked_material_count": len(blocked),
                  "error_code": "priority_material_execution_failed" if blocked else None,
                  "next_required_action": (
                      "固定 TLR 资料已耗尽，不再搜索补充资料。有执行失败或无固定资料时调用 finish_review_incomplete；否则提交所有检查点在固定资料范围内的综合结论。"
                      if context.review_pipeline == "fixed_tlr" else
                      "高优先资料已尝试完，失败资料保留并跳过。可以调查额外资料；若仍无法可靠收敛，调用 finish_review_incomplete 结束本语段，继续其他语段。" if blocked
                      else "高优先资料已读完。检查是否结束调查；需要更多资料时自行按结构目录选择补充范围。")})


@_tool_decorator(timeout=30.0)
async def open_supplementary_material(ctx: RunContextWrapper[SuggestionContext], location: str,
                                       start_offset: int = Field(0, ge=0), text_limit: int = Field(4000, ge=1, le=8000)) -> str:
    """高优先资料之后，把自行选定结构位置的 SDS 原文注册为补充调查资料。
    先看 browse_document_structure 的标题和子标题，再复制 location，不填写节点/候选 UUID。
    原有范围、逐字引用、资料数量、当前未完成资料等校验不放宽。"""
    context = _runtime(ctx)
    if context.review_pipeline == "fixed_tlr":
        raise ValueError("固定 TLR 管线没有补充资料调查阶段。")
    workspace = await _workspace(context)
    if any(p.get("sentence_id") == context.sentence_id and p.get("status") in {"pending", "in_progress"}
           for p in workspace.get("passages", [])):
        raise ValueError("先完成当前资料的全部检查点评估，再打开补充资料")
    node = await resolve_location(context, location)
    if node.get("node_type") not in {"paragraph", "table"}:
        raise ValueError("标题分支不是证据正文。请查看其子节点并选择 paragraph/table 的 location")
    return _dump(await _open(ctx, node["node_id"], None, start_offset, text_limit))
