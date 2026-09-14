from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import re
from typing import Any
from uuid import uuid4

import httpx

from .config import Settings
from .schemas import (
    ChatRequest,
    ChatResponse,
    DatabaseReadRequest,
    DatabaseReadResponse,
    DatabaseWriteRequest,
    DatabaseWriteResponse,
    ReportRequest,
    ReportResponse,
    RequirementCandidate,
    RequirementExtractionResponse,
    RequirementPoint,
)
from .store import Artifact, Project, QualityStore, ReportRun, TraceLink


class LLMClient:
    async def chat(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_format: dict[str, Any] | None = None,
        max_tokens: int | None = None,
    ) -> str:  # pragma: no cover
        raise NotImplementedError


class LLMResponseTruncated(ValueError):
    pass


class OpenAICompatibleLLMClient(LLMClient):
    def __init__(self, *, base_url: str, api_key: str, model: str, timeout_seconds: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    async def chat(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_format: dict[str, Any] | None = None,
        max_tokens: int | None = None,
    ) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if response_format:
            payload["response_format"] = response_format
        if max_tokens:
            payload["max_tokens"] = max_tokens
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self.api_key:
            headers.update({"Authorization": "Bearer " + self.api_key})
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}
        headers["Authorization"] = f"Bearer {self.api_key}"
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + self.api_key,
        }
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        choices = data.get("choices") or []
        if not choices:
            raise ValueError("LLM 响应缺少 choices 字段")
        choice = choices[0]
        message = choice.get("message") or {}
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content
        finish_reason = choice.get("finish_reason", "unknown")
        refusal = message.get("refusal")
        detail = f"finish_reason={finish_reason}"
        if refusal:
            detail += f", refusal={refusal}"
        if finish_reason == "length":
            raise LLMResponseTruncated(f"LLM 返回空内容（{detail}）")
        raise ValueError(f"LLM 返回空内容（{detail}）")


@dataclass(slots=True)
class EvidenceBundle:
    project: dict[str, Any]
    artifacts: list[dict[str, Any]]
    trace_links: list[dict[str, Any]]
    gaps: list[str]
    stats: dict[str, int]


class EvidenceAgent:
    def __init__(self, store: QualityStore) -> None:
        self.store = store

    async def collect(self, project: Project) -> EvidenceBundle:
        artifacts = await self.store.list_artifacts(project.id)
        links = await self.store.list_trace_links(project.id)
        artifact_rows = [self.store.artifact_row(item) for item in artifacts]
        link_rows = [self.store.trace_link_row(item) for item in links]
        kinds = {item["kind"] for item in artifact_rows}
        gaps: list[str] = []

        if "requirement" not in kinds:
            gaps.append("缺少需求类生命周期文档")
        if "design" not in kinds:
            gaps.append("缺少设计类生命周期文档")
        if "code" not in kinds:
            gaps.append("缺少代码资产")
        if "test" not in kinds:
            gaps.append("缺少测试资产")
        if not link_rows:
            gaps.append("缺少 trace link")

        stats = {
            "artifact_count": len(artifact_rows),
            "trace_link_count": len(link_rows),
            "report_count": len(await self.store.list_reports(project.id)),
        }
        if stats["artifact_count"] and stats["trace_link_count"] < max(1, stats["artifact_count"] // 2):
            gaps.append("trace link 覆盖偏弱")

        return EvidenceBundle(
            project=self.store.project_row(
                project,
                artifact_count=len(artifact_rows),
                trace_link_count=len(link_rows),
            ),
            artifacts=artifact_rows,
            trace_links=link_rows,
            gaps=gaps,
            stats=stats,
        )


class ConversationAgent:
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    async def answer(self, request: ChatRequest, evidence: EvidenceBundle) -> ChatResponse:
        system_prompt = self._system_prompt(request.mode)
        user_prompt = self._compose_prompt(request, evidence)
        answer = await self.llm.chat(system_prompt=system_prompt, user_prompt=user_prompt)
        if not answer.strip() or answer.strip() == user_prompt.strip():
            answer = self._fallback_answer(request, evidence)
        return ChatResponse(
            project_id=request.project_id,
            mode=request.mode,
            answer=answer,
            evidence=self._evidence_labels(evidence),
            suggested_actions=self._suggestions(evidence),
        )

    def _system_prompt(self, mode: str) -> str:
        prompts = {
            "quality": "你是软件质量管理助手，重点回答文档、代码、测试、追踪关系和风险。",
            "traceability": "你是需求追踪助手，重点分析需求-设计-代码-测试的一致性与覆盖。",
            "summary": "你是项目摘要助手，输出简洁、结构化、可执行的判断。",
        }
        return prompts.get(mode, prompts["quality"])

    def _compose_prompt(self, request: ChatRequest, evidence: EvidenceBundle) -> str:
        history_text = "\n".join(f"{item.get('role')}: {item.get('content')}" for item in request.history[-6:])
        return (
            f"项目：{evidence.project['name']}\n"
            f"用户问题：{request.message}\n"
            f"最近对话：\n{history_text or '无'}\n"
            f"资产：{evidence.artifacts}\n"
            f"trace link：{evidence.trace_links}\n"
            f"质量缺口：{evidence.gaps}\n"
            f"统计：{evidence.stats}"
        )

    def _fallback_answer(self, request: ChatRequest, evidence: EvidenceBundle) -> str:
        lines = [
            f"项目 `{evidence.project['name']}` 当前有 {evidence.stats['artifact_count']} 个资产和 {evidence.stats['trace_link_count']} 条追踪关系。",
            f"你关注的问题是：{request.message}",
        ]
        if evidence.gaps:
            lines.append("当前主要缺口：" + "；".join(evidence.gaps))
        else:
            lines.append("当前文档、代码、测试和追踪关系看起来比较齐全。")
        lines.append("建议优先补齐需求、设计、代码、测试之间的 trace link，再做覆盖分析。")
        return "\n".join(lines)

    def _evidence_labels(self, evidence: EvidenceBundle) -> list[str]:
        labels = [artifact["name"] for artifact in evidence.artifacts[:5]]
        labels.extend(
            f"{item['source_artifact_id']} -> {item['target_artifact_id']}" for item in evidence.trace_links[:5]
        )
        return labels

    def _suggestions(self, evidence: EvidenceBundle) -> list[str]:
        suggestions = [
            "补齐需求-设计-代码-测试追踪关系",
            "检查生命周期文档之间的一致性",
            "生成覆盖分析报告",
        ]
        if evidence.gaps:
            suggestions.insert(0, f"优先处理：{evidence.gaps[0]}")
        return suggestions


class ReportAgent:
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    async def generate(self, request: ReportRequest, evidence: EvidenceBundle) -> ReportResponse:
        markdown = await self.llm.chat(
            system_prompt="你是软件质量报告写作助手，输出结构化 Markdown，并给出风险和建议。",
            user_prompt=self._compose_prompt(request, evidence),
        )
        if not markdown.strip() or "#" not in markdown:
            markdown = self._fallback_markdown(request, evidence)
        title = self._title_for(request.report_type)
        highlights = [
            f"资产数：{len(evidence.artifacts)}",
            f"追踪关系数：{len(evidence.trace_links)}",
            f"缺口数：{len(evidence.gaps)}",
        ]
        risks = evidence.gaps or ["建议补齐 trace link 和测试覆盖证据"]
        return ReportResponse(
            project_id=request.project_id,
            report_type=request.report_type,
            title=title,
            markdown=markdown,
            highlights=highlights,
            risks=risks,
            report_id=str(uuid4()),
        )

    def _compose_prompt(self, request: ReportRequest, evidence: EvidenceBundle) -> str:
        return (
            f"项目：{evidence.project['name']}\n"
            f"报告类型：{request.report_type}\n"
            f"关注点：{', '.join(request.focus) or '整体质量'}\n"
            f"资产：{evidence.artifacts}\n"
            f"追踪关系：{evidence.trace_links}\n"
            f"缺口：{evidence.gaps}\n"
            f"统计：{evidence.stats}"
        )

    def _fallback_markdown(self, request: ReportRequest, evidence: EvidenceBundle) -> str:
        artifact_lines = "\n".join(
            f"- {item['kind']}: {item['name']} (`{item['path']}`)" for item in evidence.artifacts
        ) or "- 无"
        link_lines = "\n".join(
            f"- {item['source_artifact_id']} -> {item['target_artifact_id']} ({item['relation_type']}, {item['confidence']:.2f})"
            for item in evidence.trace_links
        ) or "- 暂无 trace link"
        gap_lines = "\n".join(f"- {gap}" for gap in evidence.gaps) or "- 暂无明显缺口"
        focus_lines = "\n".join(f"- {item}" for item in request.focus) or "- 全局质量"
        return f"""# {self._title_for(request.report_type)}

## 项目概览
{evidence.project['description']}

## 关注点
{focus_lines}

## 资产清单
{artifact_lines}

## 追踪关系
{link_lines}

## 质量缺口
{gap_lines}

## 建议
- 补齐需求、设计、代码、测试之间的 trace link
- 对高风险需求补充测试覆盖证据
- 将变更记录和审计事件纳入质量门禁
"""

    def _title_for(self, report_type: str) -> str:
        mapping = {
            "quality_overview": "项目质量总览报告",
            "traceability": "需求追踪分析报告",
            "coverage": "测试覆盖分析报告",
            "custom": "项目质量专题报告",
        }
        return mapping[report_type]


class RequirementDecompositionAgent:
    """Extracts and consolidates requirements into code-sized business capabilities."""

    batch_char_limit = 6000
    max_concurrency = 4
    consolidation_char_limit = 16000

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm
        self._semaphore = asyncio.Semaphore(self.max_concurrency)

    async def decompose(
        self,
        *,
        source_filename: str,
        page_count: int,
        page_text: list[str],
    ) -> RequirementExtractionResponse:
        batches = self._build_paragraph_batches(page_text)
        if not batches:
            raise ValueError("PDF 未提取到可分析的文本，可能是扫描件，请先进行 OCR")

        # await asyncio 表示把多个异步任务一起执行
        batch_results = await asyncio.gather(
            *(self._extract_batch(index, batch) for index, batch in enumerate(batches, start=1))
        )
        
        statements = self._deduplicate(
            statement
            for result in batch_results
            for statement in result
        )
        statements = await self._consolidate(statements)
        requirements = [
            RequirementPoint(
                requirement_id=f"REQ-{index:03d}",
                statement=statement,
            )
            for index, statement in enumerate(statements, start=1)
        ]
        return RequirementExtractionResponse(
            source_filename=source_filename,
            page_count=page_count,
            project_summary="已通过本地段落分批和 LLM 需求识别完成项目需求提取。",
            requirements=requirements,
            warnings=[],
        )

    def _build_paragraph_batches(self, page_text: list[str]) -> list[str]:
        paragraphs: list[str] = []
        for page_number, text in enumerate(page_text, start=1):
            for paragraph in re.split(r"\n\s*\n+|\n(?=\s*(?:[-*•]|\d+[.)、]))", text):
                cleaned = " ".join(paragraph.split())
                if len(cleaned) >= 8:
                    paragraphs.append(f"[第 {page_number} 页] {cleaned}")

        batches: list[str] = []
        current: list[str] = []
        current_length = 0
        for paragraph in paragraphs:
            if current and current_length + len(paragraph) + 1 > self.batch_char_limit:
                batches.append("\n".join(current))
                current = []
                current_length = 0
            current.append(paragraph)
            current_length += len(paragraph) + 1
        if current:
            batches.append("\n".join(current))
        return batches

    async def _extract_batch(self, index: int, batch: str) -> list[str]:
        async with self._semaphore:
            answer = await self.llm.chat(
                system_prompt=(
                    "你是软件需求分析师。只提取明确、可实现的业务能力。"
                    "一条需求应对应一个完整功能、接口或业务流程，而不是一个字段、"
                    "一个按钮、一个校验规则或一个异常分支。"
                    "同一功能的输入、处理、输出、权限和异常处理必须合并为一条需求。"
                    "忽略背景、愿景、价值描述、技术建议和重复内容。"
                    "每条需求用一句完整的话描述，必须返回合法 JSON，不要 Markdown。"
                ),
                user_prompt=(
                    f"这是第 {index} 批项目文档段落。\n"
                    '返回格式：{"requirements":[{"statement":"系统应..."}]}\n'
                    "如果没有明确需求，返回 {\"requirements\":[]}。\n\n"
                    f"文档段落：\n{batch}"
                ),
                response_format={"type": "json_object"},
                max_tokens=2500,
            )
        data = self._load_json(answer, stage=f"Requirement batch {index}")
        results: list[str] = []
        for item in data.get("requirements", []):
            candidate = RequirementCandidate.model_validate(item)
            results.append(candidate.statement)
        return results

    async def _consolidate(self, statements: list[str]) -> list[str]:
        """Merge fine-grained candidates into independently implementable capabilities."""
        if len(statements) < 2:
            return statements

        numbered = "\n".join(
            f"{index}. {statement}" for index, statement in enumerate(statements, start=1)
        )
        if len(numbered) > self.consolidation_char_limit:
            raise ValueError(
                "需求候选过多，无法在一次语义合并中处理；请缩小 PDF 批次后重试"
            )

        answer = await self.llm.chat(
            system_prompt=(
                "你是需求架构师，负责把候选需求整理成适合代码覆盖分析的需求单元。"
                "请合并属于同一个业务能力、接口、服务或完整流程的细小需求。"
                "例如“输入账号”“校验密码”“生成登录令牌”“登录失败提示”"
                "应合并为一条“用户登录功能”，因为它们通常由同一组代码共同实现。"
                "只有在两个需求可以由不同模块独立开发、独立测试时才保留为两条。"
                "不要把一个完整功能拆成输入、处理、输出和异常四条。"
                "不要合并两个无关业务能力，不要凭空添加文档中没有的能力。"
                "每条结果应是一句完整的业务需求，保留必要的范围和约束。"
                "必须返回合法 JSON，不要 Markdown。"
            ),
            user_prompt=(
                "请整理下面的候选需求。\n"
                '返回格式：{"requirements":[{"statement":"系统应..."}]}\n'
                "要求：合并过细的需求；删除重复需求；保留相互独立的功能；"
                "输出结果应比输入更接近一个需求对应一组可实现代码。\n\n"
                f"候选需求：\n{numbered}"
            ),
            response_format={"type": "json_object"},
            max_tokens=3000,
        )
        data = self._load_json(answer, stage="Requirement consolidation")
        consolidated: list[str] = []
        for item in data.get("requirements", []):
            candidate = RequirementCandidate.model_validate(item)
            consolidated.append(candidate.statement)
        if not consolidated:
            raise ValueError("Requirement consolidation 阶段未返回任何需求")
        return self._deduplicate(consolidated)

    def _deduplicate(self, statements: Any) -> list[str]:
        unique: list[str] = []
        seen: set[str] = set()
        for statement in statements:
            normalized = re.sub(r"\s+", "", statement).strip("。.!！?？")
            if normalized and normalized not in seen:
                seen.add(normalized)
                unique.append(statement.strip())
        return unique

    def _load_json(self, answer: str, *, stage: str) -> dict[str, Any]:
        if not answer.strip():
            raise ValueError(f"{stage} 阶段的 LLM 返回为空")
        try:
            data = json.loads(answer)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{stage} 阶段的 LLM 返回不是合法 JSON") from exc
        if not isinstance(data, dict):
            raise ValueError(f"{stage} 阶段的 LLM 返回结果不是 JSON 对象")
        return data


class DatabaseReadAgent:
    def __init__(self, store: QualityStore) -> None:
        self.store = store

    async def read(self, request: DatabaseReadRequest) -> DatabaseReadResponse:
        rows = await self.store.read_scope(request.scope, request.project_id, request.keyword)
        return DatabaseReadResponse(scope=request.scope, rows=rows[: request.limit], total=len(rows))


class DatabaseWriteAgent:
    def __init__(self, store: QualityStore) -> None:
        self.store = store

    async def write(self, request: DatabaseWriteRequest) -> DatabaseWriteResponse:
        if request.operation == "add_project":
            return await self._add_project(request.payload)
        if request.operation == "add_artifact":
            return await self._add_artifact(request.payload)
        if request.operation == "add_trace_link":
            return await self._add_trace_link(request.payload)
        if request.operation == "append_chat":
            return await self._append_chat(request.payload)
        if request.operation == "save_report":
            return await self._save_report(request.payload)
        return await self._log_event(request.payload)

    async def _add_project(self, payload: dict[str, Any]) -> DatabaseWriteResponse:
        project = await self.store.add_project(
            name=str(payload["name"]),
            description=str(payload.get("description", "")),
            owner=payload.get("owner"),
            status=str(payload.get("status", "active")),
        )
        return DatabaseWriteResponse(operation="add_project", record_id=project["id"], message="项目已写入")

    async def _add_artifact(self, payload: dict[str, Any]) -> DatabaseWriteResponse:
        artifact = await self.store.add_artifact(
            project_id=str(payload["project_id"]),
            kind=str(payload["kind"]),
            name=str(payload["name"]),
            path=str(payload["path"]),
            version=payload.get("version"),
            content=payload.get("content"),
            meta=payload.get("meta", {}),
        )
        return DatabaseWriteResponse(operation="add_artifact", record_id=artifact["id"], message="资产已写入")

    async def _add_trace_link(self, payload: dict[str, Any]) -> DatabaseWriteResponse:
        link = await self.store.add_trace_link(
            project_id=str(payload["project_id"]),
            source_artifact_id=str(payload["source_artifact_id"]),
            target_artifact_id=str(payload["target_artifact_id"]),
            relation_type=str(payload.get("relation_type", "related")),
            confidence=float(payload.get("confidence", 0.8)),
            evidence=payload.get("evidence"),
        )
        return DatabaseWriteResponse(operation="add_trace_link", record_id=link["id"], message="追踪关系已写入")

    async def _append_chat(self, payload: dict[str, Any]) -> DatabaseWriteResponse:
        message = await self.store.add_chat_message(
            project_id=str(payload["project_id"]),
            role=str(payload.get("role", "user")),
            content=str(payload["content"]),
            evidence=list(payload.get("evidence", [])),
        )
        return DatabaseWriteResponse(operation="append_chat", record_id=message["id"], message="对话已记录")

    async def _save_report(self, payload: dict[str, Any]) -> DatabaseWriteResponse:
        report = ReportRun(
            id=str(uuid4()),
            project_id=str(payload["project_id"]),
            report_type=str(payload["report_type"]),
            title=str(payload["title"]),
            focus=list(payload.get("focus", [])),
            markdown=str(payload["markdown"]),
            highlights=list(payload.get("highlights", [])),
            risks=list(payload.get("risks", [])),
        )
        saved = await self.store.add_report(report)
        return DatabaseWriteResponse(operation="save_report", record_id=saved["id"], message="报告已保存")

    async def _log_event(self, payload: dict[str, Any]) -> DatabaseWriteResponse:
        event = await self.store.add_audit_event(
            str(payload.get("operation", "log_event")),
            payload,
            {"ok": True},
        )
        return DatabaseWriteResponse(operation="log_event", record_id=event["id"], message="事件已记录")


class VerifierAgent:
    def verify_report(self, response: ReportResponse) -> list[str]:
        issues: list[str] = []
        if not response.markdown.strip():
            issues.append("报告内容为空")
        if "##" not in response.markdown:
            issues.append("报告缺少分节结构")
        if not response.highlights:
            issues.append("报告缺少高亮信息")
        if not response.risks:
            issues.append("报告缺少风险提示")
        return issues


class OrchestratorAgent:
    def __init__(
        self,
        *,
        conversation_agent: ConversationAgent,
        report_agent: ReportAgent,
        read_agent: DatabaseReadAgent,
        write_agent: DatabaseWriteAgent,
        evidence_agent: EvidenceAgent,
        verifier_agent: VerifierAgent,
        requirement_agent: RequirementDecompositionAgent,
    ) -> None:
        self.conversation_agent = conversation_agent
        self.report_agent = report_agent
        self.read_agent = read_agent
        self.write_agent = write_agent
        self.evidence_agent = evidence_agent
        self.verifier_agent = verifier_agent
        self.requirement_agent = requirement_agent

    async def handle_chat(self, request: ChatRequest, project: Project) -> ChatResponse:
        evidence = await self.evidence_agent.collect(project)
        return await self.conversation_agent.answer(request, evidence)

    async def handle_report(self, request: ReportRequest, project: Project) -> ReportResponse:
        evidence = await self.evidence_agent.collect(project)
        response = await self.report_agent.generate(request, evidence)
        issues = self.verifier_agent.verify_report(response)
        if issues:
            response.markdown += "\n\n## 校验提示\n" + "\n".join(f"- {issue}" for issue in issues)
        return response

    async def handle_db_read(self, request: DatabaseReadRequest) -> DatabaseReadResponse:
        return await self.read_agent.read(request)

    async def handle_db_write(self, request: DatabaseWriteRequest) -> DatabaseWriteResponse:
        return await self.write_agent.write(request)

    async def handle_requirement_extraction(
        self,
        *,
        source_filename: str,
        page_count: int,
        page_text: list[str],
    ) -> RequirementExtractionResponse:
        return await self.requirement_agent.decompose(
            source_filename=source_filename,
            page_count=page_count,
            page_text=page_text,
        )
