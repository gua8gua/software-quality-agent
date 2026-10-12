"""Runtime-only resolution of readable document/tree addresses to canonical IDs."""

from __future__ import annotations

from typing import Any

from .context import SuggestionContext


async def document_catalog(context: SuggestionContext) -> dict[str, dict[str, Any]]:
    saved = context.store.data.setdefault("document_navigation", {})
    if saved.get("complete"):
        return saved["documents"]
    documents = saved.setdefault("documents", {})
    known = {row["artifact_id"] for row in documents.values()}
    prefix = f"/api/v1/projects/{context.project_id}/information"
    offset = 0
    while True:
        page = await context.client.get(prefix + "/artifacts", {"offset": offset, "limit": 100})
        for row in page.get("items", []):
            if row["artifact_id"] in known:
                continue
            detail = await context.client.get(prefix + f"/artifacts/{row['artifact_id']}")
            label = {"requirement": "需求文档", "design": "设计文档"}.get(row.get("engineering_role"), "工件")
            number = 1
            while f"{label}{number}" in documents:
                number += 1
            documents[f"{label}{number}"] = {
                "artifact_id": row["artifact_id"], "engineering_role": row.get("engineering_role"),
                "filename": (detail.get("file") or {}).get("filename") or detail.get("external_id"),
                "revision": detail.get("revision"),
            }
            known.add(row["artifact_id"])
        if not page.get("has_more"):
            break
        next_offset = page.get("next_offset")
        if not isinstance(next_offset, int) or next_offset <= offset:
            raise ValueError("document catalog cursor did not advance")
        offset = next_offset
    saved["complete"] = True
    context.store._save()
    return documents


async def document_alias(context: SuggestionContext, artifact_id: str) -> str:
    documents = await document_catalog(context)
    for alias, document in documents.items():
        if document["artifact_id"] == artifact_id:
            return alias
    raise ValueError("工件不在当前项目的文档目录中")


async def resolve_location(context: SuggestionContext, location: str) -> dict[str, Any]:
    """Accept only a returned human-readable address; never guess a UUID/ref."""
    document, separator, position = location.partition(":")
    catalog = await document_catalog(context)
    if not separator or document not in catalog or not position.startswith("/"):
        raise ValueError("结构位置格式应为 设计文档1:/2/4；请从 browse_document_structure 返回的 location 原样复制，不使用 UUID、Docling ref 或标题编号")
    return await context.client.get(
        f"/api/v1/projects/{context.project_id}/information/artifacts/{catalog[document]['artifact_id']}/navigation/resolve",
        {"position": position})


async def locate_node(context: SuggestionContext, node_id: str) -> dict[str, Any]:
    cache = context.store.data.setdefault("structural_locator_cache", {})
    if node_id not in cache:
        row = await context.client.get(
            f"/api/v1/projects/{context.project_id}/information/nodes/{node_id}/navigation-position")
        alias = await document_alias(context, row["artifact_id"])
        cache[node_id] = {"location": f"{alias}:{row['position']}", "document": alias,
                          "position": row["position"], "title": row.get("title"),
                          "heading_path": row.get("heading_path"), "node_type": row.get("node_type")}
        context.store._save()
    return cache[node_id]


async def address_entries(context: SuggestionContext, value: Any) -> Any:
    """Decorate API rows with tree addresses; keep IDs only in local memory."""
    if isinstance(value, list):
        return [await address_entries(context, item) for item in value]
    if not isinstance(value, dict):
        return value
    result = dict(value)
    if isinstance(value.get("node_id"), str):
        result.update(await locate_node(context, value["node_id"]))
    return {key: await address_entries(context, item) for key, item in result.items()}
