"""tlr definitions for the SDK review workflow."""

from __future__ import annotations

import json

from agents import RunContextWrapper
from pydantic import Field

from ..review_runtime.context import SuggestionContext
from .common import (
    _annotate_phase,
    _annotate_tlr_priority,
    _dump,
    _get,
    _runtime,
    _set_review_phase,
    _tool_decorator,
    _write,
)


@_tool_decorator(timeout=30.0)
async def mark_mandatory_node_visited(
    ctx: RunContextWrapper[SuggestionContext], node_id: str, note: str = ""
) -> str:
    """保存一个高优先 TLR 节点已被实际检查的记录。"""
    context = _runtime(ctx)
    inspected = any(
        call.get("name") == "get_canonical_node"
        and call.get("succeeded")
        and str(call.get("arguments", {}).get("path", "")).endswith(f"/nodes/{node_id}")
        for call in context.store.data.get("tool_calls", [])
    )
    if not inspected:
        raise ValueError("mandatory node must be read through get_canonical_node before visit")
    return await _write(
        ctx,
        "mark_mandatory_node_visited",
        "POST",
        f"/api/v1/projects/{context.project_id}/reviews/{context.review_id}/mandatory-visits",
        {"design_node_id": node_id, "note": note},
    )


@_tool_decorator(timeout=30.0)
async def mark_mandatory_nodes_visited(
    ctx: RunContextWrapper[SuggestionContext], node_ids: list[str], note: str = ""
) -> str:
    """确认一页高优先节点已检查；须先阅读对应 canonical 原文。"""
    context = _runtime(ctx)
    if not node_ids or len(node_ids) > 20 or len(set(node_ids)) != len(node_ids):
        raise ValueError("duplicate_mandatory_node_ids")
    successful_paths = {
        str(call.get("arguments", {}).get("path", ""))
        for call in context.store.data.get("tool_calls", [])
        if call.get("name") == "get_canonical_node" and call.get("succeeded")
    }
    if any(
        not any(path.endswith(f"/nodes/{node_id}") for path in successful_paths)
        for node_id in node_ids
    ):
        raise ValueError("mandatory_node_not_read")
    results = []
    for node_id in node_ids:
        results.append(
            json.loads(
                await _write(
                    ctx,
                    "mark_mandatory_node_visited",
                    "POST",
                    f"/api/v1/projects/{context.project_id}/reviews/{context.review_id}/mandatory-visits",
                    {"design_node_id": node_id, "note": note},
                )
            )
        )
    return _dump({"visited": results})


@_tool_decorator(timeout=30.0)
async def get_tlr_candidates(
    ctx: RunContextWrapper[SuggestionContext],
    run_id: str = "",
    source_node_id: str = "",
    offset: int = Field(0, ge=0),
    limit: int = Field(50, ge=1, le=100),
) -> str:
    """读取指定 source/run 对的正式 TLR 候选。
    ID 为空时用当前评审的 Run/源节点。可显式指定其他 TLR 或未连接的源节点，结果标为低优先级，不能仅凭其他 TLR 判断成为当前证据。"""
    context: SuggestionContext = ctx.context
    runtime = _runtime(ctx)
    run_id = run_id or runtime.bound_run_id
    source_node_id = source_node_id or runtime.bound_source_node_id
    if not run_id or not source_node_id:
        raise ValueError("run_id_and_source_node_id_are_required")
    current = run_id == runtime.bound_run_id and source_node_id == runtime.bound_source_node_id
    raw = await _get(
        ctx,
        "get_tlr_candidates",
        f"/api/v1/projects/{context.project_id}/information/tlr-runs/{run_id}/nodes/{source_node_id}/results",
        {"offset": offset, "limit": limit},
    )
    return _annotate_phase(
        _annotate_tlr_priority(raw, current=current, run_id=run_id, source_node_id=source_node_id),
        "select_mandatory_sds_passage" if current else "read_only_context",
        "使用本页同一项真实目标 node_id/candidate_id，不把 source_node_id 当 SDS 证据。"
        if current
        else "按目标 node_id 读取有用的低优先级上下文；当前范围内补充评估用 candidate_id=null，不用其他源节点/Run 的候选绑定。",
    )


@_tool_decorator(timeout=30.0)
async def get_mandatory_tlr_nodes(
    ctx: RunContextWrapper[SuggestionContext],
    run_id: str = "",
    source_node_id: str = "",
    offset: int = Field(0, ge=0),
    limit: int = Field(100, ge=1, le=100),
) -> str:
    """分页读取指定 Run/源节点的高优先候选。
    当前评审对应的候选为高优先；其他 Run/源节点也可调查，但明确标为低优先级。"""
    context: SuggestionContext = ctx.context
    runtime = _runtime(ctx)
    run_id = run_id or runtime.bound_run_id
    source_node_id = source_node_id or runtime.bound_source_node_id
    if not run_id or not source_node_id:
        raise ValueError("run_id_and_source_node_id_are_required")
    current = run_id == runtime.bound_run_id and source_node_id == runtime.bound_source_node_id
    active_current = current and not runtime.store.stage_complete("review_analysis_verified")
    # Keep each candidate page small enough to remain actionable in the local
    # model context. The complete set remains available through next_offset;
    # accepting a model-requested limit of 100 caused the SDK to replace the
    # result with a saved-result index, after which the model repeatedly
    # paged/summarised the same list until truncation. This is a transport
    # bound, not a retrieval Top-K or evidence limit.
    limit = min(limit, 3)
    effective_offset = offset
    cursor_key = json.dumps(
        {"run_id": run_id, "source_node_id": source_node_id, "review_id": runtime.review_id},
        sort_keys=True,
    )
    cursors = runtime.store.data.setdefault("mandatory_page_cursors", {})
    # Keep the returned cursor for recovery, but honor explicit read offsets.
    # Re-reading page zero must never silently skip unread candidates.
    raw = await _get(
        ctx,
        "get_mandatory_tlr_nodes",
        f"/api/v1/projects/{context.project_id}/information/tlr-runs/{run_id}/nodes/{source_node_id}/mandatory",
        {
            "offset": effective_offset,
            "limit": limit,
            "review_id": runtime.review_id if current else None,
        },
    )
    try:
        page = json.loads(raw)
    except (TypeError, ValueError):
        return raw
    if isinstance(page, dict):
        cursors[cursor_key] = {
            "offset": effective_offset,
            "next_offset": page.get("next_offset"),
            "has_more": bool(page.get("has_more")),
        }
        if active_current:
            _set_review_phase(
                runtime,
                "select_mandatory_sds_passage",
                "选择同一项 items[].node_id/candidate_id，调用 read_review_passage。",
            )
        runtime.store._save()
        return _annotate_tlr_priority(
            _dump(
                {
                    **page,
                    "current_stage": "select_mandatory_sds_passage"
                    if active_current
                    else "read_only_context",
                    "next_required_action": (
                        "按真实 node_id 读取有用的低优先级上下文，不将这些节点加入当前高优先台账。合格补充资料使用 candidate_id=null。"
                        if not current
                        else "检查点裁决已完成。本页仅作只读上下文，不注册新资料段，返回整体评价。"
                        if not active_current
                        else "选择同一项 items[].node_id/candidate_id，调用 read_review_passage。"
                        if page.get("items")
                        else "本页没有可用高优先候选；调用 get_review_investigation 并遵循 next_required_action。"
                    ),
                }
            ),
            current=current,
            run_id=run_id,
            source_node_id=source_node_id,
        )
    return raw


@_tool_decorator(timeout=30.0)
async def get_mandatory_evidence_page(
    ctx: RunContextWrapper[SuggestionContext],
    offset: int = Field(0, ge=0),
    limit: int = Field(3, ge=1, le=3),
) -> str:
    """读取一页当前绑定的高优先 TLR 候选及真实 canonical 原文。
    has_more=true 时用 next_offset 继续。每个节点的 text_total_chars、has_more_text 表示是否需用 get_canonical_node 继续读取。"""
    context = _runtime(ctx)
    run_id = context.bound_run_id
    source_id = context.bound_source_node_id
    mandatory = json.loads(
        await _get(
            ctx,
            "get_mandatory_tlr_nodes",
            f"/api/v1/projects/{context.project_id}/information/tlr-runs/{run_id}/nodes/{source_id}/mandatory",
            {"offset": offset, "limit": limit, "review_id": context.review_id},
        )
    )
    items = []
    for candidate in mandatory.get("items", []):
        node_id = candidate["node_id"]
        node = json.loads(
            await _get(
                ctx,
                "get_canonical_node",
                f"/api/v1/projects/{context.project_id}/information/nodes/{node_id}",
                {"text_start": 0, "text_limit": 8000, "include_structure": False},
            )
        )
        current_scope = (
            not context.bound_target_node_ids or node_id in context.bound_target_node_ids
        )
        items.append(
            {
                "candidate": candidate,
                "investigation_priority": "current_tlr" if current_scope else "low_unconnected_tlr",
                "read_scope": "current_review_tlr"
                if current_scope
                else "unconnected_tlr_read_only",
                "node": {
                    key: node.get(key)
                    for key in (
                        "node_id",
                        "artifact_id",
                        "parent_id",
                        "node_type",
                        "title",
                        "reading_order",
                        "heading_path",
                        "text",
                        "text_total_chars",
                        "has_more_text",
                    )
                },
            }
        )
    return _dump(
        {
            "source": "formal_tlr_and_canonical_tree",
            "items": items,
            "has_more": mandatory.get("has_more", False),
            "next_offset": mandatory.get("next_offset"),
            "instruction": "当前范围内候选优先；low_unconnected_tlr 项仅作只读上下文，不能直接保存为当前证据。",
        }
    )


@_tool_decorator(timeout=30.0)
async def get_trace_links(
    ctx: RunContextWrapper[SuggestionContext],
    run_id: str = "",
    node_id: str = "",
    offset: int = Field(0, ge=0),
    limit: int = Field(50, ge=1, le=100),
) -> str:
    """读取任意 Run/节点的已保存 TraceLink；非当前任务的读取为低优先级。"""
    context: SuggestionContext = ctx.context
    runtime = _runtime(ctx)
    run_id = run_id or runtime.bound_run_id
    node_id = node_id or runtime.bound_source_node_id
    if not run_id or not node_id:
        raise ValueError("run_id_and_node_id_are_required")
    raw = await _get(
        ctx,
        "get_trace_links",
        f"/api/v1/projects/{context.project_id}/information/tlr-runs/{run_id}/nodes/{node_id}/links",
        {"offset": offset, "limit": limit},
    )
    return _annotate_tlr_priority(
        raw,
        current=run_id == runtime.bound_run_id and node_id == runtime.bound_source_node_id,
        run_id=run_id,
        node_id=node_id,
    )


@_tool_decorator(timeout=30.0)
async def get_run_detail(
    ctx: RunContextWrapper[SuggestionContext],
    run_id: str = "",
    failure_offset: int = Field(0, ge=0),
    failure_limit: int = Field(50, ge=1, le=100),
) -> str:
    """读取任意 TLR Run 的配置和指标；非当前 Run 仅为低优先级上下文。"""
    context: SuggestionContext = ctx.context
    runtime = _runtime(ctx)
    run_id = run_id or runtime.bound_run_id
    if not run_id:
        raise ValueError("run_id_is_required")
    raw = await _get(
        ctx,
        "get_run_detail",
        f"/api/v1/projects/{context.project_id}/information/tlr-runs/{run_id}",
        {"failure_offset": failure_offset, "failure_limit": failure_limit},
    )
    return _annotate_tlr_priority(raw, current=run_id == runtime.bound_run_id, run_id=run_id)


@_tool_decorator(timeout=30.0)
async def get_run_history(
    ctx: RunContextWrapper[SuggestionContext],
    offset: int = Field(0, ge=0),
    limit: int = Field(30, ge=1, le=100),
) -> str:
    """列出真实 run_id，用于当前或低优先级跨 TLR 调查。"""
    context: SuggestionContext = ctx.context
    return await _get(
        ctx,
        "get_run_history",
        f"/api/v1/projects/{context.project_id}/information/tlr-runs",
        {"offset": offset, "limit": limit},
    )


@_tool_decorator(timeout=30.0)
async def get_annotations(
    ctx: RunContextWrapper[SuggestionContext],
    run_id: str = "",
    node_id: str | None = None,
    offset: int = Field(0, ge=0),
    limit: int = Field(50, ge=1, le=100),
) -> str:
    """读取任意 TLR Run 的 annotation；非当前 Run/节点作为低优先级上下文。"""
    context: SuggestionContext = ctx.context
    runtime = _runtime(ctx)
    run_id = run_id or runtime.bound_run_id
    if not run_id:
        raise ValueError("run_id_is_required")
    current = run_id == runtime.bound_run_id and (
        not node_id or node_id == runtime.bound_source_node_id
    )
    raw = await _get(
        ctx,
        "get_annotations",
        f"/api/v1/projects/{context.project_id}/information/tlr-runs/{run_id}/annotations",
        {"node_id": node_id, "offset": offset, "limit": limit},
    )
    return _annotate_tlr_priority(raw, current=current, run_id=run_id, node_id=node_id)
