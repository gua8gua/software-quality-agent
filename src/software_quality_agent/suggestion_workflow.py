"""SDK role assembly, Runner dispatch and resumable per-sentence execution."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from agents import (
    Agent,
    AgentsException,
    OutputGuardrailTripwireTriggered,
    RunConfig,
    Runner,
    SQLiteSession,
    trace,
)
from filelock import FileLock
from filelock import Timeout as FileLockTimeout
from httpx import HTTPError
from openai import APIError

from .execution_errors import ReviewDependencyError
from .llm_admission import ModelAdmissionBlocked
from .model_runtime.profiles import profile_for
from .model_runtime.provider import build_model
from .review_runtime.checkpoint import CheckpointStore
from .review_runtime.context import (
    MAX_EVIDENCE_INVESTIGATOR_TURNS,
    MAX_SUPPLEMENTAL_PASSAGES,
    BackendClient,
    BackendOwnershipError,
    SuggestionContext,
)
from .review_runtime.contracts import SuggestionOutput
from .review_runtime.control import _persist_active_passage_failure, _restore_overall_checkpoint
from .review_runtime.model_input import _bounded_model_input
from .review_runtime.results import _project_persisted_result
from .role_definitions.common import finalize_roles
from .role_definitions.evidence_investigator import create_evidence_investigator_agent
from .role_definitions.fixed_review import fixed_analysis_variant, fixed_validator_variant
from .role_definitions.manager import create_manager_agent
from .role_definitions.review_analysis import create_review_analysis_agent
from .role_definitions.suggestion import create_suggestion_agent
from .role_definitions.validator import create_validator_agent
from .role_definitions.web_research import create_web_research_agent


def _build_agents(
    model: Any, sentence_input: dict[str, Any], context: SuggestionContext
) -> dict[str, Agent[SuggestionContext]]:
    """Wire role factories; each role owns its prompt/tools/output definition."""
    web = create_web_research_agent(model)
    evidence = create_evidence_investigator_agent(model)
    analysis = create_review_analysis_agent(model, sentence_input, context, evidence, web)
    if context.review_pipeline == "fixed_tlr":
        analysis = fixed_analysis_variant(analysis)
    suggestion = create_suggestion_agent(model, context, web)
    validator = create_validator_agent(model)
    assessment_validator = fixed_validator_variant(validator) if context.review_pipeline == "fixed_tlr" else validator
    manager = create_manager_agent(
        model, sentence_input, context, analysis, suggestion, validator, web,
        assessment_validator=assessment_validator,
    )
    if context.review_pipeline == "fixed_tlr":
        manager = manager.clone(
            instructions=manager.instructions + "\n本次为固定 TLR 资料管线：不要调度补充证据调查，固定资料耗尽后汇总范围内结果；执行失败保留 blocked。网络调查仅可用于已接受分析结果之后的修改建议，不用于补做一致性评审。",
            tools=[t for t in manager.tools if t.name != "research_web_context"],
        )
    return finalize_roles(
        {
            "manager": manager,
            "analysis": analysis,
            "evidence": evidence,
            "web": web,
            "suggestion": suggestion,
            "validator": validator,
        }
    )


async def _run_one_locked(
    *, settings: Any, request: Any, sentence_id: str, client: BackendClient
) -> SuggestionOutput:
    store = CheckpointStore(
        Path(settings.suggestion_checkpoint_dir), request.review_id, sentence_id
    )
    if store.data.get("checkpoint_error"):
        return SuggestionOutput(
            execution_status="blocked",
            review_id=request.review_id,
            sentence_id=sentence_id,
            error_code="checkpoint_json_unreadable",
            error_message="Original checkpoint is corrupt or has a different identity; preserved without overwriting or calling a model",
        )
    pipeline = getattr(request, "review_pipeline", None) or getattr(settings, "review_pipeline", "fixed_tlr")
    previous_binding = store.data.get("execution_binding") or {}
    if store.data.get("attempts") and previous_binding.get("review_pipeline", "full_investigation") != pipeline:
        # Do not mix conclusions obtained from different investigation scopes.
        # A separate review is required to switch an already-started analysis.
        return SuggestionOutput(execution_status="blocked", review_id=request.review_id,
            sentence_id=sentence_id, error_code="review_pipeline_changed",
            error_message="已有工作区属于另一条管线；请创建新的分析任务使用简化管线，不混用旧调查事实。")
    # A durable resume is allowed to retry a failed model task, but it must
    # eventually stop at a host-owned limit.  The first execution is not a
    # retry; review_model_retry_limit counts only subsequent attempts.  This
    # gate is deliberately before model construction, so exhausting retries
    # cannot consume another provider call or manufacture a semantic result.
    retry_limit = min(1, int(getattr(settings, "review_model_retry_limit", 1)))
    attempts = int(store.data.get("attempts", 0) or 0)
    workflow_status = str(store.data.get("workflow_status") or "pending")
    if attempts > 0 and workflow_status == "blocked" and attempts - 1 >= retry_limit:
        message = (
            f"Model task retry limit reached: {retry_limit} retries after the initial attempt. "
            "No further model call will be made; persisted facts remain available for inspection."
        )
        store.transition(
            "dispatch", "blocked", error_code="model_retry_limit_exceeded", error_message=message
        )
        output = SuggestionOutput(
            execution_status="blocked",
            attempt=attempts,
            attempt_id=store.data.get("attempt_id"),
            review_id=request.review_id,
            sentence_id=sentence_id,
            error_code="model_retry_limit_exceeded",
            error_message=message,
        )
        store.output(output)
        return output
    previous = store.data.get("latest_output") or {}
    if isinstance(previous, dict) and previous.get("error_code"):
        store.data["previous_attempt_error"] = {
            key: previous.get(key) for key in ("error_code", "error_message")}
    store.begin_attempt()
    supplemental_limit = min(
        int(getattr(settings, "review_supplemental_passage_limit", MAX_SUPPLEMENTAL_PASSAGES)),
        MAX_SUPPLEMENTAL_PASSAGES,
    )
    if pipeline == "fixed_tlr":
        supplemental_limit = 0
    investigator_turn_limit = min(
        int(getattr(settings, "review_passage_max_turns", MAX_EVIDENCE_INVESTIGATOR_TURNS)),
        MAX_EVIDENCE_INVESTIGATOR_TURNS,
    )
    store.data["execution_binding"] = {
        "worker_attempt_id": request.execution_attempt_id,
        "workflow_version": "sdk-material-review-durable-v7",
        "review_pipeline": pipeline,
        "model": settings.suggestion_model or settings.llm_model,
        "revision_budget": settings.suggestion_max_revisions,
        "model_retry_limit": retry_limit,
        "passage_turn_limit": investigator_turn_limit,
        "supplemental_passage_limit": supplemental_limit,
    }
    store._save()
    context = SuggestionContext(
        client=client,
        store=store,
        project_id=request.project_id,
        review_id=request.review_id,
        sentence_id=sentence_id,
        tenant_id=request.tenant_id,
        max_suggestion_revisions=settings.suggestion_max_revisions,
        model_name=getattr(settings, "suggestion_model", None)
        or getattr(settings, "llm_model", None)
        or "qwen35-9b",
        model_base_url=getattr(settings, "suggestion_base_url", None),
        model_api_key=getattr(settings, "suggestion_api_key", ""),
        model_context_window=getattr(settings, "suggestion_context_window", 16_384),
        model_safety_tokens=getattr(settings, "suggestion_context_safety_tokens", 512),
        model_health_timeout_seconds=getattr(
            settings, "suggestion_model_health_timeout_seconds", 4.0
        ),
        model_failure_limit=getattr(settings, "suggestion_model_failure_limit", 2),
        supplemental_passage_limit=supplemental_limit,
        passage_max_turns=investigator_turn_limit,
        review_pipeline=pipeline,
    )
    model = None
    model_client = None
    try:
        # Resolve the task binding once for this SDK execution. Credentials stay
        # exclusively in the existing backend vault/gateway, never checkpointed
        # or copied into worker environment variables. A configured connection
        # failure is a real execution error, not a reason to switch to Qwen.
        runtime = await client.get("/api/v1/model-config/tasks/review_analysis/runtime")
        if runtime.get("configured"):
            provider_window = runtime.get("context_window")
            window = (
                provider_window
                if isinstance(provider_window, int) and provider_window > 0
                else settings.suggestion_context_window
            )
            settings = settings.model_copy(
                update={
                    "suggestion_model": runtime["model"],
                    "suggestion_base_url": client.base_url + runtime["transport"],
                    "suggestion_api_key": "gateway",
                    # Runtime metadata is the SELECTED model's limit, not the old
                    # local Qwen default. Admission still intersects this with the
                    # freshly observed provider limit for every request.
                    "suggestion_context_window": window,
                    "suggestion_provider_max_output_tokens": runtime.get("max_output_tokens"),
                }
            )
            context.model_name = settings.suggestion_model
            context.model_base_url = settings.suggestion_base_url
            context.model_api_key = settings.suggestion_api_key
            context.model_context_window = window
        store.data["execution_binding"].update(
            model=context.model_name,
            model_context_window=context.model_context_window,
            model_config_runtime=runtime,
        )
        store._save()
        # Model setup is inside the durable error boundary.  A missing local
        # endpoint/tokenizer is an execution block that must be checkpointed,
        # not an uncaught exception that bypasses retry accounting.
        model, model_client = build_model(settings, store)
        selected_profile = profile_for(context.model_name)
        store.data["execution_binding"].update(
            model_family=selected_profile.family,
            continuation_limit=getattr(model, "continuation_limit", selected_profile.continuation_limit),
            profile_max_output_tokens=selected_profile.max_output_tokens,
            provider_max_output_tokens=getattr(model, "provider_max_output_tokens", None),
        )
        store._save()
        session_root = Path(settings.suggestion_session_db)
        session_root.parent.mkdir(parents=True, exist_ok=True)
        session = SQLiteSession(
            f"review-{request.review_id}-sentence-{sentence_id}-attempt-{store.data.get('attempts', 1)}",
            str(session_root),
        )
        workspace = await client.get(
            f"/api/v1/projects/{request.project_id}/reviews/{request.review_id}/workspace"
        )
        sentence = next(
            (
                item
                for item in workspace.get("sentences", [])
                if item.get("sentence_id") == sentence_id
            ),
            None,
        )
        if sentence is None:
            raise ValueError("sentence_not_found")
        prior_analysis = next(
            (
                task
                for task in workspace.get("tasks", [])
                if task.get("task_key") == f"analysis:{sentence_id}"
                and task.get("status") == "completed"
            ),
            None,
        )
        if (
            sentence.get("status") == "completed"
            and sentence.get("checks_finalized")
            and prior_analysis
        ):
            # Restore a REAL backend checkpoint, not a fabricated fallback result.
            scope = await client.get(
                f"/api/v1/projects/{request.project_id}/reviews/{request.review_id}"
                f"/sentences/{sentence_id}/investigation"
            )
            if scope.get("conclusions_complete") and (
                scope.get("can_stop_for_sufficient_evidence")
                or (
                    scope.get("passage_count")
                    and not scope.get("unfinished_passage_ids")
                    and not scope.get("mandatory_remaining_node_ids")
                    and not scope.get("blocked_passage_ids")
                )
            ):
                store.transition(
                    "review_analysis_verified", "completed", output=prior_analysis.get("output")
                )
        assessment = sentence.get("assessment") or {}
        _restore_overall_checkpoint(context, sentence)
        snapshot = workspace.get("snapshot") or {}
        run_config = snapshot.get("run_config") or {}
        context.bound_run_id = workspace.get("tlr_run_id") or snapshot.get("tlr_run_id", "")
        context.bound_source_node_id = workspace.get("requirement_node_id") or snapshot.get(
            "requirement_node_id", ""
        )
        selected_scope = workspace.get("scope") or snapshot.get("selected_scope") or {}
        context.bound_target_artifact_ids = tuple(
            selected_scope.get("target_artifact_ids") or run_config.get("target_artifact_ids", [])
        )
        context.bound_target_node_ids = tuple(
            selected_scope.get("target_node_ids")
            or selected_scope.get("selected_target_node_ids")
            or []
        )
        if assessment.get("finalized") and not assessment.get("suggestion_required"):
            output = await _project_persisted_result(context)
            store.output(output)
            return output
        # Identity and selected target membership stay in local RunContext.
        # Each specialist receives only its semantic per-turn workspace view.
        agents = _build_agents(model, {}, context)
        prompt = (
            "开始当前已保存语段的评审与建议工作流程。"
            "使用 SDK 工具完成管理 Agent 调度闭环，不调用旧后台 LLM。"
            "当前任务身份已在本地 Context 绑定，读取工具返回的权威阶段并调度 specialist。"
        )
        if store.stage_complete("review_analysis_verified") and not store.stage_complete(
            "overall_assessment_proposed"
        ):
            prompt += (
                " 本次恢复已有完整的检查点综合结论。"
                "不要调用 read_next_tlr_material、open_supplementary_material 或任何证据搜索工具。"
                "读取源语段、检查点及证据台账，直接调用 propose_review_assessment 创建整体提案，"
                "然后由管理 Agent 调度独立验证。"
            )
        with trace("TLR review suggestion SDK workflow", group_id=request.review_id):
            await Runner.run(
                agents["manager"],
                prompt,
                context=context,
                session=session,
                # The manager orchestrates the whole segment and therefore
                # has no small global turn budget.  Reading one SDS passage is
                # bounded inside the Evidence Investigator tool.
                max_turns=None,
                run_config=RunConfig(call_model_input_filter=_bounded_model_input),
            )
        output = await _project_persisted_result(context)
        store.output(output)
        return output
    except BackendOwnershipError:
        raise  # revoked worker cannot write a new blocked result into a newer attempt
    except ModelAdmissionBlocked as exc:
        await _persist_active_passage_failure(context, exc.code, str(exc))
        output = SuggestionOutput(
            execution_status="blocked",
            review_id=request.review_id,
            sentence_id=sentence_id,
            error_code=exc.code,
            error_message=str(exc)[:2000],
        )
        store.output(output)
        return output
    except ReviewDependencyError as exc:
        await _persist_active_passage_failure(context, "shared_dependency_unavailable", str(exc))
        store.output(
            SuggestionOutput(
                execution_status="blocked",
                review_id=request.review_id,
                sentence_id=sentence_id,
                error_code="shared_dependency_unavailable",
                error_message=str(exc)[:2000],
            )
        )
        raise  # durable executor interrupts; unattempted reviews stay unattempted
    except asyncio.CancelledError:
        await _persist_active_passage_failure(
            context, "worker_interrupted", "Worker stopped before this sentence finished"
        )
        store.output(
            SuggestionOutput(
                execution_status="blocked",
                review_id=request.review_id,
                sentence_id=sentence_id,
                error_code="worker_interrupted",
                error_message="Worker stopped before this sentence finished; persisted facts are retained",
            )
        )
        raise
    except OutputGuardrailTripwireTriggered as exc:
        await _persist_active_passage_failure(context, "output_guardrail_tripwire", str(exc))
        output = SuggestionOutput(
            execution_status="blocked",
            review_id=request.review_id,
            sentence_id=sentence_id,
            error_code="output_guardrail_tripwire",
            error_message=str(exc)[:2000],
        )
        store.output(output)
        return output
    except (AgentsException, APIError, HTTPError, OSError, RuntimeError, ValueError) as exc:
        terminal = store.data.get("terminal_tool_error") or {}
        code = terminal.get("error_code") or type(exc).__name__
        message = terminal.get("message") or str(exc)
        await _persist_active_passage_failure(context, code, message)
        output = SuggestionOutput(
            execution_status="blocked",
            review_id=request.review_id,
            sentence_id=sentence_id,
            error_code=code,
            error_message=message[:2000],
        )
        store.output(output)
        return output
    except Exception as exc:  # noqa: BLE001 -- isolate one review from an unexpected adapter error
        # A malformed provider payload, serialization error, or SDK adapter
        # regression must close this public attempt and let the batch continue
        # with other independent sentences.  No semantic result is fabricated.
        await _persist_active_passage_failure(context, "unhandled_agent_failure", str(exc))
        output = SuggestionOutput(
            execution_status="blocked",
            review_id=request.review_id,
            sentence_id=sentence_id,
            error_code="unhandled_agent_failure",
            error_message=f"{type(exc).__name__}: {str(exc)[:1900]}",
        )
        store.output(output)
        return output
    finally:
        if model_client is not None:
            await model_client.close()


async def run_one_suggestion(
    *, settings: Any, request: Any, sentence_id: str, client: BackendClient
) -> SuggestionOutput:
    # Native cross-process file lock protects JSON and SQLite sessions on the
    # shared worker volume. Backend transaction fencing remains authoritative.
    root = Path(settings.suggestion_checkpoint_dir).resolve()
    path = (root / request.review_id / f"{sentence_id}.json").resolve()
    if not path.is_relative_to(root):
        raise ValueError("checkpoint path outside configured directory")
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(path) + ".lock", timeout=0)
    try:
        with lock:
            return await _run_one_locked(
                settings=settings, request=request, sentence_id=sentence_id, client=client
            )
    except FileLockTimeout:
        raise RuntimeError("sentence_already_running_in_another_worker") from None
