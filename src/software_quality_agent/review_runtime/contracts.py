"""contracts definitions for the SDK review workflow."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EvidenceReference(BaseModel):
    kind: Literal[
        "review_evidence", "overall_evidence", "canonical_node", "tlr_candidate", "web_source"
    ]
    identifier: str = Field(min_length=1)
    node_id: str | None = None
    check_id: str | None = None
    candidate_id: str | None = None
    trace_link_id: str | None = None
    run_id: str | None = None
    artifact_id: str | None = None
    quote: str | None = Field(default=None, max_length=4000)
    relation: Literal["supporting", "counter", "context"] | None = None
    url: str | None = None


class SuggestionEvidenceInput(BaseModel):
    """模型引用已保存证据或结构位置；程序负责解析真实归属。"""

    kind: Literal["review_evidence", "overall_evidence", "canonical_node", "web_source"]
    identifier: str = Field(min_length=1, description="已返回的 evidence_id；canonical_node 时填写 location，例如 设计文档1:/2/4；外部资料填写网址")
    check_id: str | None = None
    quote: str | None = Field(default=None, max_length=4000)
    relation: Literal["supporting", "counter", "context"] | None = None
    url: str | None = None


class SuggestionOutput(BaseModel):
    """The only successful model output; blocked runs never contain a suggestion."""

    execution_status: Literal["completed", "unresolved", "blocked"]
    attempt: int | None = None
    attempt_id: str | None = None
    review_id: str
    sentence_id: str
    problem_summary: str = ""
    suggestion_text: str = ""
    rationale: str = ""
    affected_check_ids: list[str] = Field(default_factory=list)
    affected_issue_ids: list[str] = Field(default_factory=list)
    evidence: list[EvidenceReference] = Field(default_factory=list, max_length=40)
    web_sources: list[EvidenceReference] = Field(default_factory=list, max_length=20)
    unresolved_questions: list[str] = Field(default_factory=list, max_length=20)
    work_note_ids: list[str] = Field(default_factory=list, max_length=50)
    error_code: str | None = None
    error_message: str | None = None
    investigation_scope: dict[str, Any] = Field(default_factory=dict)


class SuggestionValidation(BaseModel):
    review_id: str
    sentence_id: str
    valid: bool
    issues: list[str] = Field(default_factory=list, max_length=30)
    required_revision: str = ""


class SuggestionDraft(BaseModel):
    review_id: str
    sentence_id: str
    segment_id: str
    assessment_fingerprint: str = ""
    problem_summary: str = ""
    suggestion_text: str = ""
    rationale: str = ""
    check_ids: list[str] = Field(default_factory=list, max_length=50)
    issue_ids: list[str] = Field(default_factory=list)
    evidence: list[EvidenceReference] = Field(default_factory=list, max_length=40)
    unresolved_questions: list[str] = Field(default_factory=list, max_length=20)


class ReviewAnalysisTask(BaseModel):
    """调度宿主已绑定的当前语段；任务身份不由模型选择。"""

    model_config = ConfigDict(extra="forbid")


class EvidenceInvestigationTask(ReviewAnalysisTask):
    investigation_goal: str = Field(min_length=1, max_length=2000)
    # Review Analysis must select a concrete structure location after using the
    # directory/summary tools; the bounded investigator does not pick a vague
    # search target on the model's behalf.
    location: str = Field(min_length=1, max_length=500)


class PassageQuote(BaseModel):
    """模型提供逐字引文，由确定性代码定位 canonical 原文范围。"""

    exact_quote: str = Field(min_length=1)


class PassageCheckAssessment(BaseModel):
    check_id: str
    relation: Literal["supporting", "counter", "context", "irrelevant", "needs_context"]
    status: Literal["pending", "supported", "contradicted", "insufficient", "uncertain"]
    note: str = Field(min_length=1, max_length=2000)
    quotes: list[PassageQuote] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def discard_unused_quotes(cls, value):
        if isinstance(value, dict) and value.get("relation") in {"irrelevant", "needs_context"}:
            return {**value, "quotes": []}
        return value


class CheckConclusion(BaseModel):
    check_id: str
    status: Literal["supported", "contradicted", "insufficient", "uncertain"]
    note: str = Field(min_length=1, max_length=2000)


class OverallQuote(BaseModel):
    location: str = Field(description="结构查询返回的设计原文 location，不是节点 UUID 或标题编号")
    exact_quote: str = Field(min_length=1)


class OverallIssue(BaseModel):
    """有独立证据的整体语段问题，不是逐个异常检查点的复制。"""

    kind: Literal["conflict", "omission", "clarification", "aggregate"]
    statement: str = Field(min_length=1)
    source_quote: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    check_ids: list[str] = Field(default_factory=list)
    evidence: list[OverallQuote] = Field(default_factory=list)


class SuggestionValidationTask(ReviewAnalysisTask):
    check_ids: list[str] = Field(default_factory=list, max_length=50)


class WebResearchTask(ReviewAnalysisTask):
    """外部资料调查参数；外部内容永远不能作为 canonical 证据。"""

    query: str = Field(min_length=1, max_length=500)
    purpose: str = Field(default="澄清拟议修改建议", max_length=500)


class SuggestionTask(ReviewAnalysisTask):
    check_ids: list[str] = Field(default_factory=list, max_length=50)
    validator_feedback: str = Field(default="", max_length=4000)


class SuggestionRequest(BaseModel):
    project_id: str = Field(min_length=1)
    review_id: str = Field(min_length=1)
    sentence_ids: list[str] | None = None
    tenant_id: str = "local"
    worker_token: str | None = None
    execution_attempt_id: str | None = None
    review_pipeline: Literal["fixed_tlr", "full_investigation"] | None = None
