"""review_progress definitions for the SDK review workflow."""

from __future__ import annotations

import json

from agents import RunContextWrapper

from ..review_runtime.context import SuggestionContext
from .common import (
    _dump,
    _get,
    _passage_failure,
    _review_phase,
    _runtime,
    _tool_decorator,
    _workspace,
)


@_tool_decorator(timeout=30.0)
async def get_review_investigation(ctx: RunContextWrapper[SuggestionContext]) -> str:
    """读取全部检查点覆盖状态、已调查分支、当前阶段和剩余补充预算。"""
    context = _runtime(ctx)
    workspace = await _workspace(context)
    state = json.loads(
        await _get(
            ctx,
            "get_review_investigation",
            f"/api/v1/projects/{context.project_id}/reviews/{context.review_id}"
            f"/sentences/{context.sentence_id}/investigation",
        )
    )
    passages = [
        p for p in workspace.get("passages", []) if p.get("sentence_id") == context.sentence_id
    ]
    supplemental_count = sum(1 for p in passages if not p.get("candidate_id"))
    sentence = next(
        (s for s in workspace.get("sentences", []) if s.get("sentence_id") == context.sentence_id),
        None,
    )
    # Repeated identical status queries are not business progress. This is a
    # local replay guard, not a total time/turn limit on the segment Runner.
    signature = json.dumps([state, passages], ensure_ascii=False, sort_keys=True, default=str)
    previous = context.store.data.get("investigation_replay", {})
    repeats = int(previous.get("repeats", 0)) + 1 if previous.get("signature") == signature else 0
    context.store.data["investigation_replay"] = {"signature": signature, "repeats": repeats}
    if repeats >= context.passage_max_turns:
        active = next((p for p in passages if p.get("status") == "pending"), None)
        context.store.data["investigation_replay"] = {}
        if active and not state.get("can_stop_for_sufficient_evidence"):
            return await _passage_failure(ctx, active["passage_id"], "get_review_investigation",
                "no_business_progress", RuntimeError("反复读取同一调查状态，未新增评估或资料。请按剩余检查点修正动作，而不是再次查询状态。"))
        context.store.data["terminal_tool_error"] = {
            "tool": "get_review_investigation", "error_code": "no_business_progress",
            "message": "调查状态没有变化，重复查询无法推进；结束当前执行，保留事实并继续其他独立语段。",
        }
        context.store._save()
        raise RuntimeError("no_business_progress:repeated unchanged investigation state")
    current_stage, next_action = _review_phase(state, sentence, pipeline=context.review_pipeline)
    if context.store.stage_complete("overall_assessment_validated"):
        current_stage, next_action = (
            "draft_suggestion_or_complete",
            "suggestion_required=true 时读取完整评价并生成建议，否则返回完成结果。",
        )
    elif context.store.stage_complete("overall_assessment_proposed"):
        current_stage, next_action = (
            "validate_overall_assessment",
            "返回管理 Agent 调度独立验证，不打开新资料段。",
        )
    elif context.store.stage_complete("review_analysis_verified"):
        current_stage, next_action = (
            "propose_overall_assessment",
            "基于已保存的综合事实调用 propose_review_assessment，不打开新资料段。",
        )
    context.store.data["current_review_phase"] = current_stage
    context.store.data["current_review_next_action"] = next_action
    context.store._save()
    return _dump(
        {
            **state,
            "passages": passages,
            "current_stage": current_stage,
            "review_pipeline": context.review_pipeline,
            "phase_protocol": [
                "extract_checks -> finalize_review_checks",
                "select_mandatory_sds_passage -> read_next_tlr_material（无需选择候选）",
                "assess_current_passage -> 每个检查点调用 assess_review_check -> finalize_review_passage",
                *( ["supplementary_sds_search_or_conclude -> Review Analysis 先查结构/节点摘要，再调用 investigate_review_material"]
                   if context.review_pipeline == "full_investigation" else []),
                "conclude_checks -> 用 complete_review_analysis 保存每个检查点综合结论",
                "propose_overall_assessment -> propose_review_assessment",
            ],
            "supplemental_passage_budget": {
                "limit": context.supplemental_passage_limit,
                "opened": supplemental_count,
                "remaining": max(0, context.supplemental_passage_limit - supplemental_count),
                "rule": "固定 TLR 管线不允许补充资料调查。" if context.review_pipeline == "fixed_tlr" else "仅高优先 TLR 调查完成后才允许打开补充资料段。",
            },
            "analysis_lifecycle_completed": context.store.stage_complete(
                "review_analysis_verified"
            ),
            "next_required_action": (
                "调用 propose_review_assessment，不再打开或评估新资料段"
                if context.store.stage_complete("review_analysis_verified")
                and not context.store.stage_complete("overall_assessment_proposed")
                else next_action
            ),
            "repeat_status_query_count": repeats,
            "repeat_status_query_warning": "此查询未产生新事实，请执行 next_required_action 而不是继续查询。" if repeats else None,
        }
    )


@_tool_decorator(timeout=30.0)
async def finish_review_incomplete(ctx: RunContextWrapper[SuggestionContext]) -> str:
    """没有可继续的高优先任务且有执行失败时，保留局部事实并结束本语段。
    不产生语义结论，也不把 pending 检查点改成 uncertain/insufficient。其他独立语段由批次继续处理。
    有可继续资料时不能使用；全部检查点合法满足时应保存综合结论，而不是调用本工具。
    """
    context = _runtime(ctx)
    state = await context.client.get(
        f"/api/v1/projects/{context.project_id}/reviews/{context.review_id}"
        f"/sentences/{context.sentence_id}/investigation")
    no_fixed_material = context.review_pipeline == "fixed_tlr" and not state.get("passage_count")
    if (state.get("can_stop_for_sufficient_evidence") or state.get("unfinished_passage_ids")
            or state.get("mandatory_unattempted_node_ids", state.get("mandatory_remaining_node_ids"))
            or not (state.get("blocked_passage_ids") or no_fixed_material)):
        raise ValueError("仍有可继续任务、没有执行失败或已经满足；不能以执行失败结束。")
    error = {"tool": "finish_review_incomplete",
             "error_code": "no_fixed_tlr_material" if no_fixed_material else "incomplete_after_passage_failures",
             "message": "没有可检查的固定 TLR 资料，不伪造无覆盖结论；继续其他独立语段。" if no_fixed_material else "资料重试后仍失败，局部评估和异常已保存；本语段未形成完整结论，继续其他独立语段。"}
    context.store.data["terminal_tool_error"] = error
    context.store.transition("review_analysis", "blocked", error_code=error["error_code"], error_message=error["message"])
    return _dump({"execution_status": "blocked", "semantic_status": None,
                  "error_code": error["error_code"], "error_message": error["message"],
                  "execution_errors": state.get("execution_errors", [])})


@_tool_decorator(timeout=30.0)
async def get_review_progress(ctx: RunContextWrapper[SuggestionContext]) -> str:
    """供管理 Agent 读取精炼业务状态，不包含完整 canonical 证据包。"""
    context = _runtime(ctx)
    workspace = await _workspace(context)
    coverage = await context.client.get(
        f"/api/v1/projects/{context.project_id}/reviews/{context.review_id}"
        f"/sentences/{context.sentence_id}/investigation"
    )
    checks = [c for c in workspace.get("checks", []) if c.get("sentence_id") == context.sentence_id]
    sentence = next(
        (s for s in workspace.get("sentences", []) if s.get("sentence_id") == context.sentence_id),
        {},
    )
    assessment = sentence.get("assessment") or {}
    validation = assessment.get("validation") or {}
    call_index = context.store.tool_call(
        "get_review_progress", {"sentence_id": context.sentence_id}
    )
    # This tool is called by the Manager on every specialist boundary. Keep it
    # deliberately small so the SDK can inline it; full proposals/issues and
    # evidence remain available through get_review_segment. Returning the
    # complete assessment here made the local model page a saved-result index
    # repeatedly and exhaust its Manager turn budget without advancing state.
    investigation = {
        key: coverage.get(key)
        for key in ("checks_finalized", "source_anchor_status", "can_stop_for_sufficient_evidence")
    }
    investigation["unfinished_passage_count"] = len(coverage.get("unfinished_passage_ids") or [])
    investigation["blocked_passage_count"] = len(coverage.get("blocked_passage_ids") or [])
    investigation["mandatory_remaining_count"] = len(
        coverage.get("mandatory_remaining_node_ids") or []
    )
    investigation["conclusions_complete"] = coverage.get("conclusions_complete", False)
    investigation["remaining_conclusion_check_ids"] = coverage.get(
        "remaining_conclusion_check_ids", []
    )
    current_stage, next_action = _review_phase(coverage, sentence, pipeline=context.review_pipeline)
    if context.store.stage_complete("overall_assessment_validated"):
        current_stage, next_action = (
            "draft_suggestion_or_complete",
            "仅 suggestion_required=true 时调度建议 Agent，否则完成。",
        )
    elif context.store.stage_complete("overall_assessment_proposed"):
        current_stage, next_action = ("validate_overall_assessment", "调度独立整体评价验证。")
    elif context.store.stage_complete("review_analysis_verified"):
        current_stage, next_action = (
            "propose_overall_assessment",
            "调度整体提案保存，不重启证据调查。",
        )
    context.store.data["current_review_phase"] = current_stage
    context.store.data["current_review_next_action"] = next_action
    context.store._save()
    compact_assessment = {
        key: assessment.get(key)
        for key in ("finalized", "suggestion_required", "semantic_status", "assessment_validity")
    }
    compact_assessment["validation_accepted"] = validation.get("accepted")
    if not context.store.stage_complete("overall_assessment_proposed"):
        next_tool = "run_review_analysis"
    elif not context.store.stage_complete("overall_assessment_validated"):
        next_tool = "validate_segment_assessment"
    elif not assessment.get("suggestion_required"):
        next_tool = None
    else:
        from ..workflow_state import suggestion_phase

        phase = suggestion_phase(context.store.data, assessment, context.max_suggestion_revisions)
        next_tool = {
            "draft": "draft_modification_suggestion",
            "validate": "validate_modification_suggestion",
            "exhausted": "complete_unresolved",
            "complete": "complete",
            "not_needed": None,
        }[phase]
    result = {
        "review_id": context.review_id,
        "review_pipeline": context.review_pipeline,
        "sentence_id": context.sentence_id,
        "review_status": workspace.get("status"),
        "investigation": investigation,
        "assessment": compact_assessment,
        "check_count": len(checks),
        "pending_check_count": sum(c["status"] == "pending" for c in checks),
        "next_workflow_tool": next_tool,
        "current_stage": current_stage,
        "next_required_action": next_action,
        "analysis_completed": context.store.stage_complete("review_analysis_verified"),
    }
    context.store.tool_success(call_index, result)
    return _dump(result)
