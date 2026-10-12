"""results definitions for the SDK review workflow."""

from __future__ import annotations

from ..tool_definitions.reference_validation import _validate_references
from .context import SuggestionContext
from .contracts import EvidenceReference, SuggestionOutput


async def _project_persisted_result(context: SuggestionContext) -> SuggestionOutput:
    """Project verified workspace facts; never ask a fallback model to invent JSON."""
    if not context.store.stage_complete("review_analysis_verified"):
        raise RuntimeError("review_analysis_agent_did_not_finish_its_lifecycle")
    workspace = await context.client.get(
        f"/api/v1/projects/{context.project_id}/reviews/{context.review_id}/workspace"
    )
    checks = [
        item
        for item in workspace.get("checks", [])
        if item.get("sentence_id") == context.sentence_id
    ]
    sentence = (
        next(
            (
                s
                for s in workspace.get("sentences", [])
                if s.get("sentence_id") == context.sentence_id
            ),
            None,
        )
        or {}
    )
    assessment = sentence.get("assessment") or {}
    if not assessment.get("finalized"):
        raise RuntimeError("whole_segment_assessment_not_validated")
    if not checks:
        raise RuntimeError("review_analysis_produced_no_verification_points")
    pending = [item["check_id"] for item in checks if item.get("status") == "pending"]
    if pending:
        raise RuntimeError(f"review_analysis_left_pending_checks:{pending}")
    evidence_rows = [
        item
        for item in workspace.get("evidence", [])
        if item.get("check_id") in {check["check_id"] for check in checks}
    ]
    for check in checks:
        required_relation = {"supported": {"supporting", "context"}, "contradicted": {"counter"}}.get(
            check.get("status")
        )
        if required_relation and not any(
            row.get("check_id") == check["check_id"]
            and row.get("relation") in required_relation
            and row.get("validation_status") == "valid"
            for row in evidence_rows
        ):
            raise RuntimeError(
                f"检查点 {check['check_id']} 缺少与当前状态对应的有效原文证据。已满足状态允许 supporting 或 context 关系，存在矛盾状态使用 counter 关系。"
            )

    scope = await context.client.get(
        f"/api/v1/projects/{context.project_id}/reviews/{context.review_id}"
        f"/sentences/{context.sentence_id}/investigation"
    )
    if not scope.get("checks_finalized"):
        raise RuntimeError("verification_point_set_not_finalized")
    if not scope.get("conclusions_complete"):
        raise RuntimeError("cumulative_check_conclusions_incomplete")
    if not scope.get("can_stop_for_sufficient_evidence") and (
        scope.get("mandatory_remaining_node_ids")
        or scope.get("unfinished_passage_ids")
        or scope.get("blocked_passage_ids")
        or not scope.get("passage_count")
    ):
        raise RuntimeError("passage_all_check_coverage_incomplete")
    scope["review_pipeline"] = context.review_pipeline
    scope["evidence_scope"] = "固定 TLR 资料范围，不代表全 SDS 文档" if context.review_pipeline == "fixed_tlr" else "固定 TLR 资料及已记录的补充调查范围"

    abnormal = [
        item
        for item in checks
        if item.get("status") in {"contradicted", "insufficient", "uncertain"}
    ]
    if not assessment.get("suggestion_required"):
        return SuggestionOutput(
            execution_status="completed",
            review_id=context.review_id,
            sentence_id=context.sentence_id,
            investigation_scope=scope,
            problem_summary=assessment.get("evaluation_text", ""),
        )

    drafts = context.store.data.get("suggestion_drafts", [])
    feedback = context.store.data.get("validation_feedback", [])
    if not drafts or not feedback:
        raise RuntimeError("suggestion_or_validator_did_not_persist_result")
    latest_draft, latest_validation = drafts[-1], feedback[-1]
    if latest_draft.get("assessment_fingerprint") != assessment.get("proposal_fingerprint"):
        raise RuntimeError("suggestion_based_on_stale_assessment")
    if latest_validation.get("draft_iteration") != latest_draft.get("iteration"):
        raise RuntimeError("latest_suggestion_draft_not_validated")
    if not latest_validation.get("valid"):
        return SuggestionOutput(
            execution_status="unresolved",
            review_id=context.review_id,
            sentence_id=context.sentence_id,
            problem_summary=latest_draft.get("problem_summary", ""),
            affected_check_ids=[item["check_id"] for item in abnormal],
            affected_issue_ids=[item["issue_id"] for item in assessment.get("issues", [])],
            unresolved_questions=list(latest_validation.get("issues") or [])
            + (
                [latest_validation["required_revision"]]
                if latest_validation.get("required_revision")
                else []
            ),
        )
    affected = set(latest_draft.get("check_ids") or [])
    abnormal_ids = {item["check_id"] for item in abnormal}
    if not abnormal_ids.issubset(affected):
        raise RuntimeError("validated_suggestion_omits_abnormal_checks")
    affected_issues = set(latest_draft.get("issue_ids") or [])
    if not {i["issue_id"] for i in assessment.get("issues", [])}.issubset(affected_issues):
        raise RuntimeError("validated_suggestion_omits_overall_issues")
    semantic_unresolved = any(item["status"] in {"insufficient", "uncertain"} for item in abnormal)
    output = SuggestionOutput(
        execution_status="unresolved" if semantic_unresolved else "completed",
        investigation_scope=scope,
        review_id=context.review_id,
        sentence_id=context.sentence_id,
        problem_summary=latest_draft.get("problem_summary", ""),
        suggestion_text=latest_draft.get("suggestion_text", ""),
        rationale=latest_draft.get("rationale", ""),
        affected_check_ids=list(affected),
        affected_issue_ids=list(affected_issues),
        evidence=[
            EvidenceReference.model_validate(item) for item in latest_draft.get("evidence", [])
        ],
        unresolved_questions=list(latest_draft.get("unresolved_questions") or []),
    )
    errors = await _validate_references(context, output)
    if output.execution_status == "completed" and not output.evidence:
        errors.append("completed_suggestion_has_no_evidence")
    if errors:
        raise RuntimeError("suggestion_projection_guardrail:" + ";".join(errors))
    return output
