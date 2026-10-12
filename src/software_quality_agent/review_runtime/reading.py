"""Count model-requested material reads at the SDK tool boundary."""

from __future__ import annotations

import hashlib
import json

from .limits import fail


MATERIAL_TOOLS = {
    "get_review_segment", "get_review_workspace_page", "get_suggestion_workspace",
    "get_saved_tool_result", "get_canonical_node", "get_node_structure", "get_node_path",
    "get_node_neighborhood", "get_node_relations", "get_table_cells",
    "get_artifact_info", "get_artifact_outline", "read_artifact_range", "search_artifact",
    "list_document_branches", "browse_document_structure", "read_document_content",
    "get_node_summary", "get_document_neighbors", "get_document_relations",
    "search_document_content", "read_table_structure", "read_fixed_material_content",
    "read_review_passage", "read_next_tlr_material", "open_supplementary_material",
    "read_external_web_page", "search_external_web",
    "get_tlr_candidates", "get_mandatory_tlr_nodes", "get_mandatory_evidence_page",
    "get_trace_links", "get_annotations",
}
VALIDATION_TOOLS = {"validate_review_assessment", "save_suggestion_validation"}
VALIDATOR = "review and suggestion validator agent"


def start_read_scope(store, agent_name, stage):
    sequence = int(store.data.get("material_read_scope_sequence", 0)) + 1
    store.data["material_read_scope_sequence"] = sequence
    store.data.setdefault("material_read_scopes", {})[agent_name] = {
        "scope": sequence, "stage": stage, "read_count": 0, "reads_without_progress": 0,
        "revision": store.data.get("facts_revision", 0), "counts": {}, "reading_closed": False,
    }
    store._save()


def read_state(context, owner=None):
    owner = owner or context.store.data.get("current_model_agent") or "review manager agent"
    return owner, context.store.data.setdefault("material_read_scopes", {}).setdefault(owner, {
        "scope": 0, "stage": owner, "read_count": 0, "reads_without_progress": 0,
        "revision": context.store.data.get("facts_revision", 0), "counts": {}, "reading_closed": False,
    })


def tool_allowed(context, name, owner=None):
    owner, state = read_state(context, owner)
    return not (owner == VALIDATOR and state["reading_closed"] and name not in VALIDATION_TOOLS)


def _identity(context, name, arguments, value):
    # Different text pages are distinct. A different tool name or page-size
    # spelling cannot hide another read of the same actual canonical range.
    if name in {"get_canonical_node", "read_document_content", "read_fixed_material_content",
                "get_node_summary", "read_review_passage", "read_next_tlr_material", "open_supplementary_material"} and isinstance(value.get("text"), str):
        target = value.get("location") or arguments.get("location") or value.get("node_id") or arguments.get("node_id")
        if target and ":/" not in str(target):
            for node_id, pointer in context.store.data.get("structural_locator_cache", {}).items():
                if node_id == target and isinstance(pointer, dict):
                    target = pointer.get("location", target)
                    break
        start = value.get("text_start", value.get("start_offset", arguments.get("text_start", arguments.get("start_offset", 0))))
        text = value["text"]
        return ["canonical_text", target, start, hashlib.sha256(text.encode()).hexdigest()]
    if name == "get_saved_tool_result":
        record = context.store.data.get("sdk_tool_results", {}).get(arguments.get("call_id"), {})
        return ["saved_material", record.get("tool"), arguments.get("field_path", []),
                value.get("offset", arguments.get("offset", 0)), value.get("value", value.get("fields"))]
    # A refreshed workspace after a genuine write is new evaluation data.
    revision = context.store.data.get("facts_revision", 0) if name in {
        "get_review_segment", "get_review_workspace_page", "get_suggestion_workspace"} else None
    return [name, arguments, revision]


def finish_material_read(context, name, arguments, raw):
    if name not in MATERIAL_TOOLS:
        return raw
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return raw
    if not isinstance(value, dict) or value.get("execution_status") in {
        "blocked", "retry_required", "current_material_pending", "priority_materials_exhausted", "ready_to_conclude"}:
        return raw
    owner, state = read_state(context)
    revision = context.store.data.get("facts_revision", 0)
    if revision != state["revision"]:
        state["reads_without_progress"] = 0
        state["revision"] = revision
    state["read_count"] += 1
    state["reads_without_progress"] += 1
    identity = json.dumps(_identity(context, name, arguments, value), ensure_ascii=False, sort_keys=True, default=str)
    key = hashlib.sha256(identity.encode()).hexdigest()
    count = state["counts"][key] = state["counts"].get(key, 0) + 1
    label = value.get("location") or arguments.get("location") or value.get("heading_path")
    if not label and name == "get_review_segment":
        label = "当前需求语段：" + str((value.get("sentence") or {}).get("text", ""))[:80]
    if not label and name == "get_saved_tool_result":
        label = "已保存资料页 " + str(arguments.get("call_id")) + " / " + "/".join(arguments.get("field_path", []))
    label = label or name
    notice = ""
    if count >= 2:
        notice = f"{owner} 正在重复读取资料 {label}，这是本次任务第 {count} 次读取同一资料页。请检查思考是否卡死，并根据已保存资料推进当前阶段。第三次读取将结束当前任务，保留已有事实并继续其他独立语段。"
        value.update(already_read=True, material_read_count=count, repeat_read_warning=notice)
    if owner == VALIDATOR and state["reads_without_progress"] > 5:
        state["reading_closed"] = True
        notice += "本次评价连续读取资料超过五次，期间没有保存新的评价事实，资料阅读现已结束。请基于已读取资料、当前提案和已保存证据直接提交验证结论，并用中文段落说明依据；信息不足时明确说明缺口。"
    if notice:
        value["material_read_notice"] = notice
        context.store.data.setdefault("material_read_events", []).append({
            "agent": owner, "scope": state["scope"], "tool": name, "material": label,
            "same_page_reads": count, "reading_closed": state["reading_closed"], "message": notice,
        })
    context.store._save()
    if count >= 3:
        fail(context.store, "repeated_material_read_limit", notice)
    return json.dumps(value, ensure_ascii=False, default=str)
