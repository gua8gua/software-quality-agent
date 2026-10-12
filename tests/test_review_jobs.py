"""Native queue/worker contracts only. Never calls TLR, embeddings or models."""

import asyncio
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from procrastinate.testing import InMemoryConnector

from software_quality_agent.config import Settings
from software_quality_agent.review_jobs import (
    QUEUE,
    RESOURCE_LOCK,
    LeaseBusy,
    LeaseLost,
    LeaseRetry,
    _with_lease,
    build_queue,
    continuation_ids,
    enqueue,
    execute_batch,
)


class ReviewJobsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.settings = Settings(_env_file=None, review_queue_dsn="")
        self.queue = build_queue(self.settings, connector=InMemoryConnector())
        self.payload = {"tenant_id": "local", "project_id": "p", "batch_id": "b"}

    async def test_native_defer_is_idempotent_and_preserves_full_scope(self):
        first = await enqueue(self.queue, self.payload)
        again = await enqueue(self.queue, self.payload)
        self.assertEqual(first, again)
        jobs = list(await self.queue.job_manager.list_jobs_async(status="todo", queue=QUEUE))
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].task_kwargs["payload"], self.payload)
        self.assertEqual(jobs[0].lock, RESOURCE_LOCK)
        self.assertEqual(jobs[0].queueing_lock, "review-batch:local:p:b")
        with self.assertRaisesRegex(ValueError, "不同范围"):
            await enqueue(self.queue, {**self.payload, "review_ids": ["only-one"]})

    async def test_native_worker_executes_deferred_job_not_web_task(self):
        await enqueue(self.queue, self.payload)
        with patch("software_quality_agent.review_jobs.execute_batch", new_callable=AsyncMock) as execute:
            async with self.queue.open_async():
                await self.queue.run_worker_async(queues=[QUEUE], wait=False, install_signal_handlers=False)
            execute.assert_awaited_once_with(self.settings, self.payload)
        jobs = list(await self.queue.job_manager.list_jobs_async(status="succeeded", queue=QUEUE))
        self.assertEqual(len(jobs), 1)

    async def test_both_task_types_use_one_native_resource_lock(self):
        await enqueue(self.queue, self.payload)
        await enqueue(self.queue, {"tenant_id": "local", "project_id": "p", "run_id": "t"}, priority=10)
        jobs = list(await self.queue.job_manager.list_jobs_async(status="todo", queue=QUEUE))
        self.assertEqual({j.task_name for j in jobs}, {"quality.review_batch", "quality.tlr_run"})
        self.assertEqual({j.lock for j in jobs}, {RESOURCE_LOCK})
        self.assertEqual(len({j.queueing_lock for j in jobs}), 2)

    def test_continuation_is_not_a_retry_of_every_past_failure(self):
        batch = {"review_ids": ["a", "b", "c", "d"], "reviews": [
            {"review_id": "a", "execution": {"status": "partial", "error_code": "ModelBehaviorError"}},
            {"review_id": "b", "execution": {"status": "blocked", "interrupted": True}},
            {"review_id": "c", "execution": None},
            {"review_id": "d", "execution": {"status": "completed"}, "assessment": {"finalized": True}},
        ]}
        self.assertEqual(continuation_ids(batch, {}), {"b", "c"})
        self.assertEqual(continuation_ids(batch, {"retry_failed": True}), {"a", "b", "c"})

    async def test_queue_failure_is_failed_not_succeeded_or_automatic_model_retry(self):
        await enqueue(self.queue, self.payload)
        with patch("software_quality_agent.review_jobs.execute_batch", new_callable=AsyncMock,
                   side_effect=RuntimeError("provider setup failed")):
            async with self.queue.open_async():
                await self.queue.run_worker_async(queues=[QUEUE], wait=False, install_signal_handlers=False)
        self.assertEqual(len(list(await self.queue.job_manager.list_jobs_async(status="failed", queue=QUEUE))), 1)
        self.assertIsNone(LeaseRetry().get_retry_decision(exception=RuntimeError("model error"), job=None))

    def test_lease_retry_uses_actual_deadline_not_a_hardcoded_delay(self):
        for seconds in (31, 900):
            deadline = datetime.now(UTC) + timedelta(seconds=seconds)
            decision = LeaseRetry().get_retry_decision(exception=LeaseBusy(deadline), job=None)
            self.assertEqual(decision.retry_at, deadline)

    async def test_ownership_loss_cancels_cognition_without_a_semantic_result(self):
        cancelled = asyncio.Event()
        started = asyncio.Event()
        async def operation():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        async def renewal():
            await started.wait()
            raise RuntimeError("worker ownership revoked")
        heartbeat = asyncio.create_task(renewal())
        with self.assertRaises(LeaseLost):
            await _with_lease(operation(), heartbeat)
        self.assertTrue(cancelled.is_set())

    async def test_transport_failure_is_persisted_as_interruption_not_a_semantic_result(self):
        import httpx

        client = AsyncMock()
        client.base_url = "http://backend"
        client.get.return_value = {"status": "pending", "review_ids": ["r"], "reviews": [{"review_id": "r"}]}
        response = unittest.mock.Mock()
        response.json.return_value = client.get.return_value
        client.http.post.return_value = response

        async def write(method, path, payload, params=None):
            if path.endswith("/heartbeat"):
                return {"lease_seconds": 300}
            if path.endswith("/begin-review"):
                return {"attempt": 1, "attempt_id": "a"}
            return {}

        client.write.side_effect = write
        with patch("software_quality_agent.review_jobs.BackendClient", return_value=client), patch(
            "software_quality_agent.review_jobs.run_review_suggestions", new_callable=AsyncMock,
            side_effect=httpx.ConnectError("connection lost"),
        ), self.assertRaises(httpx.ConnectError):
            await execute_batch(self.settings, self.payload)
        calls = client.write.await_args_list
        self.assertFalse(any(call.args[1].endswith("/progress") for call in calls))
        interrupt = next(call for call in calls if call.args[1].endswith("/interrupt"))
        self.assertEqual(interrupt.args[3]["error_code"], "ConnectError")
        self.assertEqual(interrupt.args[3]["error_message"], "connection lost")
        client.close.assert_awaited_once()

    async def test_unit_deadline_cancels_only_stuck_unit_and_continues_independent_review(self):
        # Above Windows' ~16 ms monotonic clock resolution: the fast unit must
        # not race a zero-tick deadline. These are fixture deadlines, not model
        # budgets or deployment settings.
        for deadline in (.1, .2):
            settings = self.settings.model_copy(update={"review_unit_timeout_seconds": deadline})
            client = AsyncMock()
            client.base_url = "http://backend"
            batch = {"status": "pending", "review_ids": ["slow", "next"],
                     "reviews": [{"review_id": "slow"}, {"review_id": "next"}]}
            client.get.side_effect = [batch, {**batch, "finished_count": 2, "status_counts": {"blocked": 1, "completed": 1}}]
            response = unittest.mock.Mock()
            response.json.return_value = batch
            client.http.post.return_value = response
            cancelled = asyncio.Event()

            async def write(method, path, payload, params=None):
                if path.endswith("/heartbeat"):
                    return {"lease_seconds": 300}
                if path.endswith("/begin-review"):
                    return {"attempt": 1, "attempt_id": payload["review_id"]}
                return {}

            async def execute(*, settings, request, cancelled=cancelled):
                if request.review_id == "slow":
                    try:
                        await asyncio.Event().wait()
                    finally:
                        cancelled.set()
                return {"status": "completed"}

            client.write.side_effect = write
            with patch("software_quality_agent.review_jobs.BackendClient", return_value=client), patch(
                "software_quality_agent.review_jobs.run_review_suggestions", side_effect=execute,
            ):
                await execute_batch(settings, self.payload)
            outcomes = [call.args[2] for call in client.write.await_args_list if call.args[1].endswith("/progress")]
            self.assertTrue(cancelled.is_set())
            self.assertEqual([r["review_id"] for r in outcomes], ["slow", "next"])
            self.assertEqual(outcomes[0]["result"]["status"], "blocked")
            self.assertEqual(outcomes[0]["result"]["error_code"], "review_unit_deadline_exceeded")
            self.assertEqual(outcomes[1]["result"]["status"], "completed", outcomes)
            self.assertTrue(any(call.args[1].endswith("/finish") for call in client.write.await_args_list))
            self.assertFalse(any(call.args[1].endswith("/interrupt") for call in client.write.await_args_list))

    def test_missing_queue_does_not_fall_back_to_background_tasks_or_chat_json(self):
        from software_quality_agent.server import build_app
        with patch("software_quality_agent.server.get_settings", return_value=self.settings), TestClient(build_app()) as client:
            response = client.post("/api/agent/review-suggestions/batch", json=self.payload)
            self.assertEqual(response.status_code, 503)
            response = client.post("/api/agent/review-suggestions", json={"project_id": "p", "review_id": "r"})
            self.assertEqual(response.status_code, 503)
