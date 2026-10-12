"""Semantic, tree-position information tools; canonical UUIDs stay in context."""

from __future__ import annotations

import json
from typing import Literal

from agents import RunContextWrapper
from pydantic import Field

from ..review_runtime.context import SuggestionContext
from ..review_runtime.navigation import address_entries, document_catalog, resolve_location
from .common import _dump, _get, _runtime, _tool_decorator


@_tool_decorator(timeout=30.0)
async def list_document_branches(ctx: RunContextWrapper[SuggestionContext],
                                 offset: int = Field(0, ge=0), limit: int = Field(20, ge=1, le=100)) -> str:
    """需要选择其他文档时才读此目录。返回文档别名、文件名和根结构位置，不返回工件 UUID。"""
    context = _runtime(ctx)
    catalog = await document_catalog(context)
    documents = list(catalog.items())
    return _dump({"documents": [{"document": alias, "filename": row.get("filename"),
                                  "role": row.get("engineering_role"), "location": alias + ":/"}
                                 for alias, row in documents[offset:offset + limit]],
                  "has_more": offset + limit < len(documents),
                  "next_offset": offset + limit if offset + limit < len(documents) else None})


@_tool_decorator(timeout=30.0)
async def browse_document_structure(ctx: RunContextWrapper[SuggestionContext], location: str,
                                     offset: int = Field(0, ge=0), limit: int = Field(30, ge=1, le=100)) -> str:
    """按结构位置查看当前标题、直接子节点及下方所有章节标题（分页）。
    location 从当前需求位置、已查资料位置或 list_document_branches 复制，例如 设计文档1:/。
    先看语义标题再选择下级 location；/2/4 是真实树路径，不等于标题中的 3.2.4。
    has_more=true 时用 next_offset 读完剩余标题，不猜不存在的章节。"""
    context = _runtime(ctx)
    node = await resolve_location(context, location)
    result = await _get(ctx, "browse_document_structure",
        f"/api/v1/projects/{context.project_id}/information/artifacts/{node['artifact_id']}/navigation",
        {"position": node["position"], "offset": offset, "limit": limit})
    return _dump(await address_entries(context, json.loads(result)))


@_tool_decorator(timeout=30.0)
async def read_document_content(ctx: RunContextWrapper[SuggestionContext], location: str,
                                text_start: int = Field(0, ge=0), text_limit: int = Field(4000, ge=1, le=8000)) -> str:
    """按结构位置只读 canonical 原文；不注册调查资料，不产生证据。
    location 复制目录返回的值；text_has_more/has_more_text 为 true 时按 text_next_start 续读。
    section 只有标题，没有复制的整章正文；整章内容通过目录的子节点分别读取。"""
    context = _runtime(ctx)
    node = await resolve_location(context, location)
    raw = await _get(ctx, "read_document_content",
        f"/api/v1/projects/{context.project_id}/information/nodes/{node['node_id']}",
        {"text_start": text_start, "text_limit": text_limit})
    return _dump(await address_entries(context, json.loads(raw)))


@_tool_decorator(timeout=30.0)
async def get_node_summary(ctx: RunContextWrapper[SuggestionContext], location: str,
                           text_limit: int = Field(800, ge=100, le=2000)) -> str:
    """读取一个结构位置的轻量节点摘要，供选择额外资料，不注册证据。"""
    context = _runtime(ctx)
    node = await resolve_location(context, location)
    raw = await _get(
        ctx,
        "get_node_summary",
        f"/api/v1/projects/{context.project_id}/information/nodes/{node['node_id']}",
        {"text_start": 0, "text_limit": text_limit},
    )
    value = await address_entries(context, json.loads(raw))
    return _dump(
        {
            "location": location,
            "title": node.get("title"),
            "heading_path": node.get("heading_path"),
            "node_type": node.get("node_type"),
            "text": value.get("text", ""),
            "text_total_chars": value.get("text_total_chars"),
            "has_more_text": value.get("has_more_text", False),
            "text_next_start": value.get("text_next_start"),
            "already_read": value.get("already_read", False),
            "repeat_read_count": value.get("repeat_read_count", 0),
            "repeat_read_warning": value.get("repeat_read_warning"),
            "read_scope": "supplemental_candidate_summary",
            "canonical_evidence": False,
            "instruction": "这是额外资料候选摘要；确认 location 后交给 investigate_review_material，不把摘要本身当作证据。",
        }
    )


@_tool_decorator(timeout=30.0)
async def get_document_neighbors(ctx: RunContextWrapper[SuggestionContext], location: str,
                                  sibling_offset: int = Field(0, ge=0), child_offset: int = Field(0, ge=0)) -> str:
    """按结构位置读取父节点、相邻段落和子节点，保留标题/原文帮助解释条件和指代。
    返回的各 location 可继续读取；siblings_has_more、children_has_more 使用各自游标。"""
    context = _runtime(ctx)
    node = await resolve_location(context, location)
    raw = await _get(ctx, "get_document_neighbors",
        f"/api/v1/projects/{context.project_id}/information/nodes/{node['node_id']}/neighborhood",
        {"sibling_offset": sibling_offset, "child_offset": child_offset, "sibling_limit": 4, "child_limit": 20})
    return _dump(await address_entries(context, json.loads(raw)))


@_tool_decorator(timeout=30.0)
async def get_document_relations(ctx: RunContextWrapper[SuggestionContext], location: str,
                                  offset: int = Field(0, ge=0), limit: int = Field(20, ge=1, le=100)) -> str:
    """按结构位置查看明确的 caption、attached 或 cross-reference 关系，不推断新关系。"""
    context = _runtime(ctx)
    node = await resolve_location(context, location)
    return await _get(ctx, "get_document_relations",
        f"/api/v1/projects/{context.project_id}/information/nodes/{node['node_id']}/relations",
        {"offset": offset, "limit": limit})


@_tool_decorator(timeout=30.0)
async def search_document_content(ctx: RunContextWrapper[SuggestionContext], location: str, query: str,
                                   mode: Literal["bm25", "exact", "heading"] = "bm25",
                                   offset: int = Field(0, ge=0), limit: int = Field(10, ge=1, le=100)) -> str:
    """完成高优先资料后，可在自行选定的结构分支内补充调查。
    先通过目录选择 location，query 用完整需求的语义词句；BM25 是调查工具，不重新执行 TLR。
    返回语义预览和可打开的 location；不能只凭检索分数判断满足度。"""
    context = _runtime(ctx)
    node = await resolve_location(context, location)
    raw = await _get(ctx, "search_document_content",
        f"/api/v1/projects/{context.project_id}/information/artifacts/{node['artifact_id']}/search",
        {"query": query, "mode": mode, "section_id": node["node_id"], "offset": offset, "limit": limit})
    return _dump(await address_entries(context, json.loads(raw)))


STRUCTURE_QUERY_TOOLS = [list_document_branches, browse_document_structure,
                         read_document_content, get_node_summary, get_document_neighbors,
                         get_document_relations, search_document_content]
