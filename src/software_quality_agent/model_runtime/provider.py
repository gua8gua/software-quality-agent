"""OpenAI-compatible transport adapter used by the official Agents SDK Runner."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

from agents import ModelBehaviorError
from agents.models.interface import ModelResponse
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from openai import AsyncOpenAI, DefaultAsyncHttpxClient

from ..execution_errors import dependency_failure
from ..llm_admission import ModelAdmissionBlocked, ModelAdmissionController
from ..review_runtime.checkpoint import CheckpointStore
from .config import ModelTransportConfig


class ObservedChatCompletionsModel(OpenAIChatCompletionsModel):
    """Official SDK adapter with public diagnostics and bounded continuation.

    A provider ``finish_reason=length`` is not a semantic answer.  When a
    partial public response exists, it is appended to the next model input
    with an explicit continuation instruction. Runner still owns tool calls.
    """

    def __init__(self, *, store: CheckpointStore, continuation_limit: int = 3, **kwargs):
        super().__init__(**kwargs)
        self.store = store
        self.continuation_limit = continuation_limit

    def _start_record(self) -> dict[str, Any]:
        calls = self.store.data.setdefault("model_calls", [])
        record = {
            "at": datetime.now(UTC).isoformat(),
            "agent": self.store.data.get("current_model_agent"),
            "status": "running",
            "continuation_of": self.store.data.get("active_model_call_id"),
            "continuation_index": int(self.store.data.get("truncation_continuations", 0) or 0),
        }
        calls.append(record)
        self.store.data["active_model_call_id"] = len(calls) - 1
        self.store._save()
        return record

    @staticmethod
    def _finish_reason(record: dict[str, Any]) -> str | None:
        reasons = (record.get("provider_response") or {}).get("finish_reasons") or []
        return reasons[0] if reasons else None

    @staticmethod
    def _continuation_input(original: Any, result: ModelResponse) -> list[dict[str, Any]]:
        items = list(original) if isinstance(original, list) else [{"role": "user", "content": original}]
        items.extend(item.model_dump(mode="json") for item in result.output if item.type != "reasoning")
        items.append({
            "role": "user",
            "content": (
                "上一次模型输出因达到本次输出预算而中断。请从刚才的最后位置继续，"
                "不要重复已经输出的文字；如果正在生成工具调用，请重新发出完整、合法的工具调用，"
                "不要执行或解释不完整的 JSON。"
            ),
        })
        return items

    async def get_response(self, system_instructions, input, model_settings, tools,
                           output_schema, handoffs, tracing, previous_response_id=None,
                           conversation_id=None, prompt=None):
        current_input = input
        for continuation in range(self.continuation_limit + 1):
            record = self._start_record()
            try:
                result = await super().get_response(
                    system_instructions, current_input, model_settings, tools,
                    output_schema, handoffs, tracing, previous_response_id,
                    conversation_id, prompt,
                )
                public = [item.model_dump(mode="json") for item in result.output if item.type != "reasoning"]
                record.update(status="completed", output=public, usage={
                    key: getattr(result.usage, key)
                    for key in ("requests", "input_tokens", "output_tokens", "total_tokens")
                }, response_id=result.response_id)
                if self._finish_reason(record) == "length":
                    if continuation >= self.continuation_limit:
                        raise ModelBehaviorError("provider_output_truncated:continuation_limit_reached")
                    self.store.data["truncation_continuations"] = int(
                        self.store.data.get("truncation_continuations", 0)
                    ) + 1
                    self.store._save()
                    current_input = self._continuation_input(current_input, result)
                    continue
                actionable = any(
                    item.get("type") == "function_call"
                    or (item.get("type") == "message" and any(
                        part.get("text", "").strip() or part.get("type") == "refusal"
                        for part in item.get("content", [])
                    ))
                    for item in public
                )
                if not actionable:
                    raise ModelBehaviorError("provider_response_has_no_public_text_or_tool_call")
                self.store.data["model_failure_streak"] = 0
                return result
            except asyncio.CancelledError:
                record.update(status="blocked", error_code="worker_interrupted",
                              error_message="Worker stopped during this model call")
                raise
            except Exception as exc:
                cause = exc
                while cause is not None:
                    if isinstance(cause, ModelAdmissionBlocked):
                        record.update(status="blocked", error_code=cause.code,
                                      error_message=str(cause)[:2000])
                        raise cause
                    cause = cause.__cause__
                record.update(status="blocked", error_code=type(exc).__name__,
                              error_message=str(exc)[:2000])
                self.store.data["model_failure_streak"] = int(
                    self.store.data.get("model_failure_streak", 0) or 0
                ) + 1
                failure = dependency_failure(exc, "model")
                if failure:
                    raise failure from exc
                raise
            finally:
                record["finished_at"] = datetime.now(UTC).isoformat()
                self.store._save()


async def _observe_provider_request(store: CheckpointStore, request: Any) -> None:
    if not request.url.path.endswith("/chat/completions"):
        return
    calls = store.data.get("model_calls", [])
    if not calls or calls[-1].get("status") != "running":
        return
    try:
        payload = json.loads(request.content)
    except (ValueError, TypeError):
        return
    if not isinstance(payload, dict):
        return
    public = {key: payload[key] for key in (
        "model", "tool_choice", "parallel_tool_calls", "temperature", "max_tokens",
        "max_completion_tokens", "response_format", "chat_template_kwargs", "tools"
    ) if key in payload}
    public["messages"] = [{key: message[key] for key in (
        "role", "content", "tool_calls", "tool_call_id", "name"
    ) if key in message} for message in payload.get("messages", []) if isinstance(message, dict)]
    calls[-1]["provider_request"] = public
    store._save()


async def _observe_provider_response(store: CheckpointStore, response: Any) -> None:
    if (not response.request.url.path.endswith("/chat/completions")
            or response.headers.get("content-type", "").split(";", 1)[0] != "application/json"):
        return
    await response.aread()
    try:
        payload = response.json()
    except ValueError:
        return
    calls = store.data.get("model_calls", [])
    if not calls or calls[-1].get("status") != "running" or not isinstance(payload, dict):
        return
    choices = []
    for choice in payload.get("choices", []):
        message = choice.get("message") or {}
        choices.append({"index": choice.get("index"), "finish_reason": choice.get("finish_reason"),
                        "message": {key: message.get(key) for key in ("content", "tool_calls", "refusal")}})
    calls[-1]["provider_response"] = {"status_code": response.status_code,
        "response_id": payload.get("id"),
        "finish_reasons": [choice["finish_reason"] for choice in choices],
        "usage": payload.get("usage"), "choices": choices}
    store._save()


def build_model(settings: Any, store: CheckpointStore) -> tuple[Any, AsyncOpenAI | None]:
    transport = ModelTransportConfig.from_settings(settings)
    if not transport.base_url:
        raise ModelAdmissionBlocked("model_not_configured", "Review requires a configured model and admission tokenizer endpoint")
    model_name = transport.model
    async def observe(response):
        await _observe_provider_response(store, response)

    async def observe_request(request):
        await _observe_provider_request(store, request)
        if request.url.path.endswith("/chat/completions"):
            payload = json.loads(request.content)
            controller = ModelAdmissionController(store=store, base_url=transport.base_url,
                api_key=transport.api_key, model=model_name,
                context_window=transport.context_window, safety_tokens=transport.safety_tokens,
                health_timeout_seconds=transport.health_timeout_seconds)
            await controller.check(payload=payload,
                output_reserve=payload.get("max_completion_tokens", payload.get("max_tokens")),
                compressed=True, agent=store.data.get("current_model_agent") or "SDK adapter")

    client = AsyncOpenAI(base_url=transport.base_url, api_key=transport.api_key,
        timeout=transport.call_timeout_seconds, max_retries=0,
        http_client=DefaultAsyncHttpxClient(timeout=transport.call_timeout_seconds,
            event_hooks={"request": [observe_request], "response": [observe]}))
    adapter = ObservedChatCompletionsModel(store=store, model=model_name, openai_client=client,
        continuation_limit=transport.continuation_limit)
    adapter.provider_max_output_tokens = transport.provider_max_output_tokens
    adapter.provider_context_window = transport.context_window
    return adapter, client
