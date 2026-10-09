"""Console integration boundary; restored teammate modules are not edited.

Project/content/TLR facts come only from the canonical backend. The local state
database stores user dialogue and generated reports, never a second project tree.
"""
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

from agents import RunConfig, Runner, SQLiteSession
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from openai import AsyncOpenAI

from .config import Settings
from .review_runtime.context import BackendClient
from .role_definitions.project_conversation import ChatAnswer, create_project_conversation_agent
from .tool_definitions.project_query import create_project_query_tool


class ConsoleState:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS console_records (id INTEGER PRIMARY KEY, tenant TEXT NOT NULL, project TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL)")

    def records(self, tenant: str, project: str, kind: str):
        with sqlite3.connect(self.path) as connection:
            return [json.loads(row[0]) for row in connection.execute("SELECT payload FROM console_records WHERE tenant=? AND project=? AND kind=? ORDER BY id", (tenant, project, kind))]

    def append(self, tenant: str, project: str, kind: str, payload: dict):
        with sqlite3.connect(self.path) as connection:
            connection.execute("INSERT INTO console_records(tenant,project,kind,payload) VALUES(?,?,?,?)", (tenant, project, kind, json.dumps(payload, ensure_ascii=False)))

    def clear_chat(self, tenant: str, project: str):
        with sqlite3.connect(self.path) as connection:
            connection.execute("DELETE FROM console_records WHERE tenant=? AND project=? AND kind='chat'", (tenant, project))


async def reset_chat(settings: Settings, tenant: str, project: str):
    await SQLiteSession(f"console:{tenant}:{project}", settings.suggestion_session_db).clear_session()
    ConsoleState(settings.console_state_db).clear_chat(tenant, project)


async def model_runtime(settings: Settings, client: BackendClient, task: str):
    runtime = await client.get(f"/api/v1/model-config/tasks/{task}/runtime")
    return runtime["model"], settings.quality_backend_url.rstrip("/") + runtime["transport"]





async def chat(settings: Settings, project: str, tenant: str, message: str, mode: str):
    backend = BackendClient(settings.quality_backend_url, tenant)
    llm = None
    try:
        prefix = f"/api/v1/projects/{quote(project, safe='')}"
        await backend.get(prefix)
        model, url = await model_runtime(settings, backend, "agent_chat")
        llm = AsyncOpenAI(base_url=url, api_key="local", timeout=settings.llm_timeout_seconds, max_retries=0)

        query_project_data = create_project_query_tool(backend, prefix)

        agent = create_project_conversation_agent(
            OpenAIChatCompletionsModel(model=model, openai_client=llm), query_project_data, mode)
        session = SQLiteSession(f"console:{tenant}:{project}", settings.suggestion_session_db)
        result = await Runner.run(agent, message, session=session, max_turns=settings.suggestion_max_turns, run_config=RunConfig(tracing_disabled=True))
        answer = ChatAnswer.model_validate(result.final_output)
        state = ConsoleState(settings.console_state_db)
        state.append(tenant, project, "chat", {"role": "user", "content": message})
        state.append(tenant, project, "chat", {"role": "assistant", "content": answer.answer, "evidence": answer.evidence})
        return {"project_id": project, "mode": mode, **answer.model_dump()}
    finally:
        await backend.close()
        if llm:
            await llm.close()


class CanonicalConsoleStore:
    """Adapt restored report service reads to canonical IDs, without data copies."""
    def __init__(self, client: BackendClient, state: ConsoleState):
        self.client, self.state = client, state

    async def get_project(self, project_id):
        data = await self.client.get(f"/api/v1/projects/{quote(project_id, safe='')}")
        return SimpleNamespace(**data, owner=None, status="active")

    async def list_artifacts(self, project_id):
        data = await self.client.get(f"/api/v1/projects/{quote(project_id, safe='')}/artifacts")
        return [SimpleNamespace(id=item["id"], project_id=project_id, kind=item["engineering_role"] or item["modality"], name=item["filename"], path=item["original_file_url"], version=item["revision"], content=None) for item in data]

    async def list_trace_links(self, project_id):
        prefix = f"/api/v1/projects/{quote(project_id, safe='')}/information"
        runs, offset = [], 0
        while True:
            page = await self.client.get(prefix + "/tlr-runs", {"limit": 100, "offset": offset})
            runs.extend(page["items"])
            if not page["has_more"]:
                break
            offset = page["next_offset"]
        run = next((item for item in runs if item["status"] == "completed"), None)
        if run is None:
            return []
        graph = await self.client.get(prefix + f"/tlr-runs/{quote(run['run_id'], safe='')}/visualization")
        nodes = {item["node_id"]: item for item in graph["nodes"]}
        # Current links have no probability/confidence. Do not fabricate one to
        # fit a legacy schema: the untouched report implementation receives None.
        return [SimpleNamespace(id=item["id"], project_id=project_id, source_artifact_id=nodes[item["source_node_id"]]["artifact_id"], target_artifact_id=nodes[item["target_node_id"]]["artifact_id"], relation_type=item["relation"], confidence=None, evidence=json.dumps({"source_node_id": item["source_node_id"], "target_node_id": item["target_node_id"], "quotes": item["evidence"]}, ensure_ascii=False)) for item in graph["links"]]

    async def list_reports(self, project_id):
        return [SimpleNamespace(**{**row, "created_at": datetime.fromisoformat(row["created_at"])}) for row in self.state.records(self.client.tenant_id, project_id, "report")]

    async def add_report(self, report):
        payload = {key: getattr(report, key) for key in ["id", "project_id", "report_type", "title", "focus", "markdown", "highlights", "risks"]}
        payload["created_at"] = datetime.now(UTC).isoformat()
        self.state.append(self.client.tenant_id, report.project_id, "report", payload)
        return payload

    def project_row(self, project, *, artifact_count=0, trace_link_count=0):
        return {"id": project.id, "name": project.name, "description": project.description, "owner": None, "status": "active", "artifact_count": artifact_count, "trace_link_count": trace_link_count}

    def artifact_row(self, item):
        return {"id": item.id, "project_id": item.project_id, "kind": item.kind, "name": item.name, "path": item.path, "version": item.version, "preview": None}

    def trace_link_row(self, item):
        return vars(item)

    def report_row(self, report):
        return {**vars(report), "created_at": report.created_at.isoformat()}


async def peer_service(settings: Settings, tenant: str):
    """Construct teammate's unchanged service only on explicit invocation."""
    from .service import QualityAgentService
    backend = BackendClient(settings.quality_backend_url, tenant)
    try:
        model, url = await model_runtime(settings, backend, "peer_llm")
        configured = settings.model_copy(update={"llm_base_url": url, "llm_api_key": "local", "llm_model": model})
        return QualityAgentService(configured, CanonicalConsoleStore(backend, ConsoleState(settings.console_state_db))), backend
    except BaseException:
        await backend.close()
        raise
