"""guardrails definitions for the SDK review workflow."""

from __future__ import annotations

from agents import Agent, GuardrailFunctionOutput, RunContextWrapper
from agents.decorators import output_guardrail

from .context import SuggestionContext
from .results import _project_persisted_result


@output_guardrail
async def analysis_workspace_guardrail(
    ctx: RunContextWrapper[SuggestionContext], agent: Agent, output: str
) -> GuardrailFunctionOutput:
    """An analysis Agent cannot finish by prose before checks and visits persist."""
    complete = ctx.context.store.stage_complete(
        "review_analysis_verified"
    ) and ctx.context.store.stage_complete("overall_assessment_proposed")
    return GuardrailFunctionOutput(
        output_info={"review_analysis_verified": complete}, tripwire_triggered=not complete
    )


@output_guardrail
async def suggestion_workspace_guardrail(
    ctx: RunContextWrapper[SuggestionContext], agent: Agent, output: str
) -> GuardrailFunctionOutput:
    current = len(ctx.context.store.data.get("suggestion_drafts", []))
    previous = int(ctx.context.store.data.get("suggestion_start_draft_count", 0))
    return GuardrailFunctionOutput(
        output_info={"draft_saved_this_run": current > previous},
        tripwire_triggered=current <= previous,
    )


@output_guardrail
async def validator_workspace_guardrail(
    ctx: RunContextWrapper[SuggestionContext], agent: Agent, output: str
) -> GuardrailFunctionOutput:
    if ctx.context.store.data.get("specialist_activity", {}).get("tool") == "validate_segment_assessment":
        recorded = ctx.context.store.stage_complete("overall_assessment_validation")
        return GuardrailFunctionOutput(
            output_info={"overall_validation_recorded": recorded}, tripwire_triggered=not recorded
        )
    current = len(ctx.context.store.data.get("validation_feedback", []))
    previous = int(ctx.context.store.data.get("validator_start_feedback_count", 0))
    return GuardrailFunctionOutput(
        output_info={"feedback_saved_this_run": current > previous},
        tripwire_triggered=current <= previous,
    )


@output_guardrail
async def manager_workspace_guardrail(
    ctx: RunContextWrapper[SuggestionContext], agent: Agent, output: str
) -> GuardrailFunctionOutput:
    """SDK guardrail: manager prose cannot replace verified persisted facts."""
    try:
        projected = await _project_persisted_result(ctx.context)
    except (RuntimeError, ValueError, KeyError, TypeError) as exc:
        return GuardrailFunctionOutput(
            output_info={"workspace_error": str(exc)}, tripwire_triggered=True
        )
    return GuardrailFunctionOutput(
        output_info={"projected_status": projected.execution_status}, tripwire_triggered=False
    )
