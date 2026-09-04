from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .schemas import ChatRequest, DatabaseReadRequest, DatabaseWriteRequest, ReportRequest
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

    if FRONTEND_DIST.is_dir():
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")

    return app


app = build_app()
