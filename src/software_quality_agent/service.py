from __future__ import annotations

from .agents import (
    ConversationAgent,
    DatabaseReadAgent,
    DatabaseWriteAgent,
    EvidenceAgent,
    LLMClient,
    MockLLMClient,
    OpenAICompatibleLLMClient,
    OrchestratorAgent,
    ReportAgent,
    VerifierAgent,
)
from .config import Settings
from .schemas import (
    ChatRequest,
    ChatResponse,
    DatabaseReadRequest,
    DatabaseReadResponse,
    DatabaseWriteRequest,
    DatabaseWriteResponse,
    ProjectSummary,
    ReportRequest,
    ReportResponse,
    SchemaResponse,
)
from .store import QualityStore, ReportRun


class QualityAgentService:
    def __init__(self, settings: Settings, store: QualityStore) -> None:
        self.settings = settings
        self.store = store
        self.llm = self._build_llm()
        self.orchestrator = OrchestratorAgent(
            conversation_agent=ConversationAgent(self.llm),
            report_agent=ReportAgent(self.llm),
            read_agent=DatabaseReadAgent(self.store),
            write_agent=DatabaseWriteAgent(self.store),
            evidence_agent=EvidenceAgent(self.store),
            verifier_agent=VerifierAgent(),
        )

    def _build_llm(self) -> LLMClient:
        if self.settings.llm_provider == "openai_compatible" and self.settings.llm_api_key:
            return OpenAICompatibleLLMClient(
                base_url=self.settings.llm_base_url,
                api_key=self.settings.llm_api_key,
                model=self.settings.llm_model,
                timeout_seconds=self.settings.llm_timeout_seconds,
            )
        return MockLLMClient()

    async def list_projects(self) -> list[ProjectSummary]:
        projects = await self.store.list_projects()
        return [ProjectSummary.model_validate(self.store.project_row(item)) for item in projects]

    async def chat(self, request: ChatRequest) -> ChatResponse:
        project = await self._require_project(request.project_id)
        response = await self.orchestrator.handle_chat(request, project)
        await self.store.add_chat_message(
            request.project_id,
            "user",
            request.message,
            evidence=response.evidence,
        )
        await self.store.add_chat_message(
            request.project_id,
            "assistant",
            response.answer,
            evidence=response.evidence,
        )
        return response

    async def generate_report(self, request: ReportRequest) -> ReportResponse:
        project = await self._require_project(request.project_id)
        response = await self.orchestrator.handle_report(request, project)
        report_run = self._to_report_run(request, response)
        saved = await self.store.add_report(report_run)
        response.report_id = saved["id"]
        return response

    async def read_database(self, request: DatabaseReadRequest) -> DatabaseReadResponse:
        return await self.orchestrator.handle_db_read(request)

    async def write_database(self, request: DatabaseWriteRequest) -> DatabaseWriteResponse:
        return await self.orchestrator.handle_db_write(request)

    async def schema(self) -> SchemaResponse:
        return SchemaResponse(tables=await self.store.get_schema())

    async def history(self, project_id: str) -> list[dict[str, object]]:
        messages = await self.store.list_chat_messages(project_id)
        return [self.store.chat_row(item) for item in messages]

    async def reports(self, project_id: str) -> list[dict[str, object]]:
        reports = await self.store.list_reports(project_id)
        return [self.store.report_row(item) for item in reports]

    async def _require_project(self, project_id: str):
        project = await self.store.get_project(project_id)
        if project is None:
            raise ValueError(f"Unknown project_id: {project_id}")
        return project

    def _to_report_run(self, request: ReportRequest, response: ReportResponse) -> ReportRun:
        from uuid import uuid4

        return ReportRun(
            id=str(uuid4()),
            project_id=request.project_id,
            report_type=request.report_type,
            title=response.title,
            focus=request.focus,
            markdown=response.markdown,
            highlights=response.highlights,
            risks=response.risks,
        )
