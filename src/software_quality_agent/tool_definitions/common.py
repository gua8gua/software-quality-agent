"""common definitions for the SDK review workflow."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import uuid4

from agents import ModelBehaviorError, RunContextWrapper

from ..execution_errors import ReviewDependencyError
from ..review_runtime.context import BackendHTTPError, BackendOwnershipError, SuggestionContext

_REPLAY_TRACKED_AGENTS = {
    "review analysis agent",
    "evidence investigator agent",
    "review and suggestion validator agent",
    "suggestion agent",
}
_REPLAY_TRACKED_READS = {
    "get_canonical_node",
    "get_node_structure",
    "read_document_content",
    "read_fixed_material_content",
    "get_document_neighbors",
    "get_node_summary",
}


def _tracks_canonical_replay(context: SuggestionContext) -> bool:
    return context.store.data.get("current_model_agent") in _REPLAY_TRACKED_AGENTS

TOOL_OUTPUT_INLINE_CHARS = 1000


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _runtime(ctx: RunContextWrapper[Any]) -> SuggestionContext:
    """Return the process context shared by parent and nested SDK agents."""
    value = ctx.context
    if isinstance(value, SuggestionContext):
        return value
    raise TypeError("suggestion workflow context is not available")


async def _workspace(context: SuggestionContext) -> dict[str, Any]:
    return await context.client.get(
        f"/api/v1/projects/{context.project_id}/reviews/{context.review_id}/workspace"
    )


def _review_phase(state: dict[str, Any], sentence: dict[str, Any] | None = None,
                  *, pipeline: str = "full_investigation") -> tuple[str, str]:
    """Map persisted facts to one unambiguous model-facing workflow phase.

    This is a transport/progress label, not a semantic conclusion.  The
    backend remains authoritative for statuses and evidence; the label only
    tells the SDK specialist which next protocol action is legal.
    """
    if not isinstance(sentence, dict):
        return "load_source_segment", "用 get_review_segment 读取完整源语段。"
    if not sentence.get("checks_finalized"):
        return "extract_checks", (
            "读取完整源原文，仅创建原文明示的检查点，然后将全部真实 check_id 提交 finalize_review_checks。"
        )
    if state.get("can_stop_for_sufficient_evidence"):
        return "conclude_checks", (
            "全部检查点已有合法证据支持且无反证；保存综合结论，不再调查。历史异常保留，不把未完成资料改成 completed。"
        )
    if state.get("unfinished_passage_ids"):
        return "assess_current_passage", (
            "对当前资料段的每个检查点调用 assess_review_check，然后 finalize_review_passage。"
        )
    if state.get("mandatory_unattempted_node_ids", state.get("mandatory_remaining_node_ids")):
        return "select_mandatory_sds_passage", (
            "用 read_next_tlr_material 切换下一份高优先资料，再对全部检查点评估；不用挑选或填写候选 ID。"
        )
    if state.get("conclusions_complete"):
        return "propose_overall_assessment", (
            "基于已保存的检查点综合事实调用 propose_review_assessment。"
        )
    if pipeline == "fixed_tlr":
        if state.get("blocked_passage_ids") or not state.get("passage_count"):
            return "finish_incomplete", (
                "固定 TLR 资料已耗尽，但存在执行失败或没有可检查资料。调用 finish_review_incomplete 保存执行异常，不形成虚假语义结论。")
        return "conclude_checks", (
            "固定 TLR 资料已成功处理完；基于这些已保存事实提交每个检查点综合结论。证据不足仅指固定资料范围，不进行补充调查。")
    if not state.get("passage_count"):
        return "select_mandatory_sds_passage", (
            "用 read_next_tlr_material 打开下一份高优先 SDS 资料，再判断覆盖。"
        )
    return "supplementary_sds_search_or_conclude", (
        "检查点仍有缺口时按结构位置调查补充资料。blocked 资料已跳过，不重新评估。若执行失败造成无法可靠收敛，调用 finish_review_incomplete 记录局部失败并返回管理 Agent。"
    )


def _annotate_phase(raw: str, phase: str, next_action: str) -> str:
    """Add a small progress envelope without changing the persisted result."""
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return raw
    if not isinstance(value, dict):
        return raw
    value = {**value, "current_stage": phase, "next_required_action": next_action}
    return _dump(value)


def _annotate_tlr_priority(
    raw: str,
    *,
    current: bool,
    run_id: str,
    source_node_id: str | None = None,
    node_id: str | None = None,
) -> str:
    """Mark off-path TLR reads as low-priority investigation material.

    Reading is intentionally broader than the current review binding.  The
    marker prevents a specialist from mistaking an unconnected run/node for
    the mandatory current-TLR evidence without blocking useful discovery.
    """
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return raw
    if not isinstance(value, dict):
        return raw
    value = {
        **value,
        "investigation_priority": "current_tlr" if current else "low_unconnected_tlr",
        "read_scope": "current_review_tlr" if current else "unconnected_tlr_read_only",
        "read_run_id": run_id,
    }
    if source_node_id is not None:
        value["read_source_node_id"] = source_node_id
    if node_id is not None:
        value["read_node_id"] = node_id
    if not current:
        value["canonical_evidence"] = False
        value["candidate_binding_policy"] = "do_not_bind_foreign_candidate_to_current_review"
        value["instruction"] = (
            "此 TLR/Run/节点不属于当前评审高优先范围，可低优先级调查。返回的其他 TLR 判断不是当前需求证据。按真实 node_id 读 canonical 原文；用户选定目标范围内节点可在高优先调查后用 candidate_id=null 注册补充资料。不要复制其他源节点/Run 的候选绑定或检查点结论。"
        )
    return _dump(value)


def _set_review_phase(context: SuggestionContext, phase: str, next_action: str) -> None:
    """Persist the public protocol phase beside the durable checkpoint."""
    context.store.data["current_review_phase"] = phase
    context.store.data["current_review_next_action"] = next_action
    context.store._save()


async def _get(
    ctx: RunContextWrapper[SuggestionContext],
    name: str,
    path: str,
    params: dict[str, Any] | None = None,
) -> str:
    context: SuggestionContext = ctx.context
    arguments = {key: value for key, value in (params or {}).items() if value is not None}
    # Transport cache; explicit model reads are counted at the SDK boundary.
    if (
        name in _REPLAY_TRACKED_READS
        and _tracks_canonical_replay(context)
    ):
        revision = int(context.store.data.get("facts_revision", 0))
        cache_key = json.dumps(
            [name, path, arguments, revision],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        cache = context.store.data.setdefault("canonical_read_replays", {})
        cached = cache.get(cache_key)
        if cached is not None:
            return _dump(cached["result"])
    call_index = context.store.tool_call(name, {**arguments, "path": path})
    try:
        result = await context.client.get(path, arguments)
        context.store.tool_success(call_index, result)
        if (
            name in _REPLAY_TRACKED_READS
            and _tracks_canonical_replay(context)
        ):
            cache_key = json.dumps(
                [name, path, arguments, int(context.store.data.get("facts_revision", 0))],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            context.store.data.setdefault("canonical_read_replays", {})[cache_key] = {
                "result": result,
                "replay_count": 0,
            }
            context.store._save()
        return _dump(result)
    except Exception as exc:
        context.store.tool_error(name, str(exc))
        raise


async def _write(
    ctx: RunContextWrapper[SuggestionContext],
    name: str,
    method: str,
    path: str,
    payload: dict[str, Any],
) -> str:
    context: SuggestionContext = ctx.context
    arguments = {"method": method, "path": path, "payload": payload}
    if not context.store.guard_replayed_write(name, arguments):
        cached = context.store.replayed_write_output(name, arguments)
        if cached is not None:
            return _dump(cached)
        raise RuntimeError("terminal_tool_guard:replayed_state_change")
    call_index = context.store.tool_call(name, arguments)
    try:
        result = await context.client.write(method, path, payload)
        context.store.tool_success(call_index, result)
        return _dump(result)
    except Exception as exc:
        context.store.tool_error(name, str(exc))
        if (
            isinstance(exc, BackendHTTPError)
            and exc.status_code in {400, 422}
            and name in {"assess_review_passage", "assess_review_check", "finalize_review_passage"}
        ):
            passage_id = path.split("/passages/", 1)[1].split("/", 1)[0]
            return await _passage_failure(ctx, passage_id, name, "passage_assessment_rejected", exc)
        raise


async def _passage_failure(ctx, passage_id: str, tool_name: str, code: str, error: Exception) -> str:
    """Durable one-retry policy; let the SDK deliver correction feedback."""
    context = _runtime(ctx)
    # The backend records retries, so restarting the SDK session cannot reset
    # the allowance. A lost response can replay the same failure ID safely.
    result = await context.client.write(
        "POST",
        f"/api/v1/projects/{context.project_id}/reviews/{context.review_id}/passages/{passage_id}/error",
        {"error_code": code, "error_message": str(error)[:2000], "retryable": True,
         "failure_id": str(getattr(ctx, "tool_call_id", None) or uuid4())},
    )
    feedback = _tool_error_feedback(tool_name, error)
    retry = result.get("execution_status") == "retry_required"
    phase = "assess_current_passage" if retry else "select_next_sds_passage_or_conclude"
    instruction = (
        "上次操作未保存。依据下面错误原因修正当前资料的失败评估，再尝试一次；保留其他已成功的评估。"
        if retry else
        "本资料的重试已失败，错误已保存并跳过。不要再评估或完成它；调用 read_next_tlr_material 继续其他独立资料。"
    )
    if not retry and context.store.data.get("active_passage_id") == passage_id:
        context.store.data["active_passage_id"] = None
    context.store.data.setdefault("passage_failures", {})[passage_id] = {
        **result, "feedback": feedback, "instruction": instruction,
    }
    _set_review_phase(context, phase, instruction)
    return _dump({**result, "passage_error_persisted": True, "current_stage": phase,
                  "next_required_action": instruction, "feedback": feedback})


class SavedResultAddressError(ModelBehaviorError):
    """An invalid address into immutable facts cannot be repaired by paging on."""

    code = "saved_result_address_invalid"


def _tool_error_feedback(tool_name: str, error: Exception) -> str:
    """Turn identifier/scope failures into a precise next-action message.

    The SDK already sends tool failures back to the model.  This adds the
    domain distinction that a local model otherwise tends to miss: canonical
    node UUIDs and Docling refs are different identifiers, and saved-result
    call IDs must come from the current attempt's returned index.
    """
    message = str(error)[:2000]
    lowered = message.lower()
    if "terminal_tool_guard" in lowered or "stage_retry_limit_exceeded" in lowered:
        instruction = "程序已记录当前语段的执行终点。已有分析、证据和反馈保留，本次执行结束，批次继续下一个独立语段。"
    elif "supporting status requires" in lowered or "已满足状态需要" in message:
        instruction = "当前检查点的已满足判定缺少有效原文证据。请将已读取资料中的逐字引文绑定到此检查点，使用 supporting 或 context 关系，再说明累积满足依据并保存 supported 状态。"
    elif "counter evidence" in lowered:
        instruction = "当前检查点的矛盾判定缺少有效反证。请保存与此检查点对应的逐字原文引文及 counter 关系，在理由中解释具体冲突，再提交 contradicted 状态。"
    elif "opposed evidence" in lowered:
        instruction = "当前检查点同时具有支持证据和反对证据。请综合解释两类原文的适用条件，保存表达当前冲突的 uncertain 状态和具体中文理由。"
    elif "draft_iteration" in lowered or "draft already has" in lowered:
        instruction = "当前验证请求未对应可以验证的最新草稿。请通过 get_suggestion_workspace 读取最新草稿及已有反馈，准确使用该草稿的 iteration；已有反馈的版本进入修订流程，新版本保存后再验证。"
    elif "fingerprint" in lowered:
        instruction = "当前整体验证未对应最新提案。请通过 get_review_segment 读取最新整体提案和 proposal_fingerprint，将真实指纹原样用于 validate_review_assessment，并说明本版本的验证理由。"
    elif "quote" in lowered or "exact" in lowered or "引文" in message:
        instruction = "当前引文与已登记的原文或字符范围不一致。请从工具返回的原文中逐字复制所需句子，使用真实起止范围，准确绑定当前检查点和资料。"
    elif "invalid_tool_arguments" in lowered or "validation error" in lowered:
        instruction = "本次工具参数未通过结构校验。请按工具公开的参数定义填写必填字段、值类型和允许的枚举值，使用当前工作区返回的真实索引。"
    elif (
        "saved_tool_result" in lowered
        or "saved_result" in lowered
        or "field_path" in lowered
        or "call_id" in lowered
    ):
        instruction = "使用最新保存结果索引返回的真实 call_id、field_path。不把工具名当 ID，不编 UUID，不递增末尾游标，不使用其他尝试的调用。索引不可用时重新执行列出真实地址的分页读取。"
    elif tool_name in {"browse_document_structure", "read_document_content", "get_document_neighbors", "get_document_relations", "search_document_content", "read_table_structure", "open_supplementary_material"} or "结构位置" in message:
        instruction = "文档查询使用工具返回的 location，例如 设计文档1:/2/4。先用 list_document_branches 查文件，再用 browse_document_structure 看标题和子章节，原样复制位置。不用 UUID、Docling ref 或自行猜测的章节号。用户选定范围外只能读取上下文，不能写为当前证据。"
    elif "outside current agent sentence" in lowered:
        instruction = "只向当前语段写入证据和评估。读取 get_review_segment 并复制此语段真实 check_id，不使用其他语段检查点。"
    elif (
        "docling" in lowered
        or "ref" in lowered
        or "canonical" in lowered
        or ("node" in lowered and ("404" in lowered or "not found" in lowered))
    ):
        instruction = "文档原文按已返回的 location 查询，不把 Docling ref、标题编号当查询位置。高优先资料用 read_next_tlr_material 自动切换，不填写 node_id/candidate_id；额外资料先由结构查询确定 location，再交给 investigate_review_material。检查点和证据写入仅复制各自工具返回的索引。"
    elif (
        "candidate" in lowered
        or "source_node" in lowered
        or "target_node" in lowered
        or "outside" in lowered
        or "scope" in lowered
    ):
        instruction = "高优先资料通过 read_next_tlr_material 自动绑定当前 TLR。额外资料先查看结构标题和节点摘要，再用 investigate_review_material(location)；不要填写内部候选 ID。范围外原文只能作上下文，不能写为当前证据。"
    else:
        instruction = "阅读真实错误并修正工具参数，不重复同一无效请求。"
    return f"工具 {tool_name} 本次操作未完成，已有事实保持保存。{instruction}"


def _sdk_tool_failure(ctx: RunContextWrapper[Any], error: Exception) -> str:
    """Return human-readable repair feedback for an invalid tool call.

    The SDK feeds a returned failure string into the next model turn.  This is
    important for local models that confuse canonical UUIDs, Docling refs, or
    saved-result addresses.  The same exact failure is allowed two feedback
    turns; the third is durably terminal so an unbounded segment Runner cannot
    spin forever.  No semantic result is produced by this handler.
    """
    if isinstance(error, (BackendOwnershipError, ReviewDependencyError)):
        raise error
    context = _runtime(ctx)
    if isinstance(error, ModelBehaviorError):
        name = getattr(ctx, "tool_name", "sdk_tool")
        raw_arguments = getattr(ctx, "tool_arguments", None)
        context.store.tool_call(name, {"raw_sdk_arguments": raw_arguments})
        code = getattr(error, "code", "invalid_tool_arguments")
        feedback = _tool_error_feedback(name, error)
        fingerprint = hashlib.sha256(
            json.dumps([name, type(error).__name__, str(error)], ensure_ascii=False).encode()
        ).hexdigest()
        repeats = context.store.data.setdefault("tool_error_repeats", {})
        repeats[fingerprint] = int(repeats.get(fingerprint, 0)) + 1
        context.store.tool_error(name, f"{code}:{feedback}")
        context.store._save()
        if repeats[fingerprint] < 3:
            return feedback
        context.store.data["terminal_tool_error"] = {
            "tool": name,
            "error_code": "repeated_invalid_tool_arguments",
            "message": feedback[:2000],
            "raw_arguments": raw_arguments,
        }
        context.store._save()
        raise ModelBehaviorError(
            f"repeated_invalid_tool_arguments:{name}:same tool error repeated three times; stop and persist blocked"
        ) from error
    name = getattr(ctx, "tool_name", "sdk_tool")
    raw_arguments = getattr(ctx, "tool_arguments", None)
    feedback = _tool_error_feedback(name, error)
    # Repeated identical argument errors are bounded per attempt.  The first
    # responses give the model a concrete repair instruction; after three
    # repeats the specialist is blocked instead of spinning forever now that
    # the outer segment loop has no arbitrary turn ceiling.
    fingerprint = hashlib.sha256(
        json.dumps([name, type(error).__name__, str(error)], ensure_ascii=False).encode()
    ).hexdigest()
    repeats = context.store.data.setdefault("tool_error_repeats", {})
    repeats[fingerprint] = int(repeats.get(fingerprint, 0)) + 1
    context.store.tool_error(name, feedback)
    if repeats[fingerprint] >= 3:
        context.store.data["terminal_tool_error"] = {
            "tool": name,
            "error_code": "repeated_invalid_tool_arguments",
            "message": feedback[:2000],
            "raw_arguments": raw_arguments,
        }
        context.store._save()
        raise ModelBehaviorError(
            f"repeated_invalid_tool_arguments:{name}:same tool error repeated three times; stop and persist blocked"
        )
    context.store._save()
    return feedback


def _tool_decorator(**kwargs):
    from agents.decorators import tool
    from ..review_runtime.reading import finish_material_read, tool_allowed

    kwargs.setdefault("failure_error_function", _sdk_tool_failure)

    def decorate(function):
        decorated = tool(**kwargs)(function)
        original = decorated.on_invoke_tool
        enabled = decorated.is_enabled

        async def is_enabled(ctx, agent):
            import inspect
            value = enabled(ctx, agent) if callable(enabled) else enabled
            if inspect.isawaitable(value):
                value = await value
            return value and (not isinstance(ctx.context, SuggestionContext) or tool_allowed(ctx.context, decorated.name, agent.name))

        async def invoke(ctx, arguments):
            # Internal quote verification and nested registration are host
            # operations, not a second model-requested material read.
            explicit = getattr(ctx, "tool_name", decorated.name) == decorated.name
            if explicit and isinstance(ctx.context, SuggestionContext) and not tool_allowed(ctx.context, decorated.name):
                return _dump({"instruction": "本次验证的资料阅读已经结束。请根据当前保存的提案、证据和已读取材料直接提交验证结论，说明成立依据或具体信息缺口。"})
            result = await original(ctx, arguments)
            if explicit and isinstance(ctx.context, SuggestionContext):
                try:
                    params = json.loads(arguments)
                except (TypeError, ValueError):
                    return result
                result = finish_material_read(ctx.context, decorated.name, params, result)
            return result

        decorated.on_invoke_tool = invoke
        decorated.is_enabled = is_enabled
        return decorated

    return decorate
