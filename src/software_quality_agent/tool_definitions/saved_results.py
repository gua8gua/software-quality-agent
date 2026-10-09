"""saved_results definitions for the SDK review workflow."""

from __future__ import annotations

from typing import Any

from agents import RunContextWrapper
from pydantic import Field

from ..review_runtime.context import SuggestionContext
from .common import (
    TOOL_OUTPUT_INLINE_CHARS,
    SavedResultAddressError,
    _dump,
    _runtime,
    _tool_decorator,
)


def saved_result_index(
    call_id: str, name: str, result: Any, field_path: list[str] | None = None
) -> dict:
    """Expose values and fully-qualified read arguments, never a schema-only maze.

    Long fields remain in the immutable checkpoint. Small scalar facts (IDs,
    statuses, cursors) are usable immediately; every omitted value has an exact
    read address relative to the ORIGINAL call, including nested objects.
    """
    base = field_path or []
    if isinstance(result, dict):
        fields = {}
        for key, value in result.items():
            if (not isinstance(value, (dict, list)) or not value) and len(
                _dump(value)
            ) <= TOOL_OUTPUT_INLINE_CHARS:
                fields[key] = {"value": value}
            else:
                fields[key] = {
                    "type": type(value).__name__,
                    "length": len(value),
                    "read": {
                        "call_id": call_id,
                        "field_path": [*base, key],
                        "offset": 0,
                        "limit": 100,
                    },
                }
    else:
        fields = {
            "$": {
                "type": type(result).__name__,
                "length": len(result) if isinstance(result, (str, list)) else None,
                "read": {"call_id": call_id, "field_path": base, "offset": 0, "limit": 100},
            }
        }
    identity = (
        {
            key: value
            for key, value in result.items()
            if key.endswith("_id") and isinstance(value, str)
        }
        if isinstance(result, dict)
        else {}
    )
    return {
        "source": "saved_sdk_tool_output",
        "call_id": call_id,
        "tool": name,
        "identity": identity,
        "field_path": base,
        "fields": fields,
        "instruction": "标量值可直接使用。要读省略字段，将索引中的准确 read 参数传给 get_saved_tool_result。路径相对原始调用，不是当前索引。",
    }


@_tool_decorator(timeout=30.0)
async def get_saved_tool_result(
    ctx: RunContextWrapper[SuggestionContext],
    call_id: str,
    field_path: list[str] = Field(default_factory=list),
    offset: int = Field(0, ge=0),
    limit: int = Field(100, ge=1, le=1000),
) -> str:
    """按工具返回的真实 call_id，读取本次执行保存的公开 SDK 工具结果。
    field_path=[] 表示根，['items'] 表示列表，['items','0','title'] 表示第一项标题。索引提供真实字段、类型、长度，字符串或列表分页保留原始值。仅 has_more=true 时使用 next_offset；到末尾（含空值）next_offset=null，不猜测或递增末尾游标。对象返回字段索引，合法重复读取返回相同值。不得猜测 call_id 或使用其他语段/执行尝试的结果。"""
    context = _runtime(ctx)
    from ..review_runtime.model_view import _LOCAL_FIELDS, _NODE_FIELDS

    if any(key in _LOCAL_FIELDS or key in _NODE_FIELDS
           or key.endswith("_node_ids") or key.endswith("_artifact_ids") for key in field_path):
        raise SavedResultAddressError("此字段是程序内部身份/成员列表，不是语义资料。按已返回的 location 使用结构查询工具；不要读取原始 UUID 列表")
    # Reads are idempotent: never silently advance an explicitly requested
    # offset or turn a legitimate reread into an execution failure. The SDK's
    # Runner turn bound still prevents unbounded model/tool loops.
    effective_offset = int(offset)
    record = context.store.data.get("sdk_tool_results", {}).get(call_id)
    if record is None:
        raise SavedResultAddressError("saved_tool_result_not_in_current_attempt")
    value = record["output"]
    for key in field_path:
        if isinstance(value, list):
            if not key.isdecimal() or not 0 <= int(key) < len(value):
                raise SavedResultAddressError("field_path_array_index_outside_result")
            value = value[int(key)]
        elif isinstance(value, dict):
            if key not in value:
                raise SavedResultAddressError("field_path_key_not_in_result")
            value = value[key]
        else:
            raise SavedResultAddressError("field_path_does_not_address_structured_result")
    # Validate the address, not a heuristic count of repeated model requests.
    # Empty values have exactly one valid read (offset=0). EOF never creates a
    # fresh empty page at an arbitrary offset. Scalars/objects are not paged.
    if (isinstance(value, (list, str)) and effective_offset >= max(1, len(value))) or (
        not isinstance(value, (list, str)) and effective_offset != 0
    ):
        raise SavedResultAddressError(
            f"saved_result_offset_out_of_range:offset={effective_offset};"
            f"total={len(value) if isinstance(value, (list, str)) else 1}"
        )
    replayed = context.store.guard_saved_page(call_id, field_path, offset, limit)
    if isinstance(value, (list, str)):
        size = min(limit, max(len(value) - effective_offset, 0))
        while True:
            page = {
                "call_id": call_id,
                "field_path": field_path,
                "offset": effective_offset,
                "value": value[effective_offset : effective_offset + size],
                "total": len(value),
                "has_more": effective_offset + size < len(value),
                "next_offset": effective_offset + size
                if effective_offset + size < len(value)
                else None,
            }
            if replayed:
                page["already_read"] = True
                page["requested_offset"] = offset
                page["instruction"] = "该不可变页已经读取，使用已保存值并继续下一分析动作。"
            if len(_dump(page)) <= TOOL_OUTPUT_INLINE_CHARS or size <= 1:
                break
            size = max(size // 2, 1)
        if len(_dump(page)) > TOOL_OUTPUT_INLINE_CHARS and isinstance(value, list) and size == 1:
            # One large object is addressed in the ORIGINAL stored result, not
            # by recursively wrapping a page of that very same object.
            page = {
                **saved_result_index(
                    call_id,
                    record["tool"],
                    value[effective_offset],
                    [*field_path, str(effective_offset)],
                ),
                "total": len(value),
                "has_more": effective_offset + 1 < len(value),
                "next_offset": effective_offset + 1 if effective_offset + 1 < len(value) else None,
            }
            if replayed:
                page["already_read"] = True
                page["requested_offset"] = offset
                page["instruction"] = "该不可变项已经读取，使用已保存值并继续下一分析动作。"
            return _dump(page)
        return _dump(page)
    if isinstance(value, dict):
        page = {"call_id": call_id, "field_path": field_path, "value": value}
        if replayed:
            page["already_read"] = True
            page["instruction"] = "该不可变对象已经读取，使用已保存值并继续下一分析动作。"
        if len(_dump(page)) <= TOOL_OUTPUT_INLINE_CHARS:
            return _dump(page)
        indexed = saved_result_index(call_id, record["tool"], value, field_path)
        if replayed:
            indexed["already_read"] = True
            indexed["instruction"] = "该不可变对象已经读取，使用其真实字段并继续下一分析动作。"
        return _dump(indexed)
    result = {"call_id": call_id, "field_path": field_path, "value": value}
    if replayed:
        result["already_read"] = True
        result["instruction"] = "该不可变值已经读取，使用它并继续下一分析动作。"
    return _dump(result)
