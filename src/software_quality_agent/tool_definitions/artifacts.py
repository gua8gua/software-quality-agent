"""artifacts definitions for the SDK review workflow."""

from __future__ import annotations

from typing import Literal

from agents import RunContextWrapper
from pydantic import Field

from ..review_runtime.context import SuggestionContext
from .common import _get, _tool_decorator


@_tool_decorator(timeout=30.0)
async def get_artifact_info(ctx: RunContextWrapper[SuggestionContext], artifact_id: str) -> str:
    """按真实 artifact_id 读取工件元数据、解析来源和内容可用性。"""
    context: SuggestionContext = ctx.context
    return await _get(
        ctx,
        "get_artifact_info",
        f"/api/v1/projects/{context.project_id}/information/artifacts/{artifact_id}",
    )


@_tool_decorator(timeout=30.0)
async def list_artifacts(
    ctx: RunContextWrapper[SuggestionContext],
    offset: int = Field(0, ge=0),
    limit: int = Field(30, ge=1, le=100),
) -> str:
    """分页列出本项目全部工件，先取得真实 artifact_id 再选择。"""
    context: SuggestionContext = ctx.context
    return await _get(
        ctx,
        "list_artifacts",
        f"/api/v1/projects/{context.project_id}/information/artifacts",
        {"offset": offset, "limit": limit},
    )


@_tool_decorator(timeout=30.0)
async def get_artifact_status(
    ctx: RunContextWrapper[SuggestionContext],
    artifact_id: str,
    offset: int = Field(0, ge=0),
    limit: int = Field(50, ge=1, le=100),
) -> str:
    """读取工件解析和 segmentation 状态记录。"""
    context: SuggestionContext = ctx.context
    return await _get(
        ctx,
        "get_artifact_status",
        f"/api/v1/projects/{context.project_id}/information/artifacts/{artifact_id}/status",
        {"offset": offset, "limit": limit},
    )


@_tool_decorator(timeout=30.0)
async def get_artifact_relations(
    ctx: RunContextWrapper[SuggestionContext],
    artifact_id: str,
    run_id: str | None = None,
    offset: int = Field(0, ge=0),
    limit: int = Field(50, ge=1, le=100),
) -> str:
    """读取明确的工件级关系及可选 TLR 绑定。"""
    context: SuggestionContext = ctx.context
    return await _get(
        ctx,
        "get_artifact_relations",
        f"/api/v1/projects/{context.project_id}/information/artifacts/{artifact_id}/relations",
        {"run_id": run_id, "offset": offset, "limit": limit},
    )


@_tool_decorator(timeout=30.0)
async def get_artifact_outline(
    ctx: RunContextWrapper[SuggestionContext],
    artifact_id: str,
    offset: int = Field(0, ge=0),
    limit: int = Field(50, ge=1, le=100),
    max_depth: int = Field(8, ge=0, le=20),
) -> str:
    """分页读取工件目录，返回真实 canonical node_id 与顺序。"""
    context: SuggestionContext = ctx.context
    return await _get(
        ctx,
        "get_artifact_outline",
        f"/api/v1/projects/{context.project_id}/information/artifacts/{artifact_id}/outline",
        {"offset": offset, "limit": limit, "max_depth": max_depth},
    )


@_tool_decorator(timeout=30.0)
async def read_artifact_range(
    ctx: RunContextWrapper[SuggestionContext],
    artifact_id: str,
    start_order: int = Field(0, ge=0),
    offset: int = Field(0, ge=0),
    limit: int = Field(30, ge=1, le=100),
    page_number: int | None = Field(None, ge=1),
) -> str:
    """按工件阅读顺序读取连续范围；start_order 是文档阅读序号。"""
    context: SuggestionContext = ctx.context
    return await _get(
        ctx,
        "read_artifact_range",
        f"/api/v1/projects/{context.project_id}/information/artifacts/{artifact_id}/read",
        {"start_order": start_order, "offset": offset, "limit": limit, "page_number": page_number},
    )


@_tool_decorator(timeout=30.0)
async def search_artifact(
    ctx: RunContextWrapper[SuggestionContext],
    artifact_id: str,
    query: str,
    mode: Literal["bm25", "exact", "heading"] = "bm25",
    node_type: str | None = None,
    section_id: str | None = None,
    offset: int = Field(0, ge=0),
    limit: int = Field(20, ge=1, le=100),
) -> str:
    """确定性搜索工件；BM25 只用于补充调查，不创建新的 TLR。"""
    context: SuggestionContext = ctx.context
    return await _get(
        ctx,
        "search_artifact",
        f"/api/v1/projects/{context.project_id}/information/artifacts/{artifact_id}/search",
        {
            "query": query,
            "mode": mode,
            "node_type": node_type,
            "section_id": section_id,
            "offset": offset,
            "limit": limit,
        },
    )
