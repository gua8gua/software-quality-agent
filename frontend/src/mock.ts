import type { ChatMessage, DatabaseSchema, ProjectSummary, ReportSummary } from "./types";

export const mockProjects: ProjectSummary[] = [
  {
    id: "sqm-demo-platform",
    name: "SQM Demo Platform",
    description: "用于软件质量管理演示的样例项目，包含需求、设计、代码、测试和 trace link。",
    owner: "quality-lab",
    status: "active",
    artifact_count: 4,
    trace_link_count: 1,
  },
  {
    id: "release-audit-service",
    name: "Release Audit Service",
    description: "面向发布审计和质量门禁的样例项目。",
    owner: "platform-team",
    status: "active",
    artifact_count: 3,
    trace_link_count: 2,
  },
];

export const mockSchema: DatabaseSchema = {
  tables: {
    projects: ["id", "name", "description", "owner", "status", "created_at"],
    artifacts: ["id", "project_id", "kind", "name", "path", "version", "content", "meta"],
    trace_links: [
      "id",
      "project_id",
      "source_artifact_id",
      "target_artifact_id",
      "relation_type",
      "confidence",
      "evidence",
    ],
    chat_messages: ["id", "project_id", "role", "content", "evidence", "created_at"],
    report_runs: ["id", "project_id", "report_type", "title", "focus", "markdown"],
    audit_events: ["id", "operation", "payload", "result", "created_at"],
  },
};

export const mockMessages: ChatMessage[] = [
  {
    role: "assistant",
    content:
      "请选择一个项目，我会根据它的文档、代码、测试和 trace link 做质量判断，并给出下一步建议。",
    evidence: ["requirements.md", "architecture.md", "quality_report.py"],
  },
];

export const mockReports: ReportSummary[] = [
  {
    id: "report-001",
    project_id: "sqm-demo-platform",
    report_type: "quality_overview",
    title: "项目质量总览报告",
    focus: ["requirements", "coverage", "traceability"],
    created_at: new Date().toISOString(),
  },
];
