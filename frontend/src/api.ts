import { mockMessages, mockProjects, mockReports, mockSchema } from "./mock";
import type {
  ChatMessage,
  ChatResponse,
  DatabaseReadResponse,
  DatabaseSchema,
  DatabaseWriteResponse,
  DatabaseScope,
  ProjectSummary,
  ReportResponse,
  ReportSummary,
  ReportType,
  RequirementCoverageResponse,
  RequirementPoint,
  RequirementExtractionResponse,
  ViewId,
  WriteOperation,
} from "./types";

const defaultBaseUrl = import.meta.env.VITE_AGENT_API_BASE || "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${defaultBaseUrl}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function listProjects(): Promise<ProjectSummary[]> {
  try {
    return await request<ProjectSummary[]>("/api/projects");
  } catch {
    return mockProjects;
  }
}

export async function listChatHistory(projectId: string): Promise<ChatMessage[]> {
  try {
    return await request<ChatMessage[]>(`/api/chat/history?project_id=${encodeURIComponent(projectId)}`);
  } catch {
    return mockMessages;
  }
}

export async function sendChat(payload: {
  project_id: string;
  message: string;
  mode: "quality" | "traceability" | "summary";
  history: ChatMessage[];
}): Promise<ChatResponse> {
  try {
    return await request<ChatResponse>("/api/chat", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  } catch {
    return {
      project_id: payload.project_id,
      mode: payload.mode,
      answer: `Mock 回复：已收到问题“${payload.message}”。建议先检查需求、设计、代码、测试和 trace link 是否齐全。`,
      evidence: ["requirements.md", "architecture.md", "quality_report.py"],
      suggested_actions: ["补齐 trace link", "查看测试覆盖", "生成项目报告"],
    };
  }
}

export async function generateReport(payload: {
  project_id: string;
  report_type: ReportType;
  focus: string[];
  source_kinds: string[];
}): Promise<ReportResponse> {
  try {
    return await request<ReportResponse>("/api/reports/generate", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  } catch {
    return {
      project_id: payload.project_id,
      report_type: payload.report_type,
      title: "项目质量总览报告",
      markdown: `# 项目质量总览报告\n\n## 项目概览\nMock 项目。\n\n## 风险\n- trace link 不完整\n- 测试覆盖需要补充\n`,
      highlights: ["资产数：4", "追踪关系数：1", "缺口数：2"],
      risks: ["trace link 不完整", "测试覆盖需要补充"],
      report_id: "mock-report",
    };
  }
}

export async function listReports(projectId: string): Promise<ReportSummary[]> {
  try {
    return await request<ReportSummary[]>(`/api/reports?project_id=${encodeURIComponent(projectId)}`);
  } catch {
    return mockReports;
  }
}

export async function readDatabase(payload: {
  scope: DatabaseScope;
  project_id?: string;
  keyword?: string;
  limit: number;
}): Promise<DatabaseReadResponse> {
  try {
    return await request<DatabaseReadResponse>("/api/database/read", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  } catch {
    const rows =
      payload.scope === "projects"
        ? mockProjects
        : payload.scope === "reports"
          ? mockReports
          : payload.scope === "audit_events"
            ? [{ operation: "seed_demo_data", created_at: new Date().toISOString() }]
            : [{ scope: payload.scope, keyword: payload.keyword || "" }];
    return { scope: payload.scope, rows: rows.map(row => ({ ...row })), total: rows.length };
  }
}

export async function writeDatabase(payload: {
  operation: WriteOperation;
  payload: Record<string, unknown>;
}): Promise<DatabaseWriteResponse> {
  try {
    return await request<DatabaseWriteResponse>("/api/database/write", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  } catch {
    return {
      operation: payload.operation,
      record_id: "mock-record",
      message: "Mock 写入已完成",
    };
  }
}

export async function loadSchema(): Promise<DatabaseSchema> {
  try {
    return await request<DatabaseSchema>("/api/database/schema");
  } catch {
    return mockSchema;
  }
}

export async function extractRequirements(file: File): Promise<RequirementExtractionResponse> {
  const formData = new FormData();
  formData.append("file", file);
  const response = await fetch(`${defaultBaseUrl}/api/requirements/extract`, {
    method: "POST",
    body: formData,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return response.json() as Promise<RequirementExtractionResponse>;
}

export async function analyzeRequirementCoverage(
  requirements: RequirementPoint[],
  repositoryPath: string,
): Promise<RequirementCoverageResponse> {
  return request<RequirementCoverageResponse>("/api/requirements/coverage", {
    method: "POST",
    body: JSON.stringify({
      requirements,
      repository_path: repositoryPath,
    }),
  });
}
