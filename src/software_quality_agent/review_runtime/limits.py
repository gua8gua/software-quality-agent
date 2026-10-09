"""Durable stage retry budgets around the SDK Runner."""

from agents import ModelBehaviorError


def fail(store, code, message):
    store.data["terminal_tool_error"] = {"error_code": code, "message": message}
    store._save()
    raise ModelBehaviorError(f"{code}: {message}")


def begin_specialist(store, name):
    cycles = store.data.setdefault("workflow_cycles", {})
    kinds = {"run_review_analysis": "assessment", "draft_modification_suggestion": "suggestion"}
    validations = {"validate_segment_assessment": "assessment", "validate_modification_suggestion": "suggestion"}
    kind = kinds.get(name) or validations.get(name)
    if kind:
        state = cycles.setdefault(kind, {"runs": 0, "validations": 0})
        if name in kinds:
            if state["runs"] >= 2:
                fail(store, "stage_retry_limit_exceeded", "当前语段的这一阶段已经执行了首次处理和一次修订重试，预算已用完。已保存的分析、证据和验证理由保留，本语段以执行异常结束，批次继续处理下一语段。")
            state["runs"] += 1
        else:
            # A restored proposal/draft may be ready for its first validation.
            state["runs"] = max(1, state["runs"])
            if state["validations"] >= state["runs"]:
                fail(store, "stage_retry_limit_exceeded", "当前版本已经进行过一次验证。请根据已保存的中文验证反馈完成剩余的一次修订，再验证修订版本。两轮均已使用时，本语段以执行异常结束。")
            state["validations"] += 1
    store.data["specialist_activity"] = {
        "tool": name,
    }
    store._save()
