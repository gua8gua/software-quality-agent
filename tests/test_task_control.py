import asyncio
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from software_quality_agent.execution_guard import NoBusinessProgress, with_progress_deadline
from software_quality_agent.review_runtime.checkpoint import CheckpointStore
from software_quality_agent.task_management import lifecycle


class TaskControlTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_progress_cancels_actual_coroutine(self):
        cancelled = asyncio.Event()
        async def work():
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        store = SimpleNamespace(data={"last_business_progress_at": (datetime.now(UTC) - timedelta(seconds=10)).isoformat()})
        with self.assertRaises(NoBusinessProgress):
            await with_progress_deadline(work(), store, 1)
        # A task cancelled before its first instruction has no finally to run;
        # it must still be gone, with no orphan or provider call.
        self.assertEqual(len([t for t in asyncio.all_tasks() if t is not asyncio.current_task()]), 0)

    async def test_deadline_is_not_a_maximum_duration_for_progressing_work(self):
        store = SimpleNamespace(data={"last_business_progress_at": datetime.now(UTC).isoformat()})
        async def work():
            for _ in range(3):
                await asyncio.sleep(.02)
                store.data["last_business_progress_at"] = datetime.now(UTC).isoformat()
            return "done"
        self.assertEqual(await with_progress_deadline(work(), store, .04), "done")

    def test_replayed_reads_do_not_reset_deadline_and_explicit_attempt_resets_circuit(self):
        with tempfile.TemporaryDirectory() as root:
            store = CheckpointStore(Path(root), "r", "s")
            store.begin_attempt()
            i = store.tool_call("get_canonical_node", {"node_id": "n"})
            store.tool_success(i, {"text": "exact"})
            stamp = store.data["last_business_progress_at"]
            i = store.tool_call("get_canonical_node", {"node_id": "n"})
            store.tool_success(i, {"text": "exact"})
            self.assertEqual(stamp, store.data["last_business_progress_at"])
            store.data["model_failure_streak"] = 2
            store.begin_attempt()
            self.assertEqual(store.data["model_failure_streak"], 0)
            self.assertEqual(store.data["attempt_history"][-1]["model_failure_streak"], 2)

    def test_transport_success_does_not_promote_partial_business_result(self):
        job = SimpleNamespace(status="succeeded", abort_requested=False)
        self.assertEqual(lifecycle(job, "partial"), "partial")
        job.status = "doing"
        job.abort_requested = True
        self.assertEqual(lifecycle(job, "running"), "interrupting")
        job.status = "aborted"
        self.assertEqual(lifecycle(job, "running"), "interrupted")
