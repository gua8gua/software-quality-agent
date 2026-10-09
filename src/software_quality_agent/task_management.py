"""Unified read model for business tasks and Procrastinate execution jobs.

No mirrored scheduler state/table: run/batch owns scope/checkpoints; vendor
PostgreSQL jobs own dispatch, priority, locks, attempts and cancellation.
"""
from urllib.parse import quote

from .review_jobs import QUEUE, enqueue
from .review_runtime.context import BackendClient


def lifecycle(job, business_status, resource_busy=False):
    if job is None:
        return {"completed": "completed", "partial": "partial", "running": "unmanaged",
                "failed": "blocked", "interrupted": "interrupted"}.get(business_status, "pending")
    if job.status == "doing":
        return "interrupting" if job.abort_requested else "running"
    if job.status == "todo":
        return "waiting_resource" if resource_busy else "queued"
    if job.status in {"aborted", "cancelled"}:
        return "interrupted"
    if job.status == "failed":
        return "blocked"
    # Transport completed is not semantic assessment completed.
    return "completed" if business_status == "completed" else "partial"


async def pages(client, path):
    offset, rows = 0, []
    while True:
        page = await client.get(path, {"limit": 100, "offset": offset})
        rows.extend(page["items"])
        if not page.get("has_more"):
            return rows
        next_offset = page.get("next_offset")
        if not isinstance(next_offset, int) or next_offset <= offset:
            raise ValueError("task-list cursor did not advance")
        offset = next_offset


async def task_board(settings, queue, tenant, project_id=None):
    client = BackendClient(settings.quality_backend_url, tenant)
    try:
        projects = await client.get("/api/v1/projects")
        if project_id:
            projects = [p for p in projects if p["id"] == project_id]
            if not projects:
                raise ValueError("project not found in tenant scope")
        all_jobs = list(await queue.job_manager.list_jobs_async(queue=QUEUE)) if queue else []
        jobs = [j for j in all_jobs if j.task_kwargs.get("payload", {}).get("tenant_id") == tenant]
        busy = any(j.status == "doing" for j in all_jobs)
        rows = []
        for project in projects:
            root = f"/api/v1/projects/{quote(project['id'], safe='')}"
            artifacts = {a["id"]: a["filename"] for a in await client.get(root + "/artifacts")}
            runs = await pages(client, root + "/information/tlr-runs")
            batches = await pages(client, root + "/reviews/batch/list")
            for kind, records, id_field in (("trace", runs, "run_id"), ("analysis", batches, "batch_id")):
                for record in records:
                    identity = record[id_field]
                    attempts = [j for j in jobs if j.task_kwargs.get("payload", {}).get(id_field) == identity
                                and j.task_kwargs["payload"].get("project_id") == project["id"]]
                    job = max(attempts, key=lambda j: j.id) if attempts else None
                    scope = record.get("scope") or record.get("config") or {}
                    counts = record.get("status_counts") or {}
                    rows.append({
                        "task_id": f"{kind}:{identity}", "business_id": identity, "kind": kind,
                        "project_id": project["id"], "project_name": project["name"],
                        "name": record.get("name") or scope.get("task_name") or "需求—设计追溯",
                        "status": lifecycle(job, record["status"], busy), "business_status": record["status"],
                        "stage": record.get("stage") or ("逐语块评审" if record["status"] == "running" else "审核工作区"),
                        "source_files": [artifacts.get(a, "文件已移除") for a in scope.get("source_artifact_ids", [])],
                        "target_files": [artifacts.get(a, "文件已移除") for a in scope.get("target_artifact_ids", [])],
                        "dependency_id": record.get("tlr_run_id"), "created_at": record["created_at"],
                        "finished_at": record.get("finished_at"), "done": record.get("finished_count", 0),
                        "total": scope.get("source_node_count"), "counts": counts, "error": record.get("error"),
                        "job_id": job.id if job else None, "queue_status": job.status if job else None,
                        "priority": job.priority if job else 0,
                        "attempts": sum(j.attempts for j in attempts),
                        "resource": "本地大模型 + Embedding" if kind == "trace" else "本地大模型",
                        "scope_limited": bool(job and (job.task_kwargs["payload"].get("review_ids") or job.task_kwargs["payload"].get("sentence_ids"))),
                        "href": f"/projects/{quote(project['id'], safe='')}/{kind}/" + ("batch/" if kind == "analysis" else "") + identity,
                    })
        rows.sort(key=lambda r: r["created_at"], reverse=True)
        return {"tasks": rows, "projects": projects, "queue_available": queue is not None,
                "resources": {"worker_capacity": settings.review_worker_concurrency,
                              "model_task_capacity": 1, "running": sum(j.status == "doing" for j in all_jobs),
                              "queued": sum(j.status == "todo" for j in all_jobs),
                              "model": settings.suggestion_model or settings.llm_model or "未配置",
                              "context_window": settings.suggestion_context_window,
                              "model_call_timeout_seconds": getattr(settings, "suggestion_model_call_timeout_seconds", 180.0),
                              "passage_turn_limit": getattr(settings, "review_passage_max_turns", 24),
                              "review_pipeline": settings.review_pipeline,
                              "supplemental_passage_limit": 0 if settings.review_pipeline == "fixed_tlr" else getattr(settings, "review_supplemental_passage_limit", 8),
                              "model_retry_limit": min(1, getattr(settings, "review_model_retry_limit", 1))}}
    finally:
        await client.close()


async def task_action(settings, queue, *, tenant, project, kind, identity, action, priority=0):
    if kind not in {"trace", "analysis"}:
        raise ValueError("Unknown task type")
    client = BackendClient(settings.quality_backend_url, tenant)
    try:
        root = f"/api/v1/projects/{quote(project, safe='')}"
        await client.get(root)
        id_field = "run_id" if kind == "trace" else "batch_id"
        if kind == "trace":
            record = await client.get(f"/api/v1/traceability/runs/{quote(identity, safe='')}")
            if record.get("project_id") != project or record.get("tenant_id") != tenant:
                raise ValueError("TLR outside project scope")
        else:
            record = await client.get(root + f"/reviews/batch/{quote(identity, safe='')}")
        jobs = [j for j in await queue.job_manager.list_jobs_async(queue=QUEUE)
                if j.task_kwargs.get("payload", {}).get(id_field) == identity
                and j.task_kwargs["payload"].get("tenant_id") == tenant
                and j.task_kwargs["payload"].get("project_id") == project]
        if action == "interrupt":
            active = [j for j in jobs if j.status in {"todo", "doing"}]
            if not active:
                raise ValueError("No queued or executing job to interrupt")
            for job in active:
                await queue.job_manager.cancel_job_by_id_async(job.id, abort=True)
            return {"status": "interrupt_requested", "job_ids": [j.id for j in active]}
        if action not in {"resume", "retry_failed"}:
            raise ValueError("Unknown task action")
        if record["status"] == "completed" and (kind == "trace" or all(
                (r.get("assessment") or {}).get("finalized") for r in record.get("reviews", []))):
            return {"status": "completed"}
        active = [j for j in jobs if j.status in {"todo", "doing"}]
        if any(j.abort_requested for j in active):
            raise ValueError("Wait for the executor to acknowledge interruption before resuming")
        # Explicit resume preserves the original queued execution scope. A
        # single-review job must not silently become a full-artifact analysis.
        payload = max(jobs, key=lambda j: j.id).task_kwargs["payload"] if jobs else {
            "tenant_id": tenant, "project_id": project, id_field: identity}
        payload = {**payload}
        if kind == "analysis":
            payload.setdefault("review_pipeline", "full_investigation" if jobs else settings.review_pipeline)
        if action == "retry_failed":
            if active:
                raise ValueError("Wait for the active job to end before retrying failed units")
            payload["retry_failed"] = True
        else:
            payload.pop("retry_failed", None)
        return await enqueue(queue, payload, priority=priority)
    finally:
        await client.close()


async def task_detail(settings, queue, *, tenant, project, kind, identity):
    board = await task_board(settings, queue, tenant, project)
    task = next((t for t in board["tasks"] if t["task_id"] == f"{kind}:{identity}"), None)
    if task is None:
        raise ValueError("Task not found in project scope")
    client = BackendClient(settings.quality_backend_url, tenant)
    try:
        path = f"/api/v1/projects/{quote(project, safe='')}/reviews/batch/{quote(identity, safe='')}"
        record = await client.get(path) if kind == "analysis" else await client.get(f"/api/v1/traceability/runs/{quote(identity, safe='')}")
        events = []
        if queue is not None and hasattr(queue.connector, "pool"):
            from psycopg.rows import dict_row
            async with queue.connector.pool.connection() as connection, connection.cursor(row_factory=dict_row) as cursor:
                    # Read vendor event ledger after tenant/project ownership
                    # was established; never mutate vendor lifecycle columns.
                    await cursor.execute("SELECT e.job_id,e.type,e.at FROM procrastinate_events e "
                        "JOIN procrastinate_jobs j ON j.id=e.job_id "
                        "WHERE j.args->'payload'->>'tenant_id'=%s AND j.args->'payload'->>'project_id'=%s "
                        "AND j.args->'payload'->>%s=%s ORDER BY e.at DESC LIMIT 100",
                        [tenant, project, "run_id" if kind == "trace" else "batch_id", identity])
                    events = await cursor.fetchall()
        return {"task": task, "business": record, "events": events}
    finally:
        await client.close()
