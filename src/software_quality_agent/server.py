"""Static quality workbench, canonical-backend proxy, and SDK suggestion route."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import quote

import httpx
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import get_settings

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


class SuggestionRequestPayload(BaseModel):
    project_id: str = Field(min_length=1)
    review_id: str = Field(min_length=1)
    sentence_ids: list[str] | None = None
    tenant_id: str = "local"
    priority: Literal[-10, 0, 10] = 0


class BatchSuggestionRequestPayload(BaseModel):
    project_id: str = Field(min_length=1)
    batch_id: str = Field(min_length=1)
    tenant_id: str = "local"
    priority: Literal[-10, 0, 10] = 0


def build_app() -> FastAPI:
    settings = get_settings()
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.review_queue = None
        if settings.review_queue_dsn:
            from .review_jobs import build_queue
            queue = build_queue(settings)
            async with queue.open_async():
                app.state.review_queue = queue
                yield
        else:
            yield  # read-only UI remains available; execution fails closed

    app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "app": settings.app_name}

    # Restored global-console entry points are distinct from the formal review
    # SDK route below. Teammate's requirement/report implementations are intact.
    from .console_service import ConsoleState, chat, peer_service, reset_chat
    from .schemas import ChatRequest, ReportRequest, RequirementCoverageRequest

    class ConsoleChatRequest(ChatRequest):
        tenant_id: str = "local"

    chat_locks: dict[tuple[str, str], asyncio.Lock] = {}

    @app.delete("/api/chat/history")
    async def clear_chat_history(project_id: str, tenant_id: str = "local"):
        from .review_runtime.context import BackendClient
        client = BackendClient(settings.quality_backend_url, tenant_id)
        try:
            await client.get(f"/api/v1/projects/{quote(project_id, safe='')}")
            async with chat_locks.setdefault((tenant_id, project_id), asyncio.Lock()):
                await reset_chat(settings, tenant_id, project_id)
            return {"cleared": True}
        finally:
            await client.close()

    @app.get("/api/chat/history")
    async def chat_history(project_id: str, tenant_id: str = "local"):
        from .review_runtime.context import BackendClient
        client = BackendClient(settings.quality_backend_url, tenant_id)
        try:
            await client.get(f"/api/v1/projects/{quote(project_id, safe='')}")
            return ConsoleState(settings.console_state_db).records(tenant_id, project_id, "chat")
        finally:
            await client.close()

    @app.post("/api/chat")
    async def console_chat(request: ConsoleChatRequest):
        identity = request.tenant_id, request.project_id
        async with chat_locks.setdefault(identity, asyncio.Lock()):
            try:
                return await chat(settings, request.project_id, request.tenant_id, request.message, request.mode)
            except Exception as exc:
                raise HTTPException(502, f"项目对话执行失败：{type(exc).__name__}") from exc

    @app.get("/api/reports")
    async def reports(project_id: str, tenant_id: str = "local"):
        from .review_runtime.context import BackendClient
        client = BackendClient(settings.quality_backend_url, tenant_id)
        try:
            await client.get(f"/api/v1/projects/{quote(project_id, safe='')}")
            return ConsoleState(settings.console_state_db).records(tenant_id, project_id, "report")
        finally:
            await client.close()

    @app.post("/api/reports/generate")
    async def report_generate(request: ReportRequest):
        service, client = await peer_service(settings, "local")
        try:
            return await service.generate_report(request)
        finally:
            await client.close()

    @app.post("/api/requirements/extract")
    async def requirement_extract(file: UploadFile = File(...)):
        service, client = await peer_service(settings, "local")
        try:
            return await service.extract_requirements(filename=file.filename or "project.pdf", content=await file.read())
        finally:
            await client.close()

    @app.post("/api/requirements/coverage")
    async def requirement_coverage(request: RequirementCoverageRequest):
        service, client = await peer_service(settings, "local")
        try:
            return await service.analyze_requirement_coverage(request)
        finally:
            await client.close()

    @app.exception_handler(ValueError)
    async def invalid_console_input(_request: Request, exc: ValueError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    def execution_queue():
        queue = getattr(app.state, "review_queue", None)
        if queue is None:
            raise HTTPException(503, "一致性分析的持久任务队列未配置，未启动任何模型工作")
        return queue

    class TaskActionPayload(BaseModel):
        project_id: str = Field(min_length=1)
        tenant_id: str = "local"
        action: Literal["interrupt", "resume", "retry_failed"]
        priority: Literal[-10, 0, 10] = 0

    @app.get("/api/tasks")
    async def managed_tasks(tenant_id: str = "local", project_id: str | None = None):
        from .task_management import task_board
        return await task_board(settings, getattr(app.state, "review_queue", None), tenant_id, project_id)

    @app.get("/api/tasks/{kind}/{identity}")
    async def managed_task(kind: str, identity: str, project_id: str, tenant_id: str = "local"):
        from .task_management import task_detail
        return await task_detail(settings, getattr(app.state, "review_queue", None), tenant=tenant_id,
                                 project=project_id, kind=kind, identity=identity)

    @app.post("/api/tasks/{kind}/{identity}/action", status_code=202)
    async def manage_task(kind: str, identity: str, body: TaskActionPayload):
        from .task_management import task_action
        return await task_action(settings, execution_queue(), tenant=body.tenant_id, project=body.project_id,
                                 kind=kind, identity=identity, action=body.action, priority=body.priority)

    @app.post("/api/agent/review-suggestions", status_code=202)
    async def review_suggestions(request: SuggestionRequestPayload) -> dict:
        from .review_jobs import enqueue
        from .review_runtime.context import BackendClient
        queue = execution_queue()
        client = BackendClient(settings.quality_backend_url, request.tenant_id)
        path = f"/api/v1/projects/{quote(request.project_id, safe='')}/reviews/{quote(request.review_id, safe='')}"
        try:
            workspace = await client.get(path + "/workspace")
            batch_id = workspace.get("batch_id")
            if not batch_id:
                batch_id = (await client.write("POST", path + "/execution-batch", {}))["batch_id"]
            requested = sorted(set(request.sentence_ids or []))
            if requested and not set(requested) <= {s['sentence_id'] for s in workspace['sentences']}:
                raise ValueError("requested sentence is outside this review")
            result = await enqueue(queue, {"project_id": request.project_id, "tenant_id": request.tenant_id,
                                           "batch_id": batch_id, "review_ids": [request.review_id],
                                           "review_pipeline": settings.review_pipeline,
                                           "sentence_ids": requested or None}, priority=request.priority)
            return {**result, "review_id": request.review_id}
        finally:
            await client.close()

    @app.post("/api/agent/review-suggestions/batch", status_code=202)
    async def review_suggestions_batch(request: BatchSuggestionRequestPayload) -> dict:
        from .review_jobs import enqueue
        from .review_runtime.context import BackendClient
        queue = execution_queue()
        client = BackendClient(settings.quality_backend_url, request.tenant_id)
        try:
            # Resume restores persisted review/checkpoint state. It never
            # restarts TLR, embeddings or successful review units.
            batch = await client.get(f"/api/v1/projects/{request.project_id}/reviews/batch/{request.batch_id}")
            if batch["status"] == "completed" and all(
                (review.get("assessment") or {}).get("finalized") for review in batch["reviews"]
            ):
                return {"batch_id": request.batch_id, "status": "completed"}
            return await enqueue(queue, {"project_id": request.project_id, "tenant_id": request.tenant_id,
                                         "batch_id": request.batch_id,
                                         "review_pipeline": settings.review_pipeline}, priority=request.priority)
        finally:
            await client.close()

    @app.get("/api/agent/review-suggestions/{review_id}/{sentence_id}")
    async def suggestion_checkpoint(review_id: str, sentence_id: str, project_id: str,
                                    tenant_id: str = "local") -> dict:
        from .suggestion_agent import read_suggestion_checkpoint

        # Check tenant/project ownership before exposing a filesystem checkpoint.
        async with httpx.AsyncClient(timeout=30) as client:
            scoped = await client.get(
                f"{settings.quality_backend_url.rstrip('/')}/api/v1/projects/{project_id}/reviews/{review_id}",
                params={"tenant_id": tenant_id},
            )
        if scoped.status_code != 200:
            raise HTTPException(scoped.status_code, "Review unavailable in project scope")
        try:
            return read_suggestion_checkpoint(settings=settings, review_id=review_id,
                                              sentence_id=sentence_id)
        except FileNotFoundError:
            raise HTTPException(404, "No saved suggestion checkpoint") from None
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/agent/review-suggestions/{review_id}/{sentence_id}/llm-state")
    async def suggestion_llm_state(review_id: str, sentence_id: str, project_id: str,
                                   tenant_id: str = "local") -> dict:
        """Expose the last host admission decision without opening a run.

        This is deliberately a checkpoint read: it never probes, retries or
        starts a model.  Operators can therefore distinguish ``allow``,
        ``compress`` and ``abandon`` before asking the queue to resume.
        """
        from .suggestion_agent import read_suggestion_checkpoint

        async with httpx.AsyncClient(timeout=30) as client:
            scoped = await client.get(
                f"{settings.quality_backend_url.rstrip('/')}/api/v1/projects/{project_id}/reviews/{review_id}",
                params={"tenant_id": tenant_id},
            )
        if scoped.status_code != 200:
            raise HTTPException(scoped.status_code, "Review unavailable in project scope")
        try:
            checkpoint = read_suggestion_checkpoint(settings=settings, review_id=review_id,
                                                    sentence_id=sentence_id)
        except FileNotFoundError:
            raise HTTPException(404, "No saved suggestion checkpoint") from None
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        binding = checkpoint.get("execution_binding") or {}
        return {
            "review_id": review_id,
            "sentence_id": sentence_id,
            "workflow_status": checkpoint.get("workflow_status"),
            "stage": checkpoint.get("stage"),
            "model": binding.get("model"),
            "llm_state": checkpoint.get("llm_state"),
            "llm_admission": checkpoint.get("llm_admission", []),
            "model_calls": checkpoint.get("model_calls", []),
        }

    @app.api_route("/api/v1/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"], include_in_schema=False)
    async def quality_backend(path: str, request: Request):
        if request.method == "POST" and path.startswith("traceability/runs/") and path.endswith("/execute"):
            return JSONResponse(status_code=409, content={"detail": "请通过任务队列启动或恢复追溯，不能在页面请求中直接执行"})
        # This proxy serves the current quality UI; it is not an Agent tool.
        excluded = {"host", "connection", "content-length", "transfer-encoding", "accept-encoding"}
        headers = {key: value for key, value in request.headers.items() if key.lower() not in excluded}
        try:
            async with httpx.AsyncClient(timeout=600.0) as client:
                upstream = await client.request(
                    request.method,
                    f"{settings.quality_backend_url.rstrip('/')}/api/v1/{path}",
                    params=request.query_params.multi_items(), headers=headers,
                    content=await request.body(),
                )
        except httpx.RequestError:
            return JSONResponse(status_code=502, content={"detail": "Quality backend unavailable"})
        excluded.update({"content-encoding", "keep-alive", "proxy-authenticate",
                         "proxy-authorization", "te", "trailer", "upgrade"})
        return Response(content=upstream.content, status_code=upstream.status_code,
                        headers={key: value for key, value in upstream.headers.items()
                                 if key.lower() not in excluded})

    if FRONTEND_DIST.is_dir():
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
    else:
        @app.get("/")
        async def root():
            return {"status": "ok", "message": "Build the quality frontend to view the workbench"}
    return app


app = build_app()
