from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ProjectSummary(BaseModel):
    id: str
    name: str
    description: str
    owner: str | None = None
    status: str
    artifact_count: int
    trace_link_count: int


class ArtifactSummary(BaseModel):
    id: str
    project_id: str
    kind: str
    name: str
    path: str
    version: str | None = None
    preview: str | None = None


class TraceLinkSummary(BaseModel):
    id: str
    project_id: str
    source_artifact_name: str
    target_artifact_name: str
    relation_type: str
    confidence: float
    evidence: str | None = None


class ChatRequest(BaseModel):
    # 创建一个 Pydantic 模型类 ChatRequest时, 自动去掉所有变量字符串首尾空格
    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: str
    message: str = Field(min_length=1, max_length=6000)
    mode: Literal["quality", "traceability", "summary"] = "quality"
    history: list[dict[str, Any]] = Field(default_factory=list)


class ChatResponse(BaseModel):
    project_id: str
    mode: str
    answer: str
    evidence: list[str]
    suggested_actions: list[str]


class ReportRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: str
    report_type: Literal["quality_overview", "traceability", "coverage", "custom"] = (
        "quality_overview"
    )
    focus: list[str] = Field(default_factory=list)
    source_kinds: list[str] = Field(default_factory=list)


class ReportResponse(BaseModel):
    project_id: str
    report_type: str
    title: str
    markdown: str
    highlights: list[str]
    risks: list[str]
    report_id: str


class RequirementPoint(BaseModel):
    """One independently actionable requirement."""

    requirement_id: str = Field(pattern=r"^REQ-\d{3,}$")
    statement: str = Field(min_length=1)


class RequirementCandidate(BaseModel):
    statement: str = Field(min_length=1)


class RequirementExtractionResponse(BaseModel):
    source_filename: str
    page_count: int = Field(ge=0)
    project_summary: str
    requirements: list[RequirementPoint]
    warnings: list[str] = Field(default_factory=list)


class DatabaseReadRequest(BaseModel):
    scope: Literal["projects", "artifacts", "trace_links", "reports", "audit_events"]
    project_id: str | None = None
    keyword: str | None = None
    limit: int = Field(default=20, ge=1, le=200)


class DatabaseReadResponse(BaseModel):
    scope: str
    rows: list[dict[str, Any]]
    total: int


class DatabaseWriteRequest(BaseModel):
    operation: Literal[
        "add_project",
        "add_artifact",
        "add_trace_link",
        "append_chat",
        "save_report",
        "log_event",
    ]
    payload: dict[str, Any]


class DatabaseWriteResponse(BaseModel):
    operation: str
    record_id: str
    message: str


class SchemaResponse(BaseModel):
    tables: dict[str, list[str]]
