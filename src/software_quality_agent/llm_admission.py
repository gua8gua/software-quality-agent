"""Fail-closed admission checks for model calls and credential-isolated gateways.

The Agents SDK owns the model/tool loop.  This module owns the host decision
that must happen *before* that loop asks a provider for another response:
observe the provider/tokenizer state, decide whether the request fits, compact
the model-facing transcript once, or abandon the current work item.  It never
changes max tokens, retries a model request, or creates a semantic result.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import httpx

from .execution_errors import ReviewDependencyError, dependency_failure


class ModelAdmissionBlocked(RuntimeError):
    """The current work item cannot safely issue another model request."""

    def __init__(self, code: str, message: str, *, state: dict[str, Any] | None = None):
        self.code = code
        self.state = state or {}
        super().__init__(message)


@dataclass(frozen=True)
class AdmissionDecision:
    action: Literal["allow", "compress", "abandon"]
    health: str
    reason: str
    input_tokens: int | None
    context_window: int
    output_reserve: int | None
    safety_tokens: int
    compressed: bool
    server_context_window: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "health": self.health,
            "reason": self.reason,
            "input_tokens": self.input_tokens,
            "context_window": self.context_window,
            "output_reserve": self.output_reserve,
            "output_limit_mode": "provider_default" if self.output_reserve is None else "request_limit",
            "available_output_tokens": (max(0, self.context_window - self.input_tokens - self.safety_tokens)
                                        if self.input_tokens is not None else None),
            "safety_tokens": self.safety_tokens,
            "compressed": self.compressed,
            "server_context_window": self.server_context_window,
        }


class ModelAdmissionController:
    """Observe one attempt's model state without silently retrying it."""

    def __init__(self, *, store: Any, base_url: str | None, api_key: str,
                 model: str, context_window: int, safety_tokens: int,
                 health_timeout_seconds: float = 4.0,
                 failure_limit: int = 2):
        self.store = store
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key
        self.model = model
        self.context_window = context_window
        self.safety_tokens = safety_tokens
        self.health_timeout_seconds = health_timeout_seconds
        self.failure_limit = failure_limit

    def _recent_failure_streak(self) -> tuple[int, str | None]:
        calls = self.store.data.get("model_calls", [])
        streak = 0
        last_code: str | None = None
        for call in reversed(calls):
            if call.get("status") != "blocked":
                break
            streak += 1
            last_code = str(call.get("error_code") or "model_call_failed")
        persisted = int(self.store.data.get("model_failure_streak", 0) or 0)
        return max(streak, persisted), last_code

    def _record(self, decision: AdmissionDecision, *, agent: str,
                attempted_text_chars: int) -> None:
        record = {"agent": agent, "at": datetime.now(UTC).isoformat(),
                  "attempted_text_chars": attempted_text_chars, **decision.as_dict()}
        self.store.data.setdefault("llm_admission", []).append(record)
        # This is an operator-facing state view, not hidden model reasoning.
        self.store.data["llm_state"] = {**record, "model": self.model,
                                        "base_url_configured": bool(self.base_url)}
        self.store._save()

    async def _tokenize(self, payload: dict) -> tuple[int, int | None, str]:
        if not self.base_url:
            raise ModelAdmissionBlocked("model_preflight_unavailable", "Model admission tokenizer endpoint is not configured")
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        root = self.base_url[:-3].rstrip('/') if self.base_url.endswith('/v1') else self.base_url
        urls = [f"{root}/tokenize"]
        last_error: Exception | None = None
        async with httpx.AsyncClient(timeout=self.health_timeout_seconds) as client:
            for url in urls:
                try:
                    # vLLM TokenizeChatRequest uses the SAME tokenizer/chat
                    # template as inference, including tools and thinking mode.
                    body = {key: payload[key] for key in ("messages", "tools", "chat_template_kwargs", "tool_choice", "response_format") if key in payload}
                    body.update(model=self.model, add_generation_prompt=True)
                    response = await client.post(url, headers=headers, json=body)
                    if response.status_code == 404 and url != urls[-1]:
                        continue
                    response.raise_for_status()
                    payload = response.json()
                    tokens = payload.get("count")
                    if tokens is None and isinstance(payload.get("tokens"), list):
                        tokens = len(payload["tokens"])
                    if not isinstance(tokens, int) or tokens < 0:
                        raise ValueError("tokenizer response has no integer count")
                    server_window = payload.get("max_model_len")
                    server_window = server_window if isinstance(server_window, int) else None
                    self.store.data["tokenizer_status"] = {
                        key: payload.get(key) for key in ("count_source", "tokenizer_revision", "billing_count_authority")
                        if payload.get(key) is not None}
                    return tokens, server_window, "ready"
                except (httpx.HTTPError, ValueError) as exc:
                    failure = dependency_failure(exc, "model")
                    if failure:
                        raise failure from exc
                    last_error = exc
        raise ModelAdmissionBlocked(
            "model_preflight_unavailable",
            f"model tokenizer/health preflight failed: {last_error}",
        )

    async def check(self, *, payload: dict, output_reserve: int | None, compressed: bool,
                    agent: str) -> AdmissionDecision:
        text = json.dumps(payload, ensure_ascii=False, default=str)
        streak, last_code = self._recent_failure_streak()
        preflight_streak = int(self.store.data.get("model_preflight_failure_streak", 0) or 0)
        if preflight_streak >= self.failure_limit:
            decision = AdmissionDecision(
                "abandon", "unavailable", "preflight_failure_circuit_open",
                None, self.context_window, output_reserve, self.safety_tokens,
                compressed)
            self._record(decision, agent=agent, attempted_text_chars=len(text))
            raise ModelAdmissionBlocked(
                "model_preflight_circuit_open",
                f"model preflight admission closed after {preflight_streak} failures",
                state=decision.as_dict(),
            )
        if streak >= self.failure_limit:
            decision = AdmissionDecision(
                "abandon", "failed", "consecutive_model_failures_exceeded",
                None, self.context_window, output_reserve, self.safety_tokens,
                compressed)
            self._record(decision, agent=agent, attempted_text_chars=len(text))
            raise ModelAdmissionBlocked(
                "model_failure_circuit_open",
                f"model call admission closed after {streak} consecutive failures ({last_code})",
                state=decision.as_dict(),
            )

        try:
            tokens, server_window, health = await self._tokenize(payload)
            self.store.data["model_preflight_failure_streak"] = 0
        except ReviewDependencyError:
            decision = AdmissionDecision(
                "abandon", "unavailable", "shared_model_dependency_unavailable", None,
                self.context_window, output_reserve, self.safety_tokens, compressed)
            self._record(decision, agent=agent, attempted_text_chars=len(text))
            raise
        except ModelAdmissionBlocked:
            streak = int(self.store.data.get("model_preflight_failure_streak", 0) or 0) + 1
            self.store.data["model_preflight_failure_streak"] = streak
            decision = AdmissionDecision(
                "abandon", "unavailable", "model_preflight_unavailable", None,
                self.context_window, output_reserve, self.safety_tokens, compressed)
            self._record(decision, agent=agent, attempted_text_chars=len(text))
            self.store.data["llm_state"]["preflight_failure_streak"] = streak
            self.store._save()
            raise
        effective_window = min(self.context_window, server_window or self.context_window)
        # With no request output limit, this is INPUT admission only. The
        # provider owns its default/physical generation limits; we retain
        # safety headroom but cannot promise its response will never truncate.
        # The response guard records truncation as an execution failure.
        reserved = tokens + (output_reserve if output_reserve is not None else 0) + self.safety_tokens
        if reserved <= effective_window:
            decision = AdmissionDecision(
                "allow", health, "budget_fits", tokens, effective_window,
                output_reserve, self.safety_tokens, compressed, server_window)
            self._record(decision, agent=agent, attempted_text_chars=len(text))
            return decision

        action: Literal["compress", "abandon"] = "abandon" if compressed else "compress"
        decision = AdmissionDecision(
            action, health, "context_budget_exceeded", tokens, effective_window,
            output_reserve, self.safety_tokens, compressed, server_window)
        self._record(decision, agent=agent, attempted_text_chars=len(text))
        if action == "compress":
            return decision
        raise ModelAdmissionBlocked(
            "context_budget_admission_blocked",
            f"model request requires {reserved} tokens but budget is {effective_window}",
            state=decision.as_dict(),
        )


def model_input_text(input_items: list[Any], instructions: str | None) -> str:
    """Stable, conservative representation used only for tokenizer preflight."""
    return json.dumps({"instructions": instructions or "", "input": input_items},
                      ensure_ascii=False, default=str, separators=(",", ":"))


def compact_authoritative_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Make a model-facing view smaller while retaining IDs/statuses.

    Full canonical text and evidence remain available through paginated tools;
    this function never edits the backend workspace or canonical source.
    """
    compacted = dict(snapshot)
    # Keep current source/passages verbatim. If those alone cannot fit, block;
    # never present a prefix as the complete natural-language requirement.
    compacted["all_checks"] = [
        {**{key: row.get(key) for key in ("check_id", "ordinal", "category", "status")},
         "details_omitted": True, "read_tool": "get_review_segment", "check_offset": index}
        for index, row in enumerate(compacted.get("all_checks", []))
    ]
    compacted["all_checks_compacted"] = True
    compacted["saved_evidence_associations"] = [
        {key: row.get(key) for key in ("evidence_id", "check_id", "design_node_id", "relation", "candidate_id")}
        for row in compacted.get("saved_evidence_associations", [])
    ]
    # ``workflow_state`` is the resumable business ledger.  Keep every
    # identity/status/range/evidence ID, but trim repeated prose fields.  The
    # complete values remain in the checkpoint/workspace and are addressable
    # through the normal read tools; this function never invents a summary.
    state = compacted.get("workflow_state")
    if isinstance(state, dict):
        state = dict(state)
        checks = []
        for index, row in enumerate(state.get("check_ledger", [])):
            if not isinstance(row, dict):
                continue
            view = {key: row.get(key) for key in (
                "check_id", "ordinal", "category", "status") if key in row}
            for key in ("statement", "source_quote", "note"):
                if key in row:
                    text = str(row.get(key) or "")
                    view[key] = text[:600]
                    if len(text) > 600:
                        view[f"{key}_truncated"] = True
            if any(key in row and len(str(row.get(key) or "")) > 600
                   for key in ("statement", "source_quote", "note")):
                view["read_tool"] = "get_review_segment"
                view["check_offset"] = index
            checks.append(view)
        state["check_ledger"] = checks
        evidence = []
        for row in state.get("evidence_ledger", []):
            if not isinstance(row, dict):
                continue
            view = {key: row.get(key) for key in (
                "evidence_id", "check_id", "passage_id", "design_node_id", "candidate_id",
                "relation", "validation_status", "start_offset", "end_offset",
                "exact_quote_length", "quote_sha256", "quote_read_tool") if key in row}
            quote = row.get("exact_quote")
            if quote is not None:
                quote = str(quote)
                view["exact_quote"] = quote[:1200]
                if len(quote) > 1200:
                    view["exact_quote_truncated"] = True
                    view["quote_read_tool"] = row.get("quote_read_tool") or "get_review_segment"
            evidence.append(view)
        state["evidence_ledger"] = evidence
        passages = []
        for row in state.get("passage_ledger", []):
            if not isinstance(row, dict):
                continue
            view = dict(row)
            message = view.get("error_message")
            if message is not None:
                message = str(message)
                view["error_message"] = message[:1200]
                if len(message) > 1200:
                    view["error_message_truncated"] = True
            passages.append(view)
        state["passage_ledger"] = passages
        state["compaction_rule"] = (
            "此处保留真实 ID、状态、范围、逐字证据前缀和错误状态。被截短的文本用 checkpoint/工作区工具读取，不推断省略内容。"
        )
        compacted["workflow_state"] = state
    compacted["compaction_instruction"] = (
        "本次模型调用前已压缩上下文。workflow_state 是可恢复业务台账，不是隐藏推理摘要。不要推断省略文本；使用真实分页工具，保留返回的 ID、状态、范围、错误和逐字证据。"
    )
    return compacted
