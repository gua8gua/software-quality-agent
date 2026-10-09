"""suggestions definitions for the SDK review workflow."""

from __future__ import annotations

from agents import RunContextWrapper
from pydantic import Field

from ..review_runtime.context import SuggestionContext
from ..review_runtime.contracts import EvidenceReference, SuggestionDraft, SuggestionValidation, SuggestionEvidenceInput
from ..review_runtime.navigation import resolve_location
from .common import _dump, _runtime, _tool_decorator, _workspace
from .reference_validation import _validate_references


@_tool_decorator(timeout=30.0)
async def get_suggestion_workspace(
    ctx: RunContextWrapper[SuggestionContext],
    draft_offset: int = Field(0, ge=0),
    feedback_offset: int = Field(0, ge=0),
    limit: int = Field(5, ge=1, le=20),
) -> str:
    """读取已保存建议草稿和验证反馈，分别分页。
    draft_next_offset、feedback_next_offset 是独立游标，不混用。草稿和反馈不能自行成为语义真源，须核对对应持久化验证状态。"""
    context = _runtime(ctx)
    data = context.store.data
    call_index = context.store.tool_call(
        "get_suggestion_workspace",
        {"draft_offset": draft_offset, "feedback_offset": feedback_offset, "limit": limit},
    )
    drafts = list(reversed(data.get("suggestion_drafts", [])))
    feedback = list(reversed(data.get("validation_feedback", [])))
    result = {
        "review_id": context.review_id,
        "sentence_id": context.sentence_id,
        "suggestion_drafts": drafts[draft_offset : draft_offset + limit],
        "draft_total": len(drafts),
        "draft_has_more": draft_offset + limit < len(drafts),
        "draft_next_offset": draft_offset + limit if draft_offset + limit < len(drafts) else None,
        "validation_feedback": feedback[feedback_offset : feedback_offset + limit],
        "feedback_total": len(feedback),
        "feedback_has_more": feedback_offset + limit < len(feedback),
        "feedback_next_offset": feedback_offset + limit
        if feedback_offset + limit < len(feedback)
        else None,
    }
    context.store.tool_success(call_index, result)
    return _dump(result)


@_tool_decorator(timeout=30.0)
async def save_suggestion_draft(
    ctx: RunContextWrapper[SuggestionContext],
    problem_summary: str,
    suggestion_text: str,
    rationale: str,
    check_ids: list[str],
    evidence: list[SuggestionEvidenceInput] | None = None,
    unresolved_questions: list[str] | None = None,
    issue_ids: list[str] | None = None,
) -> str:
    """确定性 ID/逐字引用校验通过后，保存本次修订草稿。"""
    context = _runtime(ctx)
    workspace = await _workspace(context)
    assessment = (
        next(
            (
                s.get("assessment")
                for s in workspace.get("sentences", [])
                if s.get("sentence_id") == context.sentence_id
            ),
            None,
        )
        or {}
    )
    if not assessment.get("finalized") or not assessment.get("suggestion_required"):
        raise ValueError("suggestion_requires_validated_business_problem")
    resolved_evidence = []
    for ref in evidence or []:
        payload = ref.model_dump()
        if ref.kind == "canonical_node":
            node = await resolve_location(context, ref.identifier)
            payload.update(identifier=node["node_id"], node_id=node["node_id"], artifact_id=node["artifact_id"])
        resolved_evidence.append(EvidenceReference(**payload))
    draft = SuggestionDraft(
        review_id=context.review_id,
        sentence_id=context.sentence_id,
        segment_id="sentence",
        problem_summary=problem_summary,
        assessment_fingerprint=assessment.get("proposal_fingerprint") or "",
        suggestion_text=suggestion_text,
        rationale=rationale,
        check_ids=check_ids,
        issue_ids=issue_ids or [],
        evidence=resolved_evidence,
        unresolved_questions=unresolved_questions or [],
    )
    errors = await _validate_references(context, draft)
    if errors:
        context.store.tool_error("save_suggestion_draft", ";".join(errors))
        raise ValueError("invalid suggestion draft: " + ";".join(errors))
    call_arguments = {
        "problem_summary": problem_summary,
        "suggestion_text": suggestion_text,
        "rationale": rationale,
        "unresolved_questions": unresolved_questions or [],
        "check_ids": check_ids,
        "issue_ids": issue_ids or [],
        "evidence": [ref.model_dump(mode="json") for ref in draft.evidence],
        "assessment_fingerprint": draft.assessment_fingerprint,
    }
    if not context.store.guard_replayed_write("save_suggestion_draft", call_arguments):
        cached = context.store.replayed_write_output("save_suggestion_draft", call_arguments)
        if cached is not None:
            return _dump(cached)
        raise RuntimeError("terminal_tool_guard:replayed_state_change")
    drafts = [
        d
        for d in context.store.data.get("suggestion_drafts", [])
        if d.get("assessment_fingerprint") == draft.assessment_fingerprint
    ]
    if len(drafts) >= context.max_suggestion_revisions:
        raise ValueError("suggestion_revision_budget_exhausted")
    if drafts:
        feedback = next(
            (
                f
                for f in reversed(context.store.data.get("validation_feedback", []))
                if f.get("draft_iteration") == drafts[-1]["iteration"]
            ),
            None,
        )
        if feedback is None or feedback.get("valid") is True:
            raise ValueError("a new draft requires rejected feedback for the latest draft")
    call_index = context.store.tool_call("save_suggestion_draft", call_arguments)
    result = context.store.save_draft(draft)
    context.store.tool_success(call_index, result)
    return _dump(result)


@_tool_decorator(timeout=30.0)
async def save_suggestion_validation(
    ctx: RunContextWrapper[SuggestionContext],
    draft_iteration: int = Field(ge=1),
    valid: bool = False,
    issues: list[str] | None = None,
    required_revision: str = "",
) -> str:
    """保存准确绑定最新草稿 iteration 的验证反馈。"""
    context = _runtime(ctx)
    drafts = context.store.data.get("suggestion_drafts", [])
    if not drafts or drafts[-1]["iteration"] != draft_iteration:
        raise ValueError("validator draft_iteration does not match latest draft")
    workspace = await _workspace(context)
    assessment = (
        next(
            (
                s.get("assessment")
                for s in workspace.get("sentences", [])
                if s.get("sentence_id") == context.sentence_id
            ),
            None,
        )
        or {}
    )
    if (
        not assessment.get("finalized")
        or not assessment.get("suggestion_required")
        or drafts[-1].get("assessment_fingerprint") != assessment.get("proposal_fingerprint")
    ):
        raise ValueError("validator requires the current independently accepted assessment")
    if valid and (issues or required_revision.strip()):
        raise ValueError("valid suggestion cannot retain revision issues")
    if not valid and not (issues or required_revision.strip()):
        raise ValueError("invalid suggestion requires actionable feedback")
    feedback = SuggestionValidation(
        review_id=context.review_id,
        sentence_id=context.sentence_id,
        valid=valid,
        issues=issues or [],
        required_revision=required_revision,
    )
    call_arguments = {
        "draft_iteration": draft_iteration,
        "valid": valid,
        "issues": issues or [],
        "required_revision": required_revision,
    }
    if not context.store.guard_replayed_write("save_suggestion_validation", call_arguments):
        cached = context.store.replayed_write_output("save_suggestion_validation", call_arguments)
        if cached is not None:
            return _dump(cached)
        raise RuntimeError("terminal_tool_guard:replayed_state_change")
    if any(
        f.get("draft_iteration") == draft_iteration
        for f in context.store.data.get("validation_feedback", [])
    ):
        raise ValueError(
            "draft already has a validation; revise it instead of overwriting feedback"
        )
    call_index = context.store.tool_call("save_suggestion_validation", call_arguments)
    result = context.store.save_validation(feedback)
    result["feedback_text"] = (
        "当前修改建议已通过独立验证，建议与已接受的评审事实和有效证据一致，可以保存最终建议。"
        if valid else
        "当前修改建议需要修订。验证发现的问题是："
        + "；".join(issues or ["当前草稿需要按验证理由调整"])
        + "。修订要求：" + (required_revision.strip() or "根据上述问题修改草稿，使其与已接受的评审事实和原文证据对应。")
        + ("本轮反馈用于唯一的一次草稿修订，随后验证修订版本。" if draft_iteration < context.max_suggestion_revisions else "首次草稿和一次修订预算已用完，当前建议保存为尚未解决，结束本阶段。")
    )
    context.store._save()
    context.store.tool_success(call_index, result)
    return _dump(result)
