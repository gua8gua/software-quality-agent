"""model_input definitions for the SDK review workflow."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from agents.models.chatcmpl_converter import Converter
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from agents.run import CallModelData, ModelInputData

from ..llm_admission import (
    ModelAdmissionBlocked,
    ModelAdmissionController,
    compact_authoritative_snapshot,
    model_input_text,
)
from ..tool_definitions.common import TOOL_OUTPUT_INLINE_CHARS, _workspace
from ..tool_definitions.saved_results import saved_result_index
from .context import SuggestionContext
from .model_view import semantic_history, semantic_snapshot

_REHYDRATED_TEXT_PAGE = 4000


_REHYDRATED_CHECK_PREVIEW = 600


_REHYDRATED_NOTE_PREVIEW = 800


def _bounded_sentence_snapshot(sentence: dict[str, Any] | None) -> dict[str, Any] | None:
    if sentence is None:
        return None
    # Overall proposals, validations and execution errors have their own
    # labelled fields below; duplicating them inside the source confuses the
    # source text with historical conclusions.
    snapshot = {key: value for key, value in sentence.items() if key != "assessment"}
    text = str(snapshot.get("text") or "")
    if len(text) > _REHYDRATED_TEXT_PAGE:
        snapshot["text"] = text[:_REHYDRATED_TEXT_PAGE]
        snapshot["text_start"] = 0
        snapshot["text_total"] = len(text)
        snapshot["text_has_more"] = True
        snapshot["text_next_start"] = _REHYDRATED_TEXT_PAGE
        snapshot["text_read_instruction"] = (
            "这里只是源原文第一页。用 get_review_segment(text_start=text_next_start) 继续，直到 text_has_more=false，再完成提取或评估。"
        )
    return snapshot


def _bounded_check_snapshot(checks: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    rows = [dict(row) for row in checks]
    compacted = False
    for row in rows:
        statement = str(row.get("statement") or "")
        quote = str(row.get("source_quote") or "")
        note = str(row.get("note") or "")
        if (
            len(statement) > _REHYDRATED_CHECK_PREVIEW
            or len(quote) > _REHYDRATED_CHECK_PREVIEW
            or len(note) > _REHYDRATED_NOTE_PREVIEW
        ):
            row["statement"] = statement[:_REHYDRATED_CHECK_PREVIEW]
            row["source_quote"] = quote[:_REHYDRATED_CHECK_PREVIEW]
            row["note"] = note[:_REHYDRATED_NOTE_PREVIEW]
            row["detail_truncated"] = True
            compacted = True
    return rows, compacted


_STATE_HISTORY_LIMIT = 8


_STATE_TEXT_LIMIT = 1200


_STATE_QUOTE_LIMIT = 4000


def _state_text(value: Any, limit: int = _STATE_TEXT_LIMIT) -> str:
    text = str(value or "")
    return text if len(text) <= limit else text[:limit] + "..."


def _state_json(value: Any, limit: int = _STATE_TEXT_LIMIT) -> str:
    return _state_text(
        json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":")), limit
    )


def _bounded_persisted_record(record: Any, text_limit: int = 1800) -> Any:
    """Keep a resumable draft/feedback record without replaying its prose bulk."""
    if not isinstance(record, dict):
        return record
    result = {}
    text_fields = {
        "problem_summary",
        "suggestion_text",
        "rationale",
        "required_revision",
        "assessment_fingerprint",
    }
    reference_fields = {"evidence", "web_sources"}
    for key, value in record.items():
        if key in text_fields:
            text = str(value or "")
            result[key] = text[:text_limit]
            if len(text) > text_limit:
                result[f"{key}_truncated"] = True
        elif key in reference_fields and isinstance(value, list):
            refs = []
            for item in value[:50]:
                if not isinstance(item, dict):
                    continue
                ref = {
                    field: item.get(field)
                    for field in (
                        "kind",
                        "identifier",
                        "node_id",
                        "check_id",
                        "candidate_id",
                        "trace_link_id",
                        "relation",
                        "url",
                    )
                    if field in item
                }
                quote = item.get("quote")
                if quote is not None:
                    quote = str(quote)
                    ref["quote"] = quote[:600]
                    if len(quote) > 600:
                        ref["quote_truncated"] = True
                refs.append(ref)
            result[key] = refs
            if len(value) > len(refs):
                result[f"{key}_truncated"] = True
        elif key == "issues" and isinstance(value, list):
            result[key] = [_state_text(item, 800) for item in value[:30]]
            if len(value) > 30:
                result["issues_truncated"] = True
        else:
            result[key] = value
    return result


def _bounded_assessment_snapshot(assessment: dict[str, Any] | None) -> dict[str, Any] | None:
    """Keep the current assessment state without replaying its full history."""
    if not isinstance(assessment, dict):
        return None
    result = {
        key: assessment.get(key)
        for key in (
            "status",
            "semantic_status",
            "finalized",
            "suggestion_required",
            "assessment_validity",
            "proposal_fingerprint",
            "proposal_current",
        )
        if key in assessment
    }
    for key in ("evaluation_text", "reason", "rationale"):
        if key in assessment:
            result[key] = _state_text(assessment.get(key), 2400)
    issues = []
    for issue in assessment.get("issues") or []:
        if not isinstance(issue, dict):
            continue
        item = {
            key: issue.get(key)
            for key in ("issue_id", "category", "title", "status", "evidence_ids")
            if key in issue
        }
        if isinstance(item.get("evidence_ids"), list):
            evidence_ids = item["evidence_ids"]
            item["evidence_ids"] = evidence_ids[:50]
            if len(evidence_ids) > 50:
                item["evidence_ids_truncated"] = True
        for key in ("statement", "explanation"):
            if key in issue:
                item[key] = _state_text(issue.get(key), 1600)
        issues.append(item)
    if issues:
        result["issues"] = issues[:50]
        result["issues_truncated"] = len(issues) > 50
    validation = assessment.get("validation")
    if isinstance(validation, dict):
        result["validation"] = {
            "accepted": validation.get("accepted"),
            "reason": _state_text(validation.get("reason"), 1600),
            "validated_at": validation.get("validated_at"),
        }
    return result


def _extract_work_state(
    runtime: SuggestionContext,
    workspace: dict[str, Any],
    sentence: dict[str, Any] | None,
    checks: list[dict[str, Any]],
    passages: list[dict[str, Any]],
) -> dict[str, Any]:
    """Extract resumable business state for a model-facing compact snapshot.

    This is deliberately deterministic.  It never summarizes with an LLM and
    never treats the transcript as the source of truth.  The backend workspace
    and checkpoint remain lossless; this envelope carries the state required
    to choose the next action after old tool messages have been trimmed.
    """
    data = runtime.store.data
    stage_states = {}
    for stage, state in (data.get("agent_states") or {}).items():
        if not isinstance(state, dict):
            continue
        stage_states[stage] = {
            key: state.get(key)
            for key in ("status", "updated_at", "error_code", "error_message", "output_recorded")
            if key in state
        }

    stage_outputs = {}
    for stage, output in (data.get("stage_outputs") or {}).items():
        if isinstance(output, dict):
            fields = sorted(str(key) for key in output.keys())
        else:
            fields = []
        encoded_output = json.dumps(
            output, ensure_ascii=False, default=str, sort_keys=True, separators=(",", ":")
        )
        stage_outputs[stage] = {
            "present": True,
            "field_names": fields[:100],
            "field_names_truncated": len(fields) > 100,
            "digest": hashlib.sha256(encoded_output.encode()).hexdigest(),
        }

    errors = [item for item in (data.get("errors") or []) if isinstance(item, dict)]
    tool_errors = [item for item in (data.get("tool_errors") or []) if isinstance(item, dict)]
    failed_calls = [
        item
        for item in (data.get("tool_calls") or [])
        if isinstance(item, dict) and item.get("succeeded") is False
    ]

    def error_view(item: dict[str, Any]) -> dict[str, Any]:
        return {
            key: (
                _state_text(item.get(key)) if key in {"message", "error_message"} else item.get(key)
            )
            for key in ("at", "name", "stage", "error_code", "error_message", "message")
            if key in item
        }

    failed_call_view = []
    for item in failed_calls[-_STATE_HISTORY_LIMIT:]:
        failed_call_view.append(
            {
                "at": item.get("at"),
                "name": item.get("name"),
                "arguments": _state_json(item.get("arguments"), 1000),
                "succeeded": False,
            }
        )

    recent_notes = []
    for item in (data.get("work_notes") or [])[-_STATE_HISTORY_LIMIT:]:
        if isinstance(item, dict):
            recent_notes.append(
                {
                    "note_id": item.get("note_id"),
                    "at": item.get("at"),
                    "step": item.get("step"),
                    "text": _state_text(item.get("text"), 1600),
                    "references": list(item.get("references") or [])[:50],
                }
            )

    check_ids = {check.get("check_id") for check in checks if isinstance(check, dict)}
    evidence_ledger = []
    for item in workspace.get("evidence", []):
        if not isinstance(item, dict) or item.get("check_id") not in check_ids:
            continue
        quote = str(item.get("exact_quote") or "")
        row = {
            key: item.get(key)
            for key in (
                "evidence_id",
                "check_id",
                "passage_id",
                "design_node_id",
                "candidate_id",
                "relation",
                "validation_status",
                "start_offset",
                "end_offset",
            )
            if key in item
        }
        row["exact_quote_length"] = len(quote)
        row["quote_sha256"] = hashlib.sha256(quote.encode()).hexdigest()
        if len(quote) <= _STATE_QUOTE_LIMIT:
            row["exact_quote"] = quote
        else:
            row["exact_quote"] = None
            row["quote_read_tool"] = "get_review_segment"
        evidence_ledger.append(row)

    passage_ledger = []
    for passage in passages:
        if not isinstance(passage, dict):
            continue
        passage_ledger.append(
            {
                key: passage.get(key)
                for key in (
                    "passage_id",
                    "design_node_id",
                    "candidate_id",
                    "start_offset",
                    "end_offset",
                    "status",
                    "error_code",
                    "error_message",
                )
                if key in passage
            }
            | {"assessment_count": len(passage.get("assessments") or [])}
        )

    investigation = None
    for record in reversed(list((data.get("sdk_tool_results") or {}).items())):
        call_id, value = record
        if not isinstance(value, dict):
            continue
        if value.get("tool") != "get_review_investigation" or not isinstance(
            value.get("output"), dict
        ):
            continue
        output = value["output"]
        investigation = {
            key: output.get(key)
            for key in (
                "checks_finalized",
                "source_anchor_status",
                "can_stop_for_sufficient_evidence",
                "conclusions_complete",
                "mandatory_remaining_node_ids",
                "unfinished_passage_ids",
                "remaining_conclusion_check_ids",
                "passage_count",
                "supplemental_passage_budget",
            )
            if key in output
        }
        investigation["source_call_id"] = call_id
        break

    attempt_history = []
    for item in (data.get("attempt_history") or [])[-_STATE_HISTORY_LIMIT:]:
        if isinstance(item, dict):
            previous = item.get("latest_output") or {}
            attempt_history.append(
                {
                    "attempt": item.get("attempt"),
                    "attempt_id": item.get("attempt_id"),
                    "workflow_status": item.get("workflow_status"),
                    "stage": item.get("stage"),
                    "current_review_phase": item.get("current_review_phase"),
                    "execution_status": previous.get("execution_status")
                    if isinstance(previous, dict)
                    else None,
                    "error_code": previous.get("error_code")
                    if isinstance(previous, dict)
                    else None,
                }
            )

    latest_draft = next(iter(reversed(data.get("suggestion_drafts") or [])), None)
    latest_feedback = next(iter(reversed(data.get("validation_feedback") or [])), None)
    draft_state = {
        "count": len(data.get("suggestion_drafts") or []),
        "latest_iteration": latest_draft.get("iteration")
        if isinstance(latest_draft, dict)
        else None,
        "latest_assessment_fingerprint": latest_draft.get("assessment_fingerprint")
        if isinstance(latest_draft, dict)
        else None,
        "latest_problem_summary": _state_text(latest_draft.get("problem_summary"), 1600)
        if isinstance(latest_draft, dict)
        else None,
        "latest_suggestion_text": _state_text(latest_draft.get("suggestion_text"), 2400)
        if isinstance(latest_draft, dict)
        else None,
        "latest_rationale": _state_text(latest_draft.get("rationale"), 1600)
        if isinstance(latest_draft, dict)
        else None,
        "latest_check_ids": list(latest_draft.get("check_ids") or [])[:50]
        if isinstance(latest_draft, dict)
        else [],
        "latest_issue_ids": list(latest_draft.get("issue_ids") or [])[:50]
        if isinstance(latest_draft, dict)
        else [],
        "latest_validation": (
            {
                "draft_iteration": latest_feedback.get("draft_iteration"),
                "valid": latest_feedback.get("valid"),
                "issues": [
                    _state_text(item, 800) for item in (latest_feedback.get("issues") or [])[:20]
                ],
                "required_revision": _state_text(latest_feedback.get("required_revision"), 1600),
            }
            if isinstance(latest_feedback, dict)
            else None
        ),
    }
    check_rows = [
        {key: check.get(key) for key in ("check_id", "status") if key in check}
        for check in checks
        if isinstance(check, dict)
    ]
    persisted_semantic_index = {
        "supported_check_ids": [
            row.get("check_id") for row in check_rows if row.get("status") == "supported"
        ],
        "contradicted_check_ids": [
            row.get("check_id") for row in check_rows if row.get("status") == "contradicted"
        ],
        "unresolved_check_ids": [
            row.get("check_id")
            for row in check_rows
            if row.get("status") in {"insufficient", "uncertain"}
        ],
        "pending_check_ids": [
            row.get("check_id") for row in check_rows if row.get("status") == "pending"
        ],
        "investigated_passage_ids": [
            row.get("passage_id") for row in passage_ledger if row.get("status") == "completed"
        ],
        "blocked_passage_ids": [
            row.get("passage_id")
            for row in passage_ledger
            if row.get("status") in {"blocked", "failed"} or row.get("error_code")
        ],
        "evidence_count": len(evidence_ledger),
        "source": "仅为已保存的检查点、资料段和证据状态，不进行新的语义推断",
    }

    return {
        "state_view_version": 1,
        "authority": "业务状态来自 checkpoint 和后台工作区；对话历史不是业务状态",
        "identity": {
            key: data.get(key) for key in ("review_id", "sentence_id", "attempts", "attempt_id")
        },
        "active_passage_id": data.get("active_passage_id"),
        "workflow_status": data.get("workflow_status"),
        "stage": data.get("stage"),
        "current_review_phase": data.get("current_review_phase"),
        "current_review_next_action": data.get("current_review_next_action"),
        "facts_revision": data.get("facts_revision", 0),
        "current_model_agent": data.get("current_model_agent"),
        "execution_binding": data.get("execution_binding"),
        "agent_states": stage_states,
        "stage_output_manifest": stage_outputs,
        "attempt_history": attempt_history,
        "latest_output": _bounded_persisted_record(data.get("latest_output")),
        "checkpoint_error": data.get("checkpoint_error"),
        "errors": {
            "total": len(errors),
            "recent": [error_view(item) for item in errors[-_STATE_HISTORY_LIMIT:]],
        },
        "tool_errors": {
            "total": len(tool_errors),
            "recent": [error_view(item) for item in tool_errors[-_STATE_HISTORY_LIMIT:]],
        },
        "failed_tool_calls": failed_call_view,
        "terminal_tool_error": data.get("terminal_tool_error"),
        "progress": {
            "last_business_progress_at": data.get("last_business_progress_at"),
            "progress_key_count": len(data.get("progress_keys") or []),
        },
        "recovery": {
            "paged_read_cursor_keys": list((data.get("paged_read_cursors") or {}).keys())[
                -_STATE_HISTORY_LIMIT:
            ],
            "saved_page_replay_count": len(data.get("saved_page_replays") or []),
            "replayed_write_count": len(data.get("replayed_writes") or []),
        },
        "work_notes": {"total": len(data.get("work_notes") or []), "recent": recent_notes},
        "investigation_checkpoint": investigation,
        "check_ledger": [
            {
                key: check.get(key)
                for key in (
                    "check_id",
                    "ordinal",
                    "category",
                    "status",
                    "source_quote",
                    "statement",
                    "note",
                )
                if key in check
            }
            for check in checks
        ],
        "passage_ledger": passage_ledger,
        "evidence_ledger": evidence_ledger,
        "persisted_semantic_index": persisted_semantic_index,
        "overall_assessment": _bounded_assessment_snapshot((sentence or {}).get("assessment")),
        "suggestion_state": draft_state,
        "model_health": {
            key: data.get(key)
            for key in ("llm_state", "model_failure_streak", "model_preflight_failure_streak")
        },
        "execution_metrics": {
            "model_call_count": len(data.get("model_calls") or []),
            "tool_call_count": len(data.get("tool_calls") or []),
            "latest_admission": (data.get("llm_admission") or [])[-1]
            if data.get("llm_admission")
            else None,
        },
    }


def _recent_tool_history(history: list[Any], blocks: int = 2) -> list[Any]:
    """Keep the latest complete tool-call blocks after deterministic compaction."""
    boundaries: list[int] = []
    cursor = len(history)
    for _ in range(blocks):
        output_index = cursor - 1
        while output_index >= 0:
            item = history[output_index]
            if isinstance(item, dict) and item.get("type") == "function_call_output":
                break
            output_index -= 1
        if output_index < 0:
            break
        start = output_index
        while start > 0:
            previous = history[start - 1]
            if not (
                isinstance(previous, dict)
                and previous.get("type") in {"function_call", "function_call_output"}
            ):
                break
            start -= 1
        if start > 0:
            previous = history[start - 1]
            if isinstance(previous, dict) and previous.get("role") == "assistant":
                start -= 1
        boundaries.append(start)
        cursor = start
    if not boundaries:
        return history[-4:]
    return history[min(boundaries) :]


def _unopened_mandatory_reference(runtime: SuggestionContext, workspace: dict) -> dict | None:
    """Retain one real fetched target pointer when old tool messages are trimmed.

    This is a reference, not evidence, a new ranking, or an automatic tool call.
    Opened ranges remain governed by backend investigation coverage and errors.
    """
    opened = {
        p.get("design_node_id")
        for p in workspace.get("passages", [])
        if p.get("sentence_id") == runtime.sentence_id
    }
    opened.update(v.get("design_node_id") for v in workspace.get("visits", []))
    for call_id, record in reversed(list(runtime.store.data.get("sdk_tool_results", {}).items())):
        output = record.get("output")
        if (
            record.get("tool") != "get_mandatory_tlr_nodes"
            or not isinstance(output, dict)
            or output.get("run_id") != runtime.bound_run_id
            or output.get("source_node_id") != runtime.bound_source_node_id
        ):
            continue
        for index, item in enumerate(output.get("items", [])):
            if isinstance(item, dict) and item.get("node_id") and item["node_id"] not in opened:
                return {
                    "target_node_id": item["node_id"],
                    "candidate_id": item.get("candidate_id"),
                    "retrieved_from": {"call_id": call_id, "field_path": ["items", str(index)]},
                    "use": "待查看的 SDS 候选，不表示证据已接受或要求已满足",
                }
    return None


def _returned_read_index(records: dict[str, Any]) -> list[dict[str, Any]]:
    """Carry factual read addresses across compaction, not an LLM summary.

    Identical calls share one latest address. Original responses remain in the
    checkpoint; a returned result is NOT an accepted evidence/semantic judgment.
    """
    indexed = {}
    for call_id, record in records.items():
        name = record.get("tool", "")
        if not name.startswith(("get_", "read_", "search_")):
            continue
        arguments = record.get("arguments")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except ValueError:
                continue
        if not isinstance(arguments, dict):
            continue
        key = json.dumps([name, arguments], ensure_ascii=False, sort_keys=True)
        entry = {
            "tool": name,
            "arguments": arguments,
            "result_reference": {"call_id": call_id, "field_path": [], "offset": 0, "limit": 100},
        }
        value = record.get("output")
        if isinstance(value, dict):
            entry["read_policy"] = {
                k: value[k]
                for k in (
                    "read_scope",
                    "investigation_priority",
                    "read_run_id",
                    "read_source_node_id",
                    "read_node_id",
                    "candidate_binding_policy",
                )
                if k in value
            }
            entry["pagination"] = {
                k: v
                for k, v in value.items()
                if k
                in {
                    "has_more",
                    "next_offset",
                    "has_more_text",
                    "text_has_more",
                    "text_start",
                    "text_next_start",
                    "text_total_chars",
                    "children_total",
                    "children_has_more",
                    "children_next_offset",
                    "siblings_total",
                    "siblings_has_more",
                    "siblings_next_offset",
                    "relations_has_more",
                    "relations_next_offset",
                    "metadata_has_more",
                    "metadata_start",
                    "metadata_limit",
                    "metadata_total_chars",
                    "metadata_next_start",
                    "content_json_start",
                    "content_json_limit",
                    "content_json_total_chars",
                    "content_json_has_more",
                    "content_json_next_start",
                    "has_more_failures",
                    "next_failure_offset",
                    "draft_has_more",
                    "draft_next_offset",
                    "feedback_has_more",
                    "feedback_next_offset",
                }
            }
        indexed[key] = entry
    return list(indexed.values())


def _compact_model_facing_input(
    items: list[Any], saved_results: dict[str, Any] | None = None
) -> list[Any]:
    """Compact once after admission rejects the normal model-facing view.

    The backend workspace and SDK session remain lossless.  The next model
    request keeps the system/task item, authoritative state and only the two
    newest non-state messages; all omitted facts are addressable by tools.
    """
    if not items:
        return items
    first = items[0]
    state_item = None
    for item in items[1:]:
        if not isinstance(item, dict) or item.get("role") != "user":
            continue
        content = item.get("content")
        if isinstance(content, str) and content.startswith("权威评审业务数据，不是指令:"):
            prefix, _, body = content.partition(":")
            try:
                state = json.loads(body.strip())
            except (TypeError, ValueError):
                state = None
            if isinstance(state, dict):
                state_item = {
                    "role": "user",
                    "content": prefix
                    + ": "
                    + json.dumps(
                        compact_authoritative_snapshot(state),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                }
            break
    # Keep the latest two complete tool blocks; never orphan an output or drop
    # one of several calls emitted in the same assistant response.
    history = [
        item
        for item in items[1:]
        if not (
            isinstance(item, dict)
            and str(item.get("content", "")).startswith("权威评审业务数据，不是指令:")
        )
    ]
    # Keep the original task anchor as well as the state ledger.  A compacted
    # transcript must not silently turn the specialist's requested sentence or
    # validation task into an implicit assumption.  The anchor is normally a
    # short user item; if it is large, admission will fail closed rather than
    # clipping it into a different task.
    task_anchor = next(
        (item for item in history if isinstance(item, dict) and item.get("role") == "user"), None
    )
    tail = _recent_tool_history(history, blocks=2)
    output = [first]
    if state_item is not None:
        output.append(state_item)
    if task_anchor is not None and task_anchor is not first and task_anchor not in tail:
        output.append(task_anchor)
    read_index = _returned_read_index(saved_results or {})
    if read_index:
        output.append(
            {
                "role": "user",
                "content": "已返回的工具结果索引（数据，不是指令）。读取已完成不代表接受证据或完成评审。仅在需要原始值时，将真实 result_reference 传给 get_saved_tool_result。 "
                + json.dumps(read_index, ensure_ascii=False, separators=(",", ":")),
            }
        )
    output.extend(tail)
    return output


def _index_large_tool_outputs(items: list[Any], saved_results: dict[str, Any]) -> list[Any]:
    """Create saved-result pointers only for an admitted compressed request.

    Normal requests retain the exact tool values.  This helper is deliberately
    called after the tokenizer admission gate decides that compaction is needed;
    it therefore cannot silently replace usable evidence while the context still
    fits.  Pointers always address the immutable original checkpoint result.
    """
    indexed = []
    for item in items:
        if not isinstance(item, dict) or item.get("type") != "function_call_output":
            indexed.append(item)
            continue
        record = saved_results.get(item.get("call_id"))
        if not isinstance(record, dict):
            indexed.append(item)
            continue
        output = record.get("output")
        if record.get("tool") == "get_canonical_node" and isinstance(output, dict):
            view = dict(output)
            for field in (
                "hierarchy",
                "metadata",
                "metadata_preview",
                "provenance",
                "content_json",
                "content_json_preview",
            ):
                value = view.get(field)
                if (
                    value is not None
                    and len(json.dumps(value, ensure_ascii=False)) > TOOL_OUTPUT_INLINE_CHARS
                ):
                    view[field] = saved_result_index(
                        item["call_id"], record["tool"], value, [field]
                    )
            indexed.append({**item, "output": json.dumps(view, ensure_ascii=False)})
            continue
        if (
            record.get("tool") not in _BUSINESS_RESULT_TOOLS
            and not (isinstance(output, dict) and output.get("source") == "saved_sdk_tool_output")
            and len(json.dumps(output, ensure_ascii=False)) > TOOL_OUTPUT_INLINE_CHARS
        ):
            indexed.append(
                {
                    **item,
                    "output": json.dumps(
                        saved_result_index(item["call_id"], record["tool"], output),
                        ensure_ascii=False,
                    ),
                }
            )
            continue
        indexed.append(item)
    return indexed


def _passage_turn_budget(runtime: SuggestionContext, agent_name: str) -> dict[str, Any]:
    """Return the model-visible budget for one supplemental investigation."""
    limit = runtime.passage_max_turns if agent_name == "evidence investigator agent" else None
    if limit is None:
        return {
            "scope": "segment_orchestration",
            "turn_limit": None,
            "turns_used": None,
            "turns_remaining": None,
            "note": "整个源语段生命周期不设轮数上限。",
        }
    stage = "evidence"
    base = int(runtime.store.data.get("agent_turn_bases", {}).get(stage, 0) or 0)
    used = max(0, len(runtime.store.data.get("model_calls", [])) - base)
    return {
        "scope": "one_supplemental_passage_investigation",
        "turn_limit": limit,
        "turns_used": used,
        "turns_remaining": max(0, limit - used),
        "note": "仅用于额外资料调查；turns_remaining 用尽时，完成本资料注册或保留 blocked，返回 Review Analysis。",
    }


async def _admit_model_input(data: CallModelData[Any], bounded: ModelInputData) -> ModelInputData:
    """Run the host admission gate immediately before an SDK model request."""
    runtime = data.context
    if not isinstance(runtime, SuggestionContext):
        return bounded
    if not isinstance(data.agent.model, OpenAIChatCompletionsModel):
        return bounded  # deterministic SDK test model: no provider request
    controller = ModelAdmissionController(
        store=runtime.store,
        base_url=runtime.model_base_url,
        api_key=runtime.model_api_key,
        model=runtime.model_name or "qwen35-9b",
        context_window=runtime.model_context_window,
        safety_tokens=runtime.model_safety_tokens,
        health_timeout_seconds=runtime.model_health_timeout_seconds,
        failure_limit=runtime.model_failure_limit,
    )
    reserve = data.agent.model_settings.max_tokens

    # None is the SDK's provider-default output policy, not a missing required
    # budget. Admission still checks tokenizer health, input capacity and the
    # configured safety headroom; it must not reintroduce a generation cap.
    def request_payload(view):
        messages = Converter.items_to_messages(
            view.input, model=runtime.model_name, base_url=runtime.model_base_url
        )
        if view.instructions:
            messages.insert(0, {"role": "system", "content": view.instructions})
        return {
            "messages": messages,
            "tools": [Converter.tool_to_openai(t) for t in data.agent.tools],
            **(data.agent.model_settings.extra_body or {}),
        }

    decision = await controller.check(
        payload=request_payload(bounded),
        output_reserve=reserve,
        compressed=False,
        agent=data.agent.name,
    )
    if decision.action != "compress":
        return bounded
    indexed = _index_large_tool_outputs(
        list(bounded.input), runtime.store.data.get("sdk_tool_results", {})
    )
    compacted = ModelInputData(
        input=_compact_model_facing_input(indexed, runtime.store.data.get("sdk_tool_results", {})),
        instructions=bounded.instructions,
    )
    compacted = await semantic_history(runtime, compacted, data.agent.name)
    second = await controller.check(
        payload=request_payload(compacted),
        output_reserve=reserve,
        compressed=True,
        agent=data.agent.name,
    )
    if second.action != "allow":
        # ``check`` raises for an oversized compressed view.  This guard keeps
        # the invariant explicit if the controller is changed later.
        raise ModelAdmissionBlocked(
            "context_budget_admission_blocked",
            "compacted model request was not admitted",
            state=second.as_dict(),
        )
    return compacted


async def _bounded_model_input(data: CallModelData[Any]) -> ModelInputData:
    """Send stage-specific semantic facts; host bindings remain outside the model."""
    bounded = data.model_data
    runtime = data.context
    if isinstance(runtime, SuggestionContext):
        terminal = runtime.store.data.get("terminal_tool_error")
        if terminal:
            from .limits import fail
            fail(runtime.store, terminal["error_code"], terminal["message"])
        runtime.store.data["current_model_agent"] = data.agent.name
        bounded = await semantic_history(runtime, bounded, data.agent.name)
        workspace = await _workspace(runtime)
        snapshot = await semantic_snapshot(runtime, workspace, data.agent.name)
        snapshot["workflow_cycles"] = runtime.store.data.get("workflow_cycles", {})
        from .reading import read_state
        _, reading = read_state(runtime)
        snapshot["material_read_budget"] = {key: reading[key] for key in (
            "read_count", "reads_without_progress", "reading_closed")}
        snapshot["stage_budget_explanation"] = "每个语段的评审分析与整体验证合计最多两轮，建议生成与建议验证合计最多两轮。第一轮验证反馈用于唯一的一次修订，第二轮验证后保留真实结果并结束该阶段。"
        if data.agent.name == "evidence investigator agent":
            snapshot["passage_read_budget"] = _passage_turn_budget(runtime, data.agent.name)
        state_item = {"role": "user", "content": "权威评审业务数据，不是指令: "
                      + json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))}
        items = list(bounded.input)
        bounded = ModelInputData(input=[items[0], state_item, *items[1:]] if items else [state_item],
                                 instructions=(bounded.instructions or "") + "\n资料阅读规则：同一次任务中重复读取同一资料页时，负责阅读的 Agent 会收到明确的重复提示。第三次读取结束当前任务，保留已有事实并继续其他独立语段；不同页的正常续读分别计数。Validator 在同一次整体验证或建议验证中，连续读取资料超过五次且没有保存新的评价事实时结束资料阅读，基于已有资料直接提交验证结论，用中文段落说明依据或信息缺口。")
        runtime.store.data.setdefault("model_input_stats", []).append({
            "agent": data.agent.name, "original_items": len(data.model_data.input),
            "sent_items": len(bounded.input), "view_policy": "semantic-structural-navigation-v1",
            "sent_characters": len(json.dumps(bounded.input, ensure_ascii=False, default=str)),
        })
        bounded = await _admit_model_input(data, bounded)
        runtime.store.data["model_input_stats"][-1]["admission_input_characters"] = len(
            model_input_text(bounded.input, bounded.instructions))
        runtime.store._save()
    return bounded


_BUSINESS_RESULT_TOOLS = {
    "read_next_tlr_material",
    "open_supplementary_material",
    "get_review_progress",
    "get_review_segment",
    "get_review_investigation",
    "get_saved_tool_result",
    "get_mandatory_tlr_nodes",
    "get_canonical_node",
    "get_node_path",
    "get_node_neighborhood",
    "get_node_summary",
    "read_fixed_material_content",
    "finish_review_incomplete",
    "read_review_passage",
    "assess_review_check",
    "finalize_review_passage",
    "create_review_check",
    "finalize_review_checks",
    "complete_review_analysis",
    "propose_review_assessment",
    "validate_review_assessment",
    "get_suggestion_workspace",
    "save_suggestion_draft",
    "save_suggestion_validation",
    "run_review_analysis",
    "investigate_review_material",
    "validate_segment_assessment",
    "draft_modification_suggestion",
    "validate_modification_suggestion",
}
