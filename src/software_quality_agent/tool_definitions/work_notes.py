"""work_notes definitions for the SDK review workflow."""

from __future__ import annotations

from agents import RunContextWrapper
from pydantic import Field

from ..review_runtime.context import SuggestionContext
from .common import _dump, _tool_decorator


@_tool_decorator(timeout=30.0)
async def get_work_notes(
    ctx: RunContextWrapper[SuggestionContext],
    offset: int = Field(0, ge=0),
    limit: int = Field(20, ge=1, le=100),
) -> str:
    """读取当前语段已持久化工作记录，供中断后继续。"""
    context: SuggestionContext = ctx.context
    notes = list(reversed(context.store.notes()))
    call_index = context.store.tool_call("get_work_notes", {"offset": offset, "limit": limit})
    result = {
        "sentence_id": context.sentence_id,
        "notes": notes[offset : offset + limit],
        "total": len(notes),
        "has_more": offset + limit < len(notes),
        "next_offset": offset + limit if offset + limit < len(notes) else None,
    }
    context.store.tool_success(call_index, result)
    return _dump(result)


@_tool_decorator(timeout=30.0)
async def record_work_note(
    ctx: RunContextWrapper[SuggestionContext],
    step: str,
    text: str,
    references: list[str] | None = None,
) -> str:
    """即时保存简短公开工作说明及使用的真实 ID，方便后续恢复；不保存隐藏推理。"""
    context: SuggestionContext = ctx.context
    note_id = context.store.note(step, text, references or [])
    return _dump({"note_id": note_id, "sentence_id": context.sentence_id})
