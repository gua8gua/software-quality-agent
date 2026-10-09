"""reference_validation definitions for the SDK review workflow."""

from __future__ import annotations

from typing import Any

import httpx

from ..review_runtime.context import SuggestionContext
from .common import _workspace


async def _candidate_ids(context: SuggestionContext, workspace: dict[str, Any]) -> set[str]:
    snapshot = workspace.get("snapshot") or {}
    run_id = workspace.get("tlr_run_id") or snapshot.get("tlr_run_id")
    source_id = workspace.get("requirement_node_id") or snapshot.get("requirement_node_id")
    if not run_id or not source_id:
        return set()
    try:
        result = await context.client.get(
            f"/api/v1/projects/{context.project_id}/information/tlr-runs/{run_id}/nodes/{source_id}/results",
            {"offset": 0, "limit": 100},
        )
        return {
            str(item.get("candidate_id"))
            for item in result.get("items", [])
            if item.get("candidate_id")
        }
    except (httpx.HTTPError, KeyError, TypeError, ValueError, RuntimeError):
        return set()


async def _validate_references(context: SuggestionContext, output: Any) -> list[str]:
    """Validate IDs/ownership and exact quotes before an output is accepted.

    This is deterministic application validation invoked from official SDK
    output guardrails.  It never turns an invalid model result into a fallback.
    """
    errors: list[str] = []
    if getattr(output, "review_id", None) != context.review_id:
        errors.append(f"review_id_not_bound_to_context:{getattr(output, 'review_id', None)!r}")
    if getattr(output, "sentence_id", None) != context.sentence_id:
        errors.append(f"sentence_id_not_bound_to_context:{getattr(output, 'sentence_id', None)!r}")
    workspace = await _workspace(context)
    sentences = {str(item.get("sentence_id")): item for item in workspace.get("sentences", [])}
    sentence = sentences.get(context.sentence_id)
    checks = {
        str(item.get("check_id")): item
        for item in workspace.get("checks", [])
        if item.get("sentence_id") == context.sentence_id
    }
    if sentence is None:
        errors.append("sentence_not_in_review_workspace")
    for check_id in getattr(output, "check_ids", []) + getattr(output, "affected_check_ids", []):
        if check_id not in checks:
            errors.append(f"check_not_owned:{check_id}")
    assessment = (sentence or {}).get("assessment") or {}
    overall_issues = {item["issue_id"] for item in assessment.get("issues", [])}
    for issue_id in getattr(output, "issue_ids", []) + getattr(output, "affected_issue_ids", []):
        if issue_id not in overall_issues or not assessment.get("finalized"):
            errors.append(f"overall_issue_not_accepted:{issue_id}")
    evidence_rows = workspace.get("evidence", [])
    candidate_ids = await _candidate_ids(context, workspace)
    for ref in getattr(output, "evidence", []):
        if ref.kind == "web_source":
            if not ref.url or not ref.url.startswith(("http://", "https://")):
                errors.append(f"web_source_without_url:{ref.identifier}")
            continue
        if ref.kind == "review_evidence":
            related_rows = [
                item
                for item in evidence_rows
                if item.get("evidence_id") == ref.identifier
                and item.get("check_id") in checks
                and (not ref.check_id or item.get("check_id") == ref.check_id)
            ]
            row = next(iter(related_rows), None)
            if row is None:
                errors.append(f"review_evidence_not_found:{ref.identifier}")
            else:
                if row.get("check_id") not in checks:
                    errors.append(f"review_evidence_wrong_sentence:{ref.identifier}")
                if ref.quote and ref.quote != row.get("exact_quote"):
                    errors.append(f"review_evidence_quote_mismatch:{ref.identifier}")
                if ref.relation and not any(
                    item.get("relation") == ref.relation for item in related_rows
                ):
                    errors.append(f"review_evidence_relation_mismatch:{ref.identifier}")
            continue
        if ref.kind == "overall_evidence":
            rows = [
                row
                for issue in assessment.get("issues", [])
                for row in issue.get("evidence", [])
                if row.get("evidence_id") == ref.identifier
            ]
            row = next(iter(rows), None)
            if not assessment.get("finalized") or row is None:
                errors.append(f"overall_evidence_not_accepted:{ref.identifier}")
            elif (
                (ref.quote and ref.quote != row.get("exact_quote"))
                or (ref.node_id and ref.node_id != row.get("node_id"))
                or (ref.candidate_id and ref.candidate_id != row.get("candidate_id"))
            ):
                errors.append(f"overall_evidence_reference_mismatch:{ref.identifier}")
            continue
        if ref.kind == "tlr_candidate":
            candidate_id = ref.candidate_id or ref.identifier
            if candidate_id not in candidate_ids:
                errors.append(f"tlr_candidate_not_owned:{candidate_id}")
        if not ref.node_id:
            errors.append(f"canonical_reference_without_node_id:{ref.identifier}")
            continue
        try:
            node_path = f"/api/v1/projects/{context.project_id}/information/nodes/{ref.node_id}"
            node = await context.client.get(node_path, {"text_start": 0, "text_limit": 8000})
            if node.get("artifact_id") not in context.bound_target_artifact_ids:
                errors.append(f"evidence_node_outside_target_scope:{ref.node_id}")
            if ref.artifact_id and node.get("artifact_id") != ref.artifact_id:
                errors.append(f"node_artifact_mismatch:{ref.node_id}")
            if ref.quote:
                found = ref.quote in str(node.get("text") or "")
                position = 8000 - min(len(ref.quote) - 1, 3999)
                total = int(node.get("text_total_chars") or 0)
                while not found and position < total:
                    page = await context.client.get(
                        node_path, {"text_start": position, "text_limit": 8000}
                    )
                    found = ref.quote in str(page.get("text") or "")
                    position += 8000 - min(len(ref.quote) - 1, 3999)
                if not found:
                    errors.append(f"quote_not_in_canonical_node:{ref.node_id}")
        except (httpx.HTTPError, KeyError, TypeError, ValueError, RuntimeError) as exc:
            errors.append(f"canonical_node_unreadable:{ref.node_id}:{type(exc).__name__}")
    return errors
