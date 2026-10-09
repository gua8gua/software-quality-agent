"""control definitions for the SDK review workflow."""

from __future__ import annotations

import json
from typing import Any

from agents import RunConfig
from agents.agent import ToolsToFinalOutputResult
from httpx import HTTPError

from ..execution_errors import ReviewDependencyError
from ..llm_admission import ModelAdmissionBlocked
from ..tool_definitions.common import _workspace
from ..workflow_state import suggestion_phase
from .context import BackendOwnershipError, SuggestionContext
from .model_input import _bounded_model_input
from .results import _project_persisted_result


def _nested_config() -> RunConfig:
    return RunConfig(call_model_input_filter=_bounded_model_input)


async def _suggestion_needed(ctx: Any, _agent: Any) -> bool:
    context = ctx.context
    if not context.store.stage_complete("review_analysis_verified"):
        return False
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
    return bool(assessment.get("finalized") and assessment.get("suggestion_required"))


async def _suggestion_stage(ctx: Any) -> str:
    if not await _suggestion_needed(ctx, None):
        return "not_needed"
    workspace = await _workspace(ctx.context)
    assessment = next(
        s["assessment"]
        for s in workspace["sentences"]
        if s["sentence_id"] == ctx.context.sentence_id
    )
    return suggestion_phase(
        ctx.context.store.data, assessment, ctx.context.max_suggestion_revisions
    )


async def _draft_enabled(ctx: Any, _agent: Any) -> bool:
    return await _suggestion_stage(ctx) == "draft"


async def _suggestion_validation_enabled(ctx: Any, _agent: Any) -> bool:
    return await _suggestion_stage(ctx) == "validate"


async def _manager_tool_completion(ctx: Any, tool_results: list[Any]) -> ToolsToFinalOutputResult:
    """SDK-native terminal handling: verified sufficient evidence needs no draft."""
    if (
        tool_results
        and ctx.context.store.stage_complete("overall_assessment_validated")
        and await _suggestion_stage(ctx) in {"not_needed", "complete", "exhausted"}
    ):
        result = await _project_persisted_result(ctx.context)
        if result.execution_status in {"completed", "unresolved"}:
            return ToolsToFinalOutputResult(
                is_final_output=True,
                final_output="CURRENT_STAGE=manager_completion；评审/建议已到持久化终点，返回真实 completed 或 unresolved 结果。",
            )
    return ToolsToFinalOutputResult(is_final_output=False)


async def _assessment_tool_completion(
    ctx: Any, tool_results: list[Any]
) -> ToolsToFinalOutputResult:
    """Finish a specialist at its persisted boundary using the SDK tool loop.

    Only THIS turn's successful write, matching its saved stage output, can
    finish. An old completed stage or a recoverable tool error is insufficient.
    Runner still applies the Agent's output guardrail to the terminal output.
    A rejected validation also returns to Manager; it is not an accepted review.
    """
    store = ctx.context.store
    terminal_error = store.data.get("terminal_tool_error")
    if terminal_error:
        # A deterministic cursor guard has already persisted the failure. Do
        # not give the model another opportunity to replay the same action;
        # the outer workflow will project this attempt as blocked.
        raise RuntimeError(
            f"terminal_tool_guard:{terminal_error.get('error_code')}:{terminal_error.get('message')}"
        )
    for result in tool_results:
        name = result.tool.name
        if name == "save_suggestion_validation":
            # Validator's business boundary is the persisted feedback record;
            # do not ask the model for a second prose turn that can replay the
            # same write and consume the specialist's turn budget.
            try:
                value = (
                    json.loads(result.output) if isinstance(result.output, str) else result.output
                )
            except (ValueError, TypeError):
                value = None
            drafts = store.data.get("suggestion_drafts", [])
            feedback = store.data.get("validation_feedback", [])
            if (
                isinstance(value, dict)
                and drafts
                and feedback
                and value == feedback[-1]
                and value.get("review_id") == ctx.context.review_id
                and value.get("sentence_id") == ctx.context.sentence_id
                and value.get("draft_iteration") == drafts[-1].get("iteration")
            ):
                return ToolsToFinalOutputResult(
                    is_final_output=True,
                    final_output=value.get("feedback_text") or "建议验证已保存，返回管理 Agent 决定修订或完成。",
                )
        if name not in {"propose_review_assessment", "validate_review_assessment"}:
            continue
        try:
            value = json.loads(result.output) if isinstance(result.output, str) else result.output
        except (ValueError, TypeError):
            continue
        if not isinstance(value, dict) or value.get("sentence_id") != ctx.context.sentence_id:
            continue
        proposal = name == "propose_review_assessment"
        stage = "overall_assessment_proposed" if proposal else "overall_assessment_validation"
        if not store.stage_complete(stage) or value != store.data.get("stage_outputs", {}).get(
            stage
        ):
            continue
        if proposal and (
            not store.stage_complete("review_analysis_verified")
            or not value.get("proposal")
            or not value.get("proposal_fingerprint")
        ):
            continue
        if not proposal and not isinstance((value.get("validation") or {}).get("accepted"), bool):
            continue
        return ToolsToFinalOutputResult(
            is_final_output=True,
            final_output=(
                "CURRENT_STAGE=validate_overall_assessment；整体提案已保存，返回管理 Agent 调度独立验证。"
                if proposal
                else value.get("feedback_text") or "独立验证已保存，管理 Agent 根据中文理由决定修订或完成。"
            ),
        )
    return ToolsToFinalOutputResult(is_final_output=False)


async def _suggestion_tool_completion(
    ctx: Any, tool_results: list[Any]
) -> ToolsToFinalOutputResult:
    """End the Suggestion Agent immediately after a draft is durably saved."""
    for result in tool_results:
        if result.tool.name != "save_suggestion_draft":
            continue
        try:
            value = json.loads(result.output) if isinstance(result.output, str) else result.output
        except (ValueError, TypeError):
            value = None
        drafts = ctx.context.store.data.get("suggestion_drafts", [])
        if (
            isinstance(value, dict)
            and drafts
            and value == drafts[-1]
            and value.get("review_id") == ctx.context.review_id
            and value.get("sentence_id") == ctx.context.sentence_id
        ):
            return ToolsToFinalOutputResult(
                is_final_output=True,
                final_output="CURRENT_STAGE=validate_suggestion；建议草稿已保存，返回管理 Agent 调度独立验证。",
            )
    return ToolsToFinalOutputResult(is_final_output=False)


async def _terminal_tool_completion(ctx: Any, tool_results: list[Any]) -> ToolsToFinalOutputResult:
    """Finish a child Agent after one persisted SDK/tool protocol failure."""
    error = ctx.context.store.data.get("terminal_tool_error")
    if error:
        return ToolsToFinalOutputResult(
            is_final_output=True,
            final_output=json.dumps(
                {
                    "execution_status": "blocked",
                    "current_stage": "blocked_execution",
                    "error_code": error.get("error_code"),
                    "error_message": error.get("message"),
                },
                ensure_ascii=False,
            ),
        )
    for result in tool_results:
        if result.tool.name not in {"read_next_tlr_material", "open_supplementary_material"}:
            continue
        try:
            value = json.loads(result.output)
        except (ValueError, TypeError):
            continue
        if value.get("execution_status") in {"ready_to_conclude", "priority_materials_exhausted", "current_material_pending", "blocked"}:
            return ToolsToFinalOutputResult(is_final_output=True, final_output=result.output)
        if (
            value.get("passage_id")
            and value.get("text")
            and value.get("execution_status") != "blocked"
        ):
            # Investigator's responsibility ends at registering the next real
            # material. It must return to Analysis to evaluate all checks;
            # tool_choice=required otherwise prevents any normal child exit.
            return ToolsToFinalOutputResult(is_final_output=True, final_output=result.output)
    return ToolsToFinalOutputResult(is_final_output=False)


async def _investigation_enabled(ctx: Any, _agent: Any) -> bool:
    """Enable the nested investigator only for bounded supplemental work.

    Official TLR traversal is deterministic and belongs to Review Analysis.
    Keeping the child disabled while mandatory nodes remain prevents a second
    model loop from competing with the saved TLR cursor.
    """
    context = ctx.context
    if context.review_pipeline == "fixed_tlr":
        return False
    if context.store.stage_complete("review_analysis_verified"):
        return False
    scope = await context.client.get(
        f"/api/v1/projects/{context.project_id}/reviews/{context.review_id}"
        f"/sentences/{context.sentence_id}/investigation"
    )
    workspace = await _workspace(context)
    if scope.get("can_stop_for_sufficient_evidence"):
        return False
    if scope.get("mandatory_unattempted_node_ids", scope.get("mandatory_remaining_node_ids")):
        return False
    if any(
        p.get("sentence_id") == context.sentence_id
        and p.get("status") in {"pending", "in_progress"}
        for p in workspace.get("passages", [])
    ):
        return False
    return any(
        s.get("sentence_id") == context.sentence_id and s.get("checks_finalized")
        for s in workspace.get("sentences", [])
    )


async def _analysis_material_tool_enabled(ctx: Any, _agent: Any) -> bool:
    """Keep deterministic TLR/material completion tools available to Analysis."""
    context = ctx.context
    if context.store.stage_complete("review_analysis_verified"):
        return False
    workspace = await _workspace(context)
    return any(
        s.get("sentence_id") == context.sentence_id and s.get("checks_finalized")
        for s in workspace.get("sentences", [])
    )


async def _conclusion_enabled(ctx: Any, _agent: Any) -> bool:
    if ctx.context.store.stage_complete("review_analysis_verified"):
        return False
    workspace = await _workspace(ctx.context)
    scope = await ctx.context.client.get(
        f"/api/v1/projects/{ctx.context.project_id}/reviews/{ctx.context.review_id}"
        f"/sentences/{ctx.context.sentence_id}/investigation")
    if scope.get("can_stop_for_sufficient_evidence"):
        return True
    if any(p.get("sentence_id") == ctx.context.sentence_id and p.get("status") in {"pending", "in_progress"}
           for p in workspace.get("passages", [])):
        return False
    return any(
        s.get("sentence_id") == ctx.context.sentence_id and s.get("checks_finalized")
        for s in workspace.get("sentences", [])
    )


def _nested_failure(ctx: Any, error: Exception) -> str:
    if isinstance(error, (BackendOwnershipError, ReviewDependencyError)):
        raise error
    runtime = getattr(ctx, "context", None)
    if isinstance(runtime, SuggestionContext):
        runtime.store.tool_error("agent_as_tool", str(error))
    return f"Nested agent execution failed: {type(error).__name__}: {error}"


def _fatal_nested_failure(ctx: Any, error: Exception) -> str:
    if isinstance(error, (BackendOwnershipError, ModelAdmissionBlocked)):
        raise error
    runtime = getattr(ctx, "context", None)
    if isinstance(runtime, SuggestionContext):
        # SDK end hooks can run before output guardrails. A subsequent
        # tripwire is still a failed specialist, not a completed graph node.
        stage = {
            "run_review_analysis": "review_analysis",
            "investigate_review_material": "evidence",
            "validate_segment_assessment": "assessment_validator",
            "draft_modification_suggestion": "suggestion",
            "validate_modification_suggestion": "suggestion_validator",
        }.get(getattr(ctx, "tool_name", None))
        if stage:
            runtime.store.transition(
                stage, "blocked", error_code=type(error).__name__, error_message=str(error)
            )
        # A child may already have persisted a precise terminal cause (for
        # example exhausted passage failures). Do not replace it with the
        # generic wrapper error or reset its retry/skip decision.
        if not runtime.store.data.get("terminal_tool_error"):
            runtime.store.data["terminal_tool_error"] = {
                "tool": getattr(ctx, "tool_name", "nested_agent"),
                "error_code": "specialist_execution_failed",
                "message": f"{type(error).__name__}: {error}"[:2000],
            }
        runtime.store._save()
        runtime.store.tool_error("agent_as_tool", str(error))
    if isinstance(error, ReviewDependencyError):
        raise error
    raise RuntimeError(f"specialist_execution_failed:{type(error).__name__}:{error}") from error


def _bound_task_params(params: dict[str, Any], context: SuggestionContext) -> dict[str, Any]:
    # Only immutable host identity is injected. Foreign identity is rejected,
    # never typo-corrected after the model selected a target.
    for key, value in (("review_id", context.review_id), ("sentence_id", context.sentence_id)):
        if key in params and params[key] != value:
            raise ValueError("specialist is outside current source segment")
    return {**params, "review_id": context.review_id, "sentence_id": context.sentence_id}


def _input_builder(
    base: dict[str, Any],
    *,
    context: SuggestionContext | None = None,
    required_stage: str | None = None,
):
    def build(options: dict[str, Any]) -> str:
        params = options.get("params") or {}
        if context is not None:
            params = _bound_task_params(params, context)
        if (
            required_stage
            and context is not None
            and not context.store.stage_complete(required_stage)
        ):
            raise RuntimeError(f"specialist_prerequisite_missing:{required_stage}")
        # Immutable identity is checked locally, not echoed into specialist prompts.
        semantic = {key: value for key, value in {**base, **params}.items()
                    if key not in {"sentence", "review_id", "sentence_id"}}
        return json.dumps(semantic, ensure_ascii=False, separators=(",", ":"))

    return build


def _evidence_input_builder(base: dict[str, Any], context: SuggestionContext):
    async def build(options: dict[str, Any]) -> str:
        params = _bound_task_params(options.get("params") or {}, context)
        workspace = await _workspace(context)
        sentence = next(
            s for s in workspace["sentences"] if s["sentence_id"] == context.sentence_id
        )
        if not sentence.get("checks_finalized"):
            raise RuntimeError("evidence investigation requires a finalized check set")
        context.store.tool_call("investigate_review_material_invocation", params)
        # Source/check facts are rehydrated by the SDK input hook, once, in the
        # child role's semantic view. Do not duplicate raw workspace IDs here.
        location = str(params.get("location") or "").strip()
        if not location:
            raise ValueError(
                "investigate_review_material 必须传入结构查询返回的 location；"
                "先调用 get_node_summary 或 browse_document_structure。"
            )
        payload = {"investigation_goal": params.get("investigation_goal"), "location": location}
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    return build


async def _assessment_needs_validation(ctx: Any, _agent: Any) -> bool:
    return ctx.context.store.stage_complete(
        "overall_assessment_proposed"
    ) and not ctx.context.store.stage_complete("overall_assessment_validated")


def _restore_overall_checkpoint(context: SuggestionContext, sentence: dict[str, Any]) -> None:
    """Restore only current backend business facts into SDK tool availability.

    A pending proposal is not an accepted conclusion. Restoring it makes the
    existing Validator tool available without regenerating the proposal or
    replacing the SDK Runner/session with an application reasoning loop.
    """
    if not context.store.stage_complete("review_analysis_verified"):
        return
    assessment = sentence.get("assessment") or {}
    if assessment.get("finalized"):
        context.store.transition("overall_assessment_proposed", "completed", output=assessment)
        context.store.transition("overall_assessment_validated", "completed", output=assessment)
    elif (
        assessment.get("proposal_current") is True
        and assessment.get("proposal")
        and assessment.get("proposal_fingerprint")
        and (assessment.get("validation") or {}).get("accepted") is not False
    ):
        context.store.transition("overall_assessment_proposed", "completed", output=assessment)


async def _persist_active_passage_failure(
    context: SuggestionContext, code: str, message: str
) -> None:
    """Do not depend on a failed model to label its unfinished passage task."""
    passage_id = context.store.data.get("active_passage_id")
    if not passage_id:
        return
    try:
        workspace = await _workspace(context)
        passage = next(
            (
                p
                for p in workspace.get("passages", [])
                if p.get("passage_id") == passage_id and p.get("sentence_id") == context.sentence_id
            ),
            None,
        )
        if passage is not None and passage.get("status") == "pending":
            await context.client.write(
                "POST",
                f"/api/v1/projects/{context.project_id}/reviews/{context.review_id}/passages/{passage_id}/error",
                {"error_code": code[:64], "error_message": message[:2000],
                 "retryable": code not in {"worker_interrupted", "shared_dependency_unavailable"},
                 "failure_id": f"host:{context.store.data.get('attempt_id')}:{code}"},
            )
    except (
        HTTPError,
        OSError,
        RuntimeError,
        ValueError,
        KeyError,
        ReviewDependencyError,
    ) as state_error:
        context.store.tool_error("persist_active_passage_failure", str(state_error))
