from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import DateTime, Float, ForeignKey, JSON, String, Text, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, selectinload


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    artifacts: Mapped[list["Artifact"]] = relationship(back_populates="project")
    trace_links: Mapped[list["TraceLink"]] = relationship(back_populates="project")


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    path: Mapped[str] = mapped_column(String(512), nullable=False)
    version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    project: Mapped["Project"] = relationship(back_populates="artifacts")


class TraceLink(Base):
    __tablename__ = "trace_links"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    source_artifact_id: Mapped[str] = mapped_column(ForeignKey("artifacts.id", ondelete="CASCADE"))
    target_artifact_id: Mapped[str] = mapped_column(ForeignKey("artifacts.id", ondelete="CASCADE"))
    relation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.8)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    project: Mapped["Project"] = relationship(back_populates="trace_links")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ReportRun(Base):
    __tablename__ = "report_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    report_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    focus: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    markdown: Mapped[str] = mapped_column(Text, nullable=False)
    highlights: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    risks: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class QualityStore:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.engine: AsyncEngine = create_async_engine(database_url, future=True)
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def initialize(self) -> None:
        self._ensure_storage_root()
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await self.seed_demo_data()

    async def close(self) -> None:
        await self.engine.dispose()

    def _ensure_storage_root(self) -> None:
        data_dir = Path("data")
        data_dir.mkdir(exist_ok=True)

    async def seed_demo_data(self) -> None:
        async with self.sessionmaker() as session:
            count = await session.scalar(select(func.count()).select_from(Project))
            if count and count > 0:
                return

            project = Project(
                id=str(uuid4()),
                name="SQM Demo Platform",
                description="用于软件质量管理演示的样例项目，包含需求、设计、代码、测试和 trace link。",
                owner="quality-lab",
                status="active",
            )
            artifacts = [
                Artifact(
                    id=str(uuid4()),
                    project=project,
                    kind="requirement",
                    name="requirements.md",
                    path="docs/requirements.md",
                    version="v1.0",
                    content="系统应支持项目级质量报告、数据库读写、对话分析和追踪关系管理。",
                    meta={"source": "lifecycle"},
                ),
                Artifact(
                    id=str(uuid4()),
                    project=project,
                    kind="design",
                    name="architecture.md",
                    path="docs/architecture.md",
                    version="v1.0",
                    content="后端采用 FastAPI + SQLAlchemy + SQLite，前端采用 React + Vite + TypeScript。",
                    meta={"source": "lifecycle"},
                ),
                Artifact(
                    id=str(uuid4()),
                    project=project,
                    kind="code",
                    name="quality_report.py",
                    path="src/quality/report.py",
                    version="v1.0",
                    content="负责汇总文档、代码、测试和 trace link，生成项目质量报告。",
                    meta={"source": "repo"},
                ),
                Artifact(
                    id=str(uuid4()),
                    project=project,
                    kind="test",
                    name="test_report.py",
                    path="tests/test_report.py",
                    version="v1.0",
                    content="验证报告结构、风险提示和建议是否完整。",
                    meta={"source": "repo"},
                ),
            ]
            trace_link = TraceLink(
                id=str(uuid4()),
                project=project,
                source_artifact_id=artifacts[0].id,
                target_artifact_id=artifacts[2].id,
                relation_type="implements",
                confidence=0.92,
                evidence="需求明确要求报告与数据库读写能力，代码资产实现该功能。",
            )
            session.add_all([project, *artifacts, trace_link])
            session.add(
                AuditEvent(
                    id=str(uuid4()),
                    operation="seed_demo_data",
                    payload={"project": project.name},
                    result={"artifact_count": len(artifacts)},
                )
            )
            await session.commit()

    async def list_projects(self) -> list[Project]:
        async with self.sessionmaker() as session:
            result = await session.execute(
                select(Project)
                .options(selectinload(Project.artifacts), selectinload(Project.trace_links))
                .order_by(Project.created_at.desc())
            )
            return list(result.scalars().all())

    async def get_project(self, project_id: str) -> Project | None:
        async with self.sessionmaker() as session:
            return await session.get(Project, project_id)

    async def add_project(
        self,
        *,
        name: str,
        description: str,
        owner: str | None,
        status: str,
    ) -> dict[str, Any]:
        async with self.sessionmaker() as session:
            project = Project(
                id=str(uuid4()),
                name=name,
                description=description,
                owner=owner,
                status=status,
            )
            session.add(project)
            await session.commit()
            return self.project_row(project)

    async def add_artifact(
        self,
        *,
        project_id: str,
        kind: str,
        name: str,
        path: str,
        version: str | None,
        content: str | None,
        meta: dict[str, Any],
    ) -> dict[str, Any]:
        async with self.sessionmaker() as session:
            artifact = Artifact(
                id=str(uuid4()),
                project_id=project_id,
                kind=kind,
                name=name,
                path=path,
                version=version,
                content=content,
                meta=meta,
            )
            session.add(artifact)
            await session.commit()
            return self.artifact_row(artifact)

    async def add_trace_link(
        self,
        *,
        project_id: str,
        source_artifact_id: str,
        target_artifact_id: str,
        relation_type: str,
        confidence: float,
        evidence: str | None,
    ) -> dict[str, Any]:
        async with self.sessionmaker() as session:
            link = TraceLink(
                id=str(uuid4()),
                project_id=project_id,
                source_artifact_id=source_artifact_id,
                target_artifact_id=target_artifact_id,
                relation_type=relation_type,
                confidence=confidence,
                evidence=evidence,
            )
            session.add(link)
            await session.commit()
            return self.trace_link_row(link)

    async def list_artifacts(self, project_id: str | None = None) -> list[Artifact]:
        async with self.sessionmaker() as session:
            stmt = select(Artifact).order_by(Artifact.created_at.desc())
            if project_id:
                stmt = stmt.where(Artifact.project_id == project_id)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def list_trace_links(self, project_id: str | None = None) -> list[TraceLink]:
        async with self.sessionmaker() as session:
            stmt = select(TraceLink).order_by(TraceLink.created_at.desc())
            if project_id:
                stmt = stmt.where(TraceLink.project_id == project_id)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def list_reports(self, project_id: str | None = None) -> list[ReportRun]:
        async with self.sessionmaker() as session:
            stmt = select(ReportRun).order_by(ReportRun.created_at.desc())
            if project_id:
                stmt = stmt.where(ReportRun.project_id == project_id)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def list_chat_messages(self, project_id: str | None = None) -> list[ChatMessage]:
        async with self.sessionmaker() as session:
            stmt = select(ChatMessage).order_by(ChatMessage.created_at.asc())
            if project_id:
                stmt = stmt.where(ChatMessage.project_id == project_id)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def add_chat_message(
        self, project_id: str, role: str, content: str, evidence: list[str] | None = None
    ) -> dict[str, Any]:
        async with self.sessionmaker() as session:
            message = ChatMessage(
                id=str(uuid4()),
                project_id=project_id,
                role=role,
                content=content,
                evidence=evidence or [],
            )
            session.add(message)
            session.add(
                AuditEvent(
                    id=str(uuid4()),
                    operation="append_chat",
                    payload={"project_id": project_id, "role": role},
                    result={"message_id": message.id},
                )
            )
            await session.commit()
            return self.chat_row(message)

    async def add_report(self, report: ReportRun) -> dict[str, Any]:
        async with self.sessionmaker() as session:
            session.add(report)
            session.add(
                AuditEvent(
                    id=str(uuid4()),
                    operation="save_report",
                    payload={"project_id": report.project_id, "report_type": report.report_type},
                    result={"report_id": report.id},
                )
            )
            await session.commit()
            return self.report_row(report)

    async def add_audit_event(
        self, operation: str, payload: dict[str, Any], result: dict[str, Any]
    ) -> dict[str, Any]:
        async with self.sessionmaker() as session:
            event = AuditEvent(
                id=str(uuid4()),
                operation=operation,
                payload=payload,
                result=result,
            )
            session.add(event)
            await session.commit()
            return self.audit_row(event)

    async def read_scope(self, scope: str, project_id: str | None = None, keyword: str | None = None):
        if scope == "projects":
            rows = await self.list_projects()
            data = [self.project_row(item) for item in rows]
        elif scope == "artifacts":
            rows = await self.list_artifacts(project_id)
            data = [self.artifact_row(item) for item in rows]
        elif scope == "trace_links":
            rows = await self.list_trace_links(project_id)
            data = [self.trace_link_row(item) for item in rows]
        elif scope == "reports":
            rows = await self.list_reports(project_id)
            data = [self.report_row(item) for item in rows]
        else:
            rows = await self._list_audits()
            data = [self.audit_row(item) for item in rows]

        if keyword:
            keyword = keyword.lower()
            data = [row for row in data if keyword in str(row).lower()]
        return data

    async def _list_audits(self) -> list[AuditEvent]:
        async with self.sessionmaker() as session:
            result = await session.execute(select(AuditEvent).order_by(AuditEvent.created_at.desc()))
            return list(result.scalars().all())

    async def get_schema(self) -> dict[str, list[str]]:
        return {
            "projects": ["id", "name", "description", "owner", "status", "created_at"],
            "artifacts": ["id", "project_id", "kind", "name", "path", "version", "content", "meta"],
            "trace_links": [
                "id",
                "project_id",
                "source_artifact_id",
                "target_artifact_id",
                "relation_type",
                "confidence",
                "evidence",
            ],
            "chat_messages": ["id", "project_id", "role", "content", "evidence", "created_at"],
            "report_runs": ["id", "project_id", "report_type", "title", "focus", "markdown"],
            "audit_events": ["id", "operation", "payload", "result", "created_at"],
        }

    def project_row(
        self,
        project: Project,
        *,
        artifact_count: int | None = None,
        trace_link_count: int | None = None,
    ) -> dict[str, Any]:
        if artifact_count is None:
            artifact_count = len(project.__dict__.get("artifacts") or [])
        if trace_link_count is None:
            trace_link_count = len(project.__dict__.get("trace_links") or [])
        return {
            "id": project.id,
            "name": project.name,
            "description": project.description,
            "owner": project.owner,
            "status": project.status,
            "artifact_count": artifact_count,
            "trace_link_count": trace_link_count,
        }

    def artifact_row(self, artifact: Artifact) -> dict[str, Any]:
        return {
            "id": artifact.id,
            "project_id": artifact.project_id,
            "kind": artifact.kind,
            "name": artifact.name,
            "path": artifact.path,
            "version": artifact.version,
            "preview": artifact.content[:180] if artifact.content else None,
        }

    def trace_link_row(self, link: TraceLink) -> dict[str, Any]:
        return {
            "id": link.id,
            "project_id": link.project_id,
            "source_artifact_id": link.source_artifact_id,
            "target_artifact_id": link.target_artifact_id,
            "relation_type": link.relation_type,
            "confidence": link.confidence,
            "evidence": link.evidence,
        }

    def chat_row(self, message: ChatMessage) -> dict[str, Any]:
        return {
            "id": message.id,
            "project_id": message.project_id,
            "role": message.role,
            "content": message.content,
            "evidence": message.evidence,
            "created_at": message.created_at.isoformat(),
        }

    def report_row(self, report: ReportRun) -> dict[str, Any]:
        return {
            "id": report.id,
            "project_id": report.project_id,
            "report_type": report.report_type,
            "title": report.title,
            "focus": report.focus,
            "created_at": report.created_at.isoformat(),
        }

    def audit_row(self, event: AuditEvent) -> dict[str, Any]:
        return {
            "id": event.id,
            "operation": event.operation,
            "payload": event.payload,
            "result": event.result,
            "created_at": event.created_at.isoformat(),
        }
