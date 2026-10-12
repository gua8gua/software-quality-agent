"""web definitions for the SDK review workflow."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
from urllib.parse import urlsplit

from agents import RunContextWrapper
from pydantic import Field

from ..review_runtime.context import SuggestionContext
from .common import _dump, _runtime, _tool_decorator


@_tool_decorator(timeout=25.0)
async def search_external_web(
    ctx: RunContextWrapper[SuggestionContext], query: str = Field(min_length=3, max_length=500)
) -> str:
    """搜索公开网络，获取可选外部背景资料；不能作为 canonical 工件证据。"""
    from ddgs import DDGS

    context = _runtime(ctx)
    call_index = context.store.tool_call("search_external_web", {"query": query})
    try:
        raw_results = await asyncio.to_thread(lambda: DDGS(timeout=10).text(query, max_results=5))
        results = []
        for row in raw_results:
            url = str(row.get("href") or "")
            parsed = urlsplit(url)
            if parsed.scheme != "https" or not parsed.hostname:
                continue
            try:
                ipaddress.ip_address(parsed.hostname)
            except ValueError:
                pass
            else:
                continue
            results.append(
                {
                    "title": str(row.get("title") or ""),
                    "url": url,
                    "snippet": str(row.get("body") or "")[:1000],
                }
            )
        hits = context.store.data.setdefault("web_search_hits", [])
        hits.extend(results)
        context.store._save()
        context.store.tool_success(call_index)
        return _dump({"source": "external_web", "results": results, "canonical_evidence": False})
    except Exception as exc:
        context.store.tool_error("search_external_web", str(exc))
        raise


@_tool_decorator(timeout=25.0)
async def read_external_web_page(
    ctx: RunContextWrapper[SuggestionContext],
    url: str,
    start: int = Field(0, ge=0),
    limit: int = Field(4000, ge=1, le=8000),
) -> str:
    """分页读取已经搜索到的公开网址；内容仅作外部背景，不作为评审证据。"""
    from ddgs import DDGS

    context = _runtime(ctx)
    known_urls = {row.get("url") for row in context.store.data.get("web_search_hits", [])}
    if url not in known_urls:
        raise ValueError("external_url_not_returned_by_search")
    cache_dir = context.store.path.parent / "web_pages"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / (hashlib.sha256(url.encode("utf-8")).hexdigest() + ".md")
    call_index = context.store.tool_call(
        "read_external_web_page", {"url": url, "start": start, "limit": limit}
    )
    try:
        if not cache_path.exists():
            extracted = await asyncio.to_thread(
                lambda: DDGS(timeout=10).extract(url, fmt="text_markdown")
            )
            if extracted.get("url") != url or not isinstance(extracted.get("content"), str):
                raise ValueError("external_page_extraction_invalid")
            cache_path.write_text(extracted["content"], encoding="utf-8")
        content = cache_path.read_text(encoding="utf-8")
        context.store.tool_success(call_index)
        return _dump(
            {
                "source": "external_web",
                "url": url,
                "content": content[start : start + limit],
                "start": start,
                "total_chars": len(content),
                "has_more": start + limit < len(content),
                "canonical_evidence": False,
            }
        )
    except Exception as exc:
        context.store.tool_error("read_external_web_page", str(exc))
        raise
