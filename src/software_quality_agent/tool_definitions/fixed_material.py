"""Read-only access to source and already registered fixed TLR material."""

from __future__ import annotations

import json

from agents import RunContextWrapper
from pydantic import Field

from ..review_runtime.context import SuggestionContext
from ..review_runtime.navigation import address_entries, resolve_location
from .common import _dump, _get, _runtime, _tool_decorator, _workspace


@_tool_decorator(timeout=30.0)
async def read_fixed_material_content(
    ctx: RunContextWrapper[SuggestionContext],
    location: str,
    text_start: int = Field(0, ge=0),
    text_limit: int = Field(4000, ge=1, le=8000),
) -> str:
    """续读需求原文或已经打开的固定 TLR 资料，不搜索和注册额外资料。
    location 复制源语段、资料读取或已保存证据返回的真实位置。
    有剩余正文时用返回的 text_next_start 续读，不能只读摘要就下结论。
    """
    context = _runtime(ctx)
    node = await resolve_location(context, location)
    workspace = await _workspace(context)
    allowed = {context.bound_source_node_id}
    allowed.update(p["design_node_id"] for p in workspace.get("passages", [])
                   if p.get("sentence_id") == context.sentence_id and p.get("candidate_id"))
    if node["node_id"] not in allowed:
        raise ValueError("简化管线只读取当前需求原文和已打开的固定 TLR 资料；不调查额外节点。请复制已返回的资料 location。")
    raw = await _get(ctx, "read_fixed_material_content",
        f"/api/v1/projects/{context.project_id}/information/nodes/{node['node_id']}",
        {"text_start": text_start, "text_limit": text_limit})
    return _dump(await address_entries(context, json.loads(raw)))
