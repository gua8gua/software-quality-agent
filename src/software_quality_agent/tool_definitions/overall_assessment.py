"""overall_assessment definitions for the SDK review workflow."""

from __future__ import annotations

import json
from typing import Literal

from agents import RunContextWrapper
from pydantic import Field

from ..review_runtime.context import SuggestionContext
from ..review_runtime.contracts import OverallIssue
from ..review_runtime.navigation import resolve_location
from .common import _dump, _get, _runtime, _set_review_phase, _tool_decorator, _workspace, _write


@_tool_decorator(timeout=30.0)
async def propose_review_assessment(
    ctx: RunContextWrapper[SuggestionContext],
    status: Literal["implemented", "uncovered", "issues"],
    evaluation_text: str = Field(min_length=1),
    issues: list[OverallIssue] | None = None,
) -> str:
    """全部检查点综合结论完成后、独立验证前，保存整体语段评价。
    子检查点异常汇总到 evaluation_text；无独立整体问题时 issues=[]。不为 insufficient/uncertain 编造反证。每个 OverallIssue 须有真实逐字 canonical 设计证据，不得描述执行错误。即使所有点 supported，整体异常也须给 source_quote、解释和设计引文。后台返回真实 issue/evidence ID 与 proposal_fingerprint。"""
    context = _runtime(ctx)
    if not context.store.stage_complete("review_analysis_verified"):
        raise ValueError("overall_assessment_requires_completed_check_review")
    payload_issues = []
    fixed_passages = []
    if context.review_pipeline == "fixed_tlr":
        workspace = await _workspace(context)
        fixed_passages = [p for p in workspace.get("passages", [])
                          if p.get("sentence_id") == context.sentence_id and p.get("candidate_id")]
    for issue in issues or []:
        refs = []
        for ref in issue.evidence:
            located = await resolve_location(context, ref.location)
            node_id = located["node_id"]
            if context.review_pipeline == "fixed_tlr" and not any(p["design_node_id"] == node_id for p in fixed_passages):
                raise ValueError("简化管线的整体问题证据必须来自已经打开的固定 TLR 资料，不能引入补充节点。")
            if context.bound_target_node_ids and node_id not in context.bound_target_node_ids:
                raise ValueError("overall evidence node outside selected TLR node scope")
            path = f"/api/v1/projects/{context.project_id}/information/nodes/{node_id}"
            parts, offset = [], 0
            while True:
                page = json.loads(
                    await _get(
                        ctx, "get_canonical_node", path, {"text_start": offset, "text_limit": 8000}
                    )
                )
                if page.get("artifact_id") not in context.bound_target_artifact_ids:
                    raise ValueError("overall_evidence_node_outside_target_scope")
                chunk = str(page.get("text") or "")
                if not chunk and page.get("has_more_text"):
                    raise ValueError("canonical_text_page_did_not_advance")
                parts.append(chunk)
                offset += len(chunk)
                if not page.get("has_more_text"):
                    break
            text = "".join(parts)
            if text.count(ref.exact_quote) != 1:
                raise ValueError("overall_evidence_quote_missing_or_ambiguous")
            start = text.index(ref.exact_quote)
            if context.review_pipeline == "fixed_tlr" and not any(
                p["design_node_id"] == node_id and p["start_offset"] <= start
                and start + len(ref.exact_quote) <= p["end_offset"] for p in fixed_passages
            ):
                raise ValueError("整体证据引文超出已经读取的固定资料范围；请先续读该固定资料。")
            refs.append(
                {
                    "node_id": node_id, "exact_quote": ref.exact_quote, "candidate_id": None,
                    "start_offset": start,
                    "end_offset": start + len(ref.exact_quote),
                }
            )
        payload_issues.append({**issue.model_dump(), "evidence": refs})
    result = json.loads(
        await _write(
            ctx,
            "propose_review_assessment",
            "POST",
            f"/api/v1/projects/{context.project_id}/reviews/{context.review_id}"
            f"/sentences/{context.sentence_id}/assessment/propose",
            {"status": status, "evaluation_text": evaluation_text, "issues": payload_issues},
        )
    )
    context.store.transition("overall_assessment_proposed", "completed", output=result)
    _set_review_phase(
        context, "validate_overall_assessment", "返回管理 Agent 调度独立验证；确认前提案尚未接受。"
    )
    result["current_stage"] = "validate_overall_assessment"
    result["next_required_action"] = (
        "返回管理 Agent 调用 validate_segment_assessment；独立验证确认前，提案尚未接受。"
    )
    return _dump(result)


@_tool_decorator(timeout=30.0)
async def validate_review_assessment(
    ctx: RunContextWrapper[SuggestionContext],
    proposal_fingerprint: str,
    accepted: bool,
    reason: str = Field(min_length=1),
) -> str:
    """独立确认或拒绝准确绑定的已保存整体提案。
    通过 get_review_segment 读取 assessment.proposal_fingerprint、完整原文、全部检查点/理由和整体问题的 canonical 证据 ID。不猜指纹，不因现有检查点均 supported 就接受遗漏的要求。拒绝记录为验证反馈，不改写成语义不确定。"""
    context = _runtime(ctx)
    result = json.loads(
        await _write(
            ctx,
            "validate_review_assessment",
            "POST",
            f"/api/v1/projects/{context.project_id}/reviews/{context.review_id}"
            f"/sentences/{context.sentence_id}/assessment/validate",
            {"proposal_fingerprint": proposal_fingerprint, "accepted": accepted, "reason": reason},
        )
    )
    remaining = max(0, 2 - context.store.data.get("workflow_cycles", {}).get("assessment", {}).get("runs", 1))
    result["feedback_text"] = (
        f"当前语段的整体评审已通过独立验证。验证理由：{reason.strip()}。接下来按照已接受的评审结果决定是否生成修改建议。"
        if result.get("finalized") else
        f"当前语段的整体评审需要修订。验证指出：{reason.strip()}。"
        + ("评审分析可以根据这些问题修订一次，保存修订后的完整语段提案，再交给独立验证。" if remaining else "本语段已用完首次处理和一次修订重试，保留当前验证反馈并结束，批次继续下一语段。")
    )
    context.store.transition("overall_assessment_validation", "completed", output=result)
    if result.get("finalized"):
        context.store.transition("overall_assessment_validated", "completed", output=result)
    else:
        context.store.transition("overall_assessment_proposed", "revision_required", output=result)
        if not remaining:
            context.store.data["terminal_tool_error"] = {
                "error_code": "assessment_retry_exhausted", "message": result["feedback_text"]}
            context.store._save()
    return _dump(result)
