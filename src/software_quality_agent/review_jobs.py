"""Durable transport for the SDK workflow, using Procrastinate's worker/locks.

Web routes only defer jobs. PostgreSQL keeps them across web restarts. Cognition
still runs in Runner; this module only owns transport and independent reviews.
"""

import argparse
import asyncio
import hashlib
import logging
from contextlib import suppress
from datetime import datetime
from urllib.parse import quote
from uuid import uuid4

import httpx
import procrastinate
from procrastinate.testing import InMemoryConnector
from psycopg.rows import dict_row

from .config import Settings, get_settings
from .review_runtime.context import BackendClient, BackendHTTPError
from .review_runtime.contracts import SuggestionRequest
from .suggestion_agent import run_review_suggestions

logger = logging.getLogger(__name__)
QUEUE = "quality-reviews"
RESOURCE_LOCK = "quality:local-model-workload"


class LeaseBusy(RuntimeError):
    def __init__(self, deadline):
        self.deadline = deadline
        super().__init__("existing backend worker lease is still active")


class LeaseLost(Exception):
    """Execution control failure, not an independent review/model failure."""


class LeaseRetry(procrastinate.BaseRetryStrategy):
    def get_retry_decision(self, *, exception, job):
        # Only ownership contention is rescheduled. Not model/semantic errors.
        if isinstance(exception, LeaseBusy):
            return procrastinate.RetryDecision(retry_at=exception.deadline)
        return None


def continuation_ids(batch, payload):
    selected = set(payload.get("review_ids") or batch["review_ids"])
    if not selected <= set(batch["review_ids"]):
        raise ValueError("requested reviews are outside the batch")
    return {r["review_id"] for r in batch["reviews"] if r["review_id"] in selected
            and not ((r.get("execution") or {}).get("status") in {"completed", "idle"}
                     and (r.get("assessment") or {}).get("finalized"))
            and (payload.get("retry_failed") or payload.get("review_ids") or not r.get("execution")
                 or r["execution"].get("status") == "running" or r["execution"].get("interrupted")
                 or r["execution"].get("error_code") in {"worker_interrupted", "CancelledError", "LeaseLost"})}


async def _renew(client: BackendClient, path: str, token: str, interval: float) -> None:
    while True:
        await asyncio.sleep(interval)
        await client.write("POST", path + "/heartbeat", {}, {"worker_token": token})


async def _with_lease(operation, heartbeat: asyncio.Task):
    """Ownership loss cancels cognition before it can continue any writes."""
    running = asyncio.create_task(operation)
    try:
        done, _ = await asyncio.wait({running, heartbeat}, return_when=asyncio.FIRST_COMPLETED)
        if heartbeat in done:
            try:
                await heartbeat
            except Exception as exc:
                raise LeaseLost(f"review lease renewal failed: {exc}") from exc
            raise LeaseLost("review_heartbeat_stopped")
        return await running
    finally:
        if not running.done():
            running.cancel()
            with suppress(asyncio.CancelledError):
                await running


async def execute_batch(settings: Settings, payload: dict) -> None:
    project, batch_id, tenant = payload["project_id"], payload["batch_id"], payload["tenant_id"]
    client = BackendClient(settings.quality_backend_url, tenant)
    path = f"/api/v1/projects/{quote(project, safe='')}/reviews/batch/{quote(batch_id, safe='')}"
    token, heartbeat, finished = str(uuid4()), None, False
    claimed = False
    interruption = {}
    try:
        current = await client.get(path)
        deadline = current.get("lease_expires_at")
        if current["status"] == "running" and deadline:
            from procrastinate.utils import utcnow
            deadline = datetime.fromisoformat(deadline)
            if deadline > utcnow():
                raise LeaseBusy(deadline)
        selected = continuation_ids(current, payload)
        batch = await client.http.post(client.base_url + path + "/claim", params={
            "tenant_id": tenant, "resume": True, "worker_token": token}, json={"review_ids": sorted(selected)})
        batch.raise_for_status()
        batch = batch.json()
        claimed = True
        lease = await client.write("POST", path + "/heartbeat", {}, {"worker_token": token})
        heartbeat = asyncio.create_task(_renew(client, path, token, lease["lease_seconds"] / 3))
        for review in batch["reviews"]:
            if review["review_id"] not in selected:
                continue
            if ((review.get("execution") or {}).get("status") in {"completed", "idle"}
                    and (review.get("assessment") or {}).get("finalized")):
                continue
            attempt = await client.write("POST", path + "/begin-review", {
                "review_id": review["review_id"], "attempt_id": str(uuid4()), "worker_token": token})
            identity = {key: attempt[key] for key in ("attempt", "attempt_id")}
            try:
                # Timeout belongs to one provider HTTP call. The complete
                # segment conversation may finish its persisted lifecycle;
                # passage investigation is bounded independently in the SDK.
                result = await _with_lease(run_review_suggestions(settings=settings, request=SuggestionRequest(
                    project_id=project, review_id=review["review_id"], tenant_id=tenant,
                    sentence_ids=payload.get("sentence_ids"), worker_token=token,
                    # Jobs queued before pipeline selection existed retain the
                    # original scope; new submissions freeze their mode.
                    review_pipeline=payload.get("review_pipeline", "full_investigation"),
                    execution_attempt_id=attempt["attempt_id"])), heartbeat)
            except BackendHTTPError as exc:
                if exc.status_code not in {400, 404, 422}:
                    raise  # transport/ownership/infrastructure: stop safely
                result = {"status": "blocked", "error_code": "review_data_rejected", "error_message": str(exc)}
            except (ValueError, RuntimeError) as exc:
                result = {"status": "blocked", "error_code": "review_execution_failed", "error_message": str(exc)}
            # The SDK workflow isolates sentence failures. Persist their genuine
            # outcome before the next independent review. Transport failure is
            # left as a failed queue job, resumable from the workspace.
            await client.write("POST", path + "/progress", {
                "review_id": review["review_id"], "result": {**result, **identity}, "worker_token": token})
        current = await client.get(path)
        if (not payload.get("review_ids") and not payload.get("sentence_ids")
                and current["finished_count"] == len(current["reviews"])
                and not current["status_counts"].get("running")):
            await client.write("POST", path + "/finish", {}, {"worker_token": token})
            finished = True
    except BaseException as exc:
        # Includes worker cancellation. This is an execution failure, never
        # an uncertain/insufficient assessment invented by the transport.
        interruption = {"error_code": type(exc).__name__[:128],
                        "error_message": (str(exc) or "Worker execution was cancelled")[:2000]}
        raise
    finally:
        if heartbeat is not None:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await heartbeat
        if claimed and not finished:
            try:
                await client.write("POST", path + "/interrupt", {}, {"worker_token": token, **interruption})
            except Exception:
                logger.exception("Could not persist batch interruption; lease expiry preserves fencing")
        await client.close()


def build_queue(settings: Settings, *, connector=None) -> procrastinate.App:
    if connector is None and not settings.review_queue_dsn:
        raise ValueError("REVIEW_QUEUE_DSN is required for durable review execution")
    queue = procrastinate.App(connector=connector or procrastinate.PsycopgConnector(
        conninfo=settings.review_queue_dsn, min_size=1, max_size=4))

    @queue.task(name="quality.review_batch", queue=QUEUE, retry=LeaseRetry())
    async def review_batch(payload: dict):
        # Semantic/model failures are already terminal workspace facts. Do not
        # automatically retry them or treat them as successful conclusions.
        await execute_batch(settings, payload)

    @queue.task(name="quality.tlr_run", queue=QUEUE, retry=False)
    async def tlr_run(payload: dict):
        # Same native worker/queue/resource lock as analysis. The backend
        # cancels its coroutine when this owning HTTP client disconnects.
        async with httpx.AsyncClient(timeout=None) as client:
            response = await client.post(f"{settings.quality_backend_url.rstrip('/')}/api/v1/traceability/runs/"
                                         f"{quote(payload['run_id'], safe='')}/execute",
                                         params={"tenant_id": payload["tenant_id"], "project_id": payload["project_id"]})
            response.raise_for_status()
            if response.json().get("status") != "completed":
                raise RuntimeError("TLR execution did not reach completed")

    @queue.periodic(cron="* * * * *")
    @queue.task(name="quality.recover_stalled_reviews", queue="quality-maintenance",
                queueing_lock="quality-recover-stalled", pass_context=True)
    async def recover_stalled(context, timestamp):
        for job in await queue.job_manager.get_stalled_jobs(queue=QUEUE):
            # Native heartbeat recovery, never elapsed LLM time. Retry after
            # the backend lease expiry; old workers are fenced at every write.
            from procrastinate.utils import utcnow
            payload = job.task_kwargs["payload"]
            if job.task_name == "quality.tlr_run":
                # Never automatically rerun a model/data error. Stalled means
                # dead worker; backend's per-run lock excludes a live executor.
                await queue.job_manager.retry_job(job, lock=RESOURCE_LOCK)
                continue
            client = BackendClient(settings.quality_backend_url, payload["tenant_id"])
            try:
                batch = await client.get(f"/api/v1/projects/{quote(payload['project_id'], safe='')}"
                                         f"/reviews/batch/{quote(payload['batch_id'], safe='')}")
                deadline = batch.get("lease_expires_at")
                if deadline and datetime.fromisoformat(deadline) > utcnow():
                    # A live backend owner is still executing. Leave the native
                    # job alone; a later maintenance pass can recover an expired lease.
                    continue
                retry_at = utcnow()
                await queue.job_manager.retry_job(job, retry_at=retry_at, lock=RESOURCE_LOCK)
            finally:
                await client.close()

    return queue


async def enqueue(queue: procrastinate.App, payload: dict, *, priority: int = 0) -> dict:
    kind = "quality.tlr_run" if "run_id" in payload else "quality.review_batch"
    identity = payload.get("batch_id") or payload.get("run_id")
    lock = f"{'tlr-run' if 'run_id' in payload else 'review-batch'}:{payload['tenant_id']}:{payload['project_id']}:{identity}"
    identity_field = "run_id" if "run_id" in payload else "batch_id"
    if isinstance(queue.connector, procrastinate.PsycopgConnector):
        # Native external-connection defer + PostgreSQL transaction advisory
        # lock closes the todo->doing race. queueing_lock alone excludes only
        # todo jobs; otherwise simultaneous clicks can queue a semantic retry.
        key = int.from_bytes(hashlib.sha256(lock.encode()).digest()[:8], signed=True)
        async with queue.connector.pool.connection() as connection, connection.transaction():
                async with connection.cursor(row_factory=dict_row) as cursor:
                    await cursor.execute("SELECT pg_advisory_xact_lock(%s)", [key])
                    await cursor.execute("SELECT id, status, args FROM procrastinate_jobs "
                                         "WHERE (queueing_lock = %s OR lock = %s) AND status IN ('todo', 'doing') ORDER BY id FOR UPDATE", [lock, lock])
                    existing = await cursor.fetchall()
                if existing:
                    job = existing[0]
                    if job["args"].get("payload") != payload:
                        raise ValueError("该批次已有不同范围的执行任务；请等待它结束后再启动本次范围")
                    return {identity_field: identity, "status": "running" if job["status"] == "doing" else "queued",
                            "job_id": job["id"]}
                job_id = await queue.tasks[kind].configure(
                    lock=RESOURCE_LOCK, queueing_lock=lock, priority=priority, connection=connection).defer_async(payload=payload)
                return {identity_field: identity, "status": "queued", "job_id": job_id}
    if not isinstance(queue.connector, InMemoryConnector):
        raise TypeError("durable execution requires PsycopgConnector")
    # Official in-memory connector for deterministic tests ONLY. Production
    # build_queue always creates the PostgreSQL connector above.
    for status in ("todo", "doing"):
        existing = list(await queue.job_manager.list_jobs_async(queueing_lock=lock, status=status))
        if existing:
            if existing[0].task_kwargs.get("payload") != payload:
                raise ValueError("该批次已有不同范围的执行任务；请等待它结束后再启动本次范围")
            return {identity_field: identity, "status": "running" if status == "doing" else "queued",
                    "job_id": existing[0].id}
    try:
        job_id = await queue.tasks[kind].configure(
            lock=RESOURCE_LOCK, queueing_lock=lock, priority=priority).defer_async(payload=payload)
    except procrastinate.exceptions.AlreadyEnqueued:
        existing = list(await queue.job_manager.list_jobs_async(queueing_lock=lock, status="todo"))
        if not existing or existing[0].task_kwargs.get("payload") != payload:
            raise ValueError("another execution scope was concurrently queued") from None
        return {identity_field: identity, "status": "queued", "job_id": existing[0].id}
    return {identity_field: identity, "status": "queued", "job_id": job_id}


async def initialize_schema(queue: procrastinate.App) -> None:
    """First installation uses the vendor schema. Existing schemas aren't overwritten."""
    async with queue.open_async(), queue.connector.pool.connection() as connection, connection.transaction():
            await connection.execute("SELECT pg_advisory_xact_lock(%s)", [817264291])
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute("SELECT to_regclass('procrastinate_jobs') AS existing")
                exists = await cursor.fetchone()
            if exists["existing"] is None:
                await connection.execute(queue.schema_manager.get_schema())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--init-schema", action="store_true")
    parser.add_argument("--maintenance-only", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    queue = build_queue(settings)
    if args.init_schema:
        asyncio.run(initialize_schema(queue))
        return
    queue.run_worker(queues=["quality-maintenance"] if args.maintenance_only else [QUEUE],
                     concurrency=1 if args.maintenance_only else settings.review_worker_concurrency)


if __name__ == "__main__":
    main()
