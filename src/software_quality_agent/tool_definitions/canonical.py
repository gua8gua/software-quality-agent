"""canonical definitions for the SDK review workflow."""

from __future__ import annotations

from agents import RunContextWrapper
from pydantic import Field

from ..review_runtime.context import SuggestionContext
from .common import _get, _tool_decorator


@_tool_decorator(timeout=30.0)
async def get_canonical_node(
    ctx: RunContextWrapper[SuggestionContext],
    node_id: str,
    text_start: int = Field(0, ge=0),
    text_limit: int = Field(4000, ge=1, le=8000),
    include_structure: bool = False,
    structure_start: int = Field(0, ge=0),
    structure_limit: int = Field(200, ge=1, le=8000),
    metadata_start: int = Field(0, ge=0),
    metadata_limit: int = Field(200, ge=1, le=8000),
) -> str:
    """按真实 node_id 读取 canonical 节点；text_start 是节点原文字符偏移。
    include_structure 附带持久化父子关系、附属关系和 provenance。较大 content_json/metadata 返回连续预览和 *_has_more，通过对应 start 继续读，不把预览当完整结构。有 ID 时不按标题猜节点。"""
    context: SuggestionContext = ctx.context
    return await _get(
        ctx,
        "get_canonical_node",
        f"/api/v1/projects/{context.project_id}/information/nodes/{node_id}",
        {
            "text_start": text_start,
            "text_limit": text_limit,
            "include_structure": include_structure,
            "structure_start": structure_start,
            "structure_limit": structure_limit,
            "metadata_start": metadata_start,
            "metadata_limit": metadata_limit,
        },
    )


@_tool_decorator(timeout=30.0)
async def get_node_structure(
    ctx: RunContextWrapper[SuggestionContext],
    node_id: str,
    offset: int = Field(0, ge=0),
    limit: int = Field(50, ge=1, le=100),
    max_depth: int = Field(2, ge=0, le=8),
) -> str:
    """按真实 node_id 读取 canonical 子树和父子层级。"""
    context: SuggestionContext = ctx.context
    return await _get(
        ctx,
        "get_node_structure",
        f"/api/v1/projects/{context.project_id}/information/nodes/{node_id}/subtree",
        {"offset": offset, "limit": limit, "max_depth": max_depth},
    )


@_tool_decorator(timeout=30.0)
async def get_node_path(ctx: RunContextWrapper[SuggestionContext], node_id: str) -> str:
    """按真实 node_id 读取 canonical 祖先路径，不生成重复持久化路径。"""
    context: SuggestionContext = ctx.context
    return await _get(
        ctx,
        "get_node_path",
        f"/api/v1/projects/{context.project_id}/information/nodes/{node_id}/path",
    )


@_tool_decorator(timeout=30.0)
async def get_node_neighborhood(
    ctx: RunContextWrapper[SuggestionContext],
    node_id: str,
    sibling_limit: int = Field(4, ge=0, le=20),
    child_limit: int = Field(20, ge=0, le=100),
    sibling_offset: int = Field(0, ge=0),
    child_offset: int = Field(0, ge=0),
) -> str:
    """分页读真实 canonical node_id 的直接邻近节点，不接受 Docling ref。
    children/siblings 的真实 node_id 可用于 get_canonical_node。*_total、*_has_more 区分完整列表和部分页；用 *_next_offset 继续，不扩大限制、不反复读取已结束页。limit=0 仅省略列表，不表示没有邻居。relations_has_more=true 时用 get_node_relations(node_id, offset=relations_next_offset)。"""
    context: SuggestionContext = ctx.context
    return await _get(
        ctx,
        "get_node_neighborhood",
        f"/api/v1/projects/{context.project_id}/information/nodes/{node_id}/neighborhood",
        {
            "sibling_limit": sibling_limit,
            "child_limit": child_limit,
            "sibling_offset": sibling_offset,
            "child_offset": child_offset,
        },
    )


@_tool_decorator(timeout=30.0)
async def get_node_relations(
    ctx: RunContextWrapper[SuggestionContext],
    node_id: str,
    relation_type: str | None = None,
    offset: int = Field(0, ge=0),
    limit: int = Field(50, ge=1, le=100),
) -> str:
    """读取明确的 canonical 关系；relation_type 只过滤已有关系，不推测关系。"""
    context: SuggestionContext = ctx.context
    return await _get(
        ctx,
        "get_node_relations",
        f"/api/v1/projects/{context.project_id}/information/nodes/{node_id}/relations",
        {"relation_type": relation_type, "offset": offset, "limit": limit},
    )


@_tool_decorator(timeout=30.0)
async def get_table_cells(
    ctx: RunContextWrapper[SuggestionContext],
    node_id: str,
    offset: int = Field(0, ge=0),
    limit: int = Field(50, ge=1, le=100),
) -> str:
    """读取结构化 Docling 单元格，保留行、列和相关元数据。"""
    context: SuggestionContext = ctx.context
    return await _get(
        ctx,
        "get_table_cells",
        f"/api/v1/projects/{context.project_id}/information/nodes/{node_id}/table-cells",
        {"offset": offset, "limit": limit},
    )
