from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, File, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .schemas import (
    ChatRequest,
    DatabaseReadRequest,
    DatabaseWriteRequest,
    ReportRequest,
    RequirementCoverageRequest,
)
from .service import QualityAgentService
from .store import QualityStore


FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def build_app() -> FastAPI:
    settings = get_settings()
    store = QualityStore(settings.database_url)
    service = QualityAgentService(settings, store)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await store.initialize()
        app.state.service = service
        yield
        await store.close()

    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def get_service(request: Request) -> QualityAgentService:
        return request.app.state.service

    @app.get("/", response_model=None)
    async def root() -> FileResponse | dict[str, object]:
        """Serve the bundled workbench, with an API fallback before it is built."""
        index_file = FRONTEND_DIST / "index.html"
        if index_file.is_file():
            return FileResponse(index_file)
        return {
            "status": "ok",
            "app": settings.app_name,
            "message": "Software Quality Agent API is running",
            "health": "/api/health",
            "docs": "/docs",
            "openapi": "/openapi.json",
        }

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "app": settings.app_name}

    @app.get("/api/projects")
    async def projects(service: QualityAgentService = Depends(get_service)):
        return await service.list_projects()

    @app.get("/api/chat/history")
    async def chat_history(project_id: str, service: QualityAgentService = Depends(get_service)):
        return await service.history(project_id)

    @app.post("/api/chat")
    async def chat(request: ChatRequest, service: QualityAgentService = Depends(get_service)):
        return await service.chat(request)

    @app.post("/api/reports/generate")
    async def generate_report(
        request: ReportRequest, service: QualityAgentService = Depends(get_service)
    ):
        return await service.generate_report(request)

    @app.post("/api/requirements/extract")
    async def extract_requirements(
        file: UploadFile = File(...),
        service: QualityAgentService = Depends(get_service),
    ):
        if file.content_type not in {"application/pdf", "application/octet-stream"}:
            raise ValueError("只支持上传 PDF 文件")
        return await service.extract_requirements(
            filename=file.filename or "project.pdf",
            content=await file.read(),
        )

    @app.post("/api/requirements/coverage")
    async def analyze_requirement_coverage(
        request: RequirementCoverageRequest,
        service: QualityAgentService = Depends(get_service),
    ):
        return await service.analyze_requirement_coverage(request)

    @app.get("/api/reports")
    async def list_reports(project_id: str, service: QualityAgentService = Depends(get_service)):
        return await service.reports(project_id)

    @app.get("/api/database/schema")
    async def database_schema(service: QualityAgentService = Depends(get_service)):
        return await service.schema()

    @app.post("/api/database/read")
    async def database_read(
        request: DatabaseReadRequest, service: QualityAgentService = Depends(get_service)
    ):
        return await service.read_database(request)

    @app.post("/api/database/write")
    async def database_write(
        request: DatabaseWriteRequest, service: QualityAgentService = Depends(get_service)
    ):
        return await service.write_database(request)

    @app.exception_handler(ValueError)
    async def handle_value_error(_request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.api_route("/api/v1/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"], include_in_schema=False)
    async def quality_backend(path: str, request: Request):
        # Keep the quality service separate while serving both panels on one origin.
        excluded = {"host", "connection", "content-length", "transfer-encoding", "accept-encoding"}
        headers = {key: value for key, value in request.headers.items() if key.lower() not in excluded}
        try:
            async with httpx.AsyncClient(timeout=600.0) as client:
                upstream = await client.request(
                    request.method,
                    f"{settings.quality_backend_url.rstrip('/')}/api/v1/{path}",
                    params=request.query_params.multi_items(),
                    headers=headers,
                    content=await request.body(),
                )
        except httpx.RequestError:
            return JSONResponse(status_code=502, content={"detail": "Quality backend unavailable"})
        excluded.update({"content-encoding", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "upgrade"})
        return Response(content=upstream.content, status_code=upstream.status_code,
                        headers={key: value for key, value in upstream.headers.items() if key.lower() not in excluded})

    if FRONTEND_DIST.is_dir():
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")

    return app


app = build_app()
