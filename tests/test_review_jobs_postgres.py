"""Opt-in PostgreSQL concurrency test in an isolated, disposable schema.

REVIEW_TEST_DSN is supplied by deployment tooling, never written or printed.
No production tables, backend HTTP calls or models are accessed by the test.
"""
import asyncio
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

import procrastinate
import psycopg
from psycopg import sql

from software_quality_agent.config import Settings
from software_quality_agent.review_jobs import QUEUE, build_queue, enqueue, initialize_schema


@unittest.skipUnless(os.environ.get("REVIEW_TEST_DSN"), "PostgreSQL test DSN not configured")
class PostgresQueueTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dsn = os.environ["REVIEW_TEST_DSN"]
        self.schema = "review_queue_test_" + uuid4().hex
        async with await psycopg.AsyncConnection.connect(self.dsn, autocommit=True) as connection:
            await connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.queue = build_queue(Settings(_env_file=None), connector=procrastinate.PsycopgConnector(
            conninfo=self.dsn, kwargs={"options": f"-c search_path={self.schema}"}, min_size=1, max_size=4))
        await self.queue.open_async()
        # The production initializer must be idempotent and use the official schema.
        await self.queue.close_async()
        await initialize_schema(self.queue)
        await initialize_schema(self.queue)
        await self.queue.open_async()
        self.payload = {"tenant_id": "local", "project_id": "p", "batch_id": "b"}

    async def asyncTearDown(self):
        await self.queue.close_async()
        # This schema is created by this test and validated before its removal.
        if not self.schema.startswith("review_queue_test_") or len(self.schema) != len("review_queue_test_") + 32:
            raise ValueError("unexpected disposable schema")
        async with await psycopg.AsyncConnection.connect(self.dsn, autocommit=True) as connection:
            await connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))

    async def test_concurrent_submission_and_todo_to_doing_transition(self):
        results = await asyncio.gather(*(enqueue(self.queue, self.payload) for _ in range(20)))
        self.assertEqual(len({r["job_id"] for r in results}), 1)
        started, release = asyncio.Event(), asyncio.Event()
        async def execute(*args, **kwargs):
            started.set()
            await release.wait()
        with patch("software_quality_agent.review_jobs.execute_batch", new=execute):
            worker = asyncio.create_task(self.queue.run_worker_async(queues=[QUEUE], wait=False,
                                                                      install_signal_handlers=False))
            try:
                await asyncio.wait_for(started.wait(), timeout=10)
                running = await asyncio.gather(*(enqueue(self.queue, self.payload) for _ in range(20)))
                self.assertEqual({r["job_id"] for r in running}, {results[0]["job_id"]})
                self.assertTrue(all(r["status"] == "running" for r in running))
                with self.assertRaises(ValueError):
                    await enqueue(self.queue, {**self.payload, "review_ids": ["other-scope"]})
            finally:
                release.set()
                await asyncio.wait_for(worker, timeout=10)
        self.assertEqual(len(list(await self.queue.job_manager.list_jobs_async(status="succeeded", queue=QUEUE))), 1)
