"""Typed dependency boundaries; no real providers, retries, or semantic results."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError
from test_material_workflow import BackendFixture

from software_quality_agent.config import Settings
from software_quality_agent.execution_errors import ReviewDependencyError, dependency_failure
from software_quality_agent.review_jobs import LeaseRetry, execute_batch
from software_quality_agent.review_runtime.context import BackendClient, BackendHTTPError
from software_quality_agent.review_runtime.checkpoint import CheckpointStore
from software_quality_agent.review_runtime.model import ObservedChatCompletionsModel
from software_quality_agent.review_runtime.control import _fatal_nested_failure, _nested_failure
from software_quality_agent.suggestion_workflow import _run_one_locked


class DependencyTests(unittest.IsolatedAsyncioTestCase):
    def test_official_status_and_transport_types_not_message_keywords_define_scope(self):
        request = httpx.Request("POST", "http://local-model/v1/chat/completions")
        for status in (401, 403, 404, 429, 502, 503, 504):
            error = APIStatusError("provider error", response=httpx.Response(status, request=request), body=None)
            self.assertIsInstance(dependency_failure(error, "model"), ReviewDependencyError)
        for status in (400, 409, 422, 500):
            error = APIStatusError("provider error", response=httpx.Response(status, request=request), body=None)
            self.assertIsNone(dependency_failure(error, "model"))
        self.assertIsNone(dependency_failure(APITimeoutError(request=request), "model"))
        self.assertIsNone(dependency_failure(httpx.ReadTimeout("slow request"), "backend"))
        self.assertIsNone(dependency_failure(RuntimeError("provider unavailable"), "model"))
        self.assertIsNotNone(dependency_failure(APIConnectionError(request=request), "model"))

    async def test_backend_target_not_found_stays_local_but_connection_and_access_failures_escape(self):
        client = BackendClient("http://backend", "local")
        await client.close()
        async def response(request):
            if request.url.path == "/offline":
                raise httpx.ConnectError("backend unreachable", request=request)
            return httpx.Response(404 if request.url.path == "/missing-node" else 503)
        client.http = httpx.AsyncClient(transport=httpx.MockTransport(response))
        self.addAsyncCleanup(client.close)
        with self.assertRaises(BackendHTTPError):
            await client.get("/missing-node")
        for operation in (client.get("/offline"), client.write("POST", "/unavailable", {})):
            with self.assertRaises(ReviewDependencyError):
                await operation

    async def test_model_connection_failure_keeps_official_cause_and_does_not_become_an_agent_result(self):
        with tempfile.TemporaryDirectory() as directory:
            store = CheckpointStore(Path(directory), "r", "s")
            error = APIConnectionError(request=httpx.Request("POST", "http://local-model"))
            model = ObservedChatCompletionsModel(store=store, model="unused", openai_client=None)
            with patch("agents.models.openai_chatcompletions.OpenAIChatCompletionsModel.get_response",
                       new=AsyncMock(side_effect=error)), self.assertRaises(ReviewDependencyError) as caught:
                await model.get_response()
            self.assertIs(caught.exception.__cause__, error)
            record = store.data["model_calls"][0]
            self.assertEqual(record["status"], "blocked")
            self.assertEqual(record["error_code"], "APIConnectionError")
            self.assertIsNone(store.data.get("latest_output"))

    async def test_dependency_failure_is_saved_locally_even_when_backend_error_write_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = SimpleNamespace(suggestion_checkpoint_dir=directory,
                suggestion_session_db=str(Path(directory) / "session.sqlite"), suggestion_model="unused",
                llm_model="unused", suggestion_max_revisions=3, suggestion_max_turns=24)
            request = SimpleNamespace(project_id="p", review_id="r", tenant_id="local", execution_attempt_id="attempt")
            client = BackendFixture()
            error = ReviewDependencyError("backend", httpx.ConnectError("connection lost"))
            client.write = AsyncMock(side_effect=error)
            async def unavailable(*args, **kwargs):
                kwargs["context"].store.data["active_passage_id"] = "passage"
                raise error
            with patch("software_quality_agent.suggestion_workflow._model_for", return_value=("unused", None)), patch(
                "software_quality_agent.suggestion_workflow.Runner.run", new=unavailable,
            ), self.assertRaises(ReviewDependencyError) as caught:
                await _run_one_locked(settings=settings, request=request, sentence_id="s", client=client)
            self.assertIs(caught.exception, error)
            saved = CheckpointStore(Path(directory), "r", "s").data
            self.assertEqual(saved["latest_output"]["error_code"], "shared_dependency_unavailable")
            self.assertEqual(saved["latest_output"]["execution_status"], "blocked")
            self.assertTrue(any(e["name"] == "persist_active_passage_failure" for e in saved["tool_errors"]))
            self.assertEqual(saved["latest_output"]["suggestion_text"], "")

    def test_required_specialist_does_not_erase_typed_dependency_failure(self):
        error = ReviewDependencyError("model", httpx.ConnectError("offline"))
        for handler in (_fatal_nested_failure, _nested_failure):
            with self.assertRaises(ReviewDependencyError) as caught:
                handler(SimpleNamespace(context=None), error)
            self.assertIs(caught.exception, error)
        self.assertIn("Nested agent execution failed", _nested_failure(
            SimpleNamespace(context=None), ValueError("optional external page unavailable")))
        self.assertIsNone(LeaseRetry().get_retry_decision(exception=error, job=None))

    async def test_shared_dependency_interrupts_only_current_execution_unattempted_reviews_are_untouched(self):
        await self._check_batch_outcome(shared=True)

    async def test_independent_model_failure_still_allows_next_review_to_finish(self):
        await self._check_batch_outcome(shared=False)

    async def _check_batch_outcome(self, *, shared):
        settings = Settings(_env_file=None, review_queue_dsn="")
        batch = {"status": "pending", "review_ids": ["first", "second"],
                 "reviews": [{"review_id": "first"}, {"review_id": "second"}]}
        client = AsyncMock(base_url="http://backend")
        client.get.side_effect = [batch, {**batch, "finished_count": 2, "status_counts": {}}]
        response = Mock()
        response.json.return_value = batch
        client.http.post.return_value = response
        async def write(method, path, payload, params=None):
            if path.endswith("/heartbeat"):
                return {"lease_seconds": 300}
            if path.endswith("/begin-review"):
                return {"attempt": 1, "attempt_id": payload["review_id"]}
            return {}
        client.write.side_effect = write
        error = (ReviewDependencyError("model", httpx.ConnectError("offline")) if shared
                 else RuntimeError("invalid model JSON"))
        execute = AsyncMock(side_effect=[error, {"status": "completed"}])
        with patch("software_quality_agent.review_jobs.BackendClient", return_value=client), patch(
            "software_quality_agent.review_jobs.run_review_suggestions", new=execute,
        ):
            if shared:
                with self.assertRaises(ReviewDependencyError):
                    await execute_batch(settings, {"project_id": "p", "batch_id": "b", "tenant_id": "local"})
            else:
                await execute_batch(settings, {"project_id": "p", "batch_id": "b", "tenant_id": "local"})
        writes = client.write.await_args_list
        starts = [call.args[2]["review_id"] for call in writes if call.args[1].endswith("/begin-review")]
        self.assertEqual(starts, ["first"] if shared else ["first", "second"])
        self.assertEqual(execute.await_count, 1 if shared else 2)
        if shared:
            self.assertFalse(any(call.args[1].endswith(("/finish", "/progress")) for call in writes))
            interrupted = next(call for call in writes if call.args[1].endswith("/interrupt"))
            self.assertEqual(interrupted.args[3]["error_code"], "ReviewDependencyError")
        else:
            progress = [call.args[2]["result"] for call in writes if call.args[1].endswith("/progress")]
            self.assertEqual([result["status"] for result in progress], ["blocked", "completed"])
            self.assertTrue(any(call.args[1].endswith("/finish") for call in writes))
