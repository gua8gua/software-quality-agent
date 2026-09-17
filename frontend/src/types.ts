export type ViewId = "chat" | "report" | "requirements" | "database";

export type ReportType = "quality_overview" | "traceability" | "coverage" | "custom";

export type DatabaseScope = "projects" | "artifacts" | "trace_links" | "reports" | "audit_events";

export type WriteOperation =
  | "add_project"
  | "add_artifact"
  | "add_trace_link"
  | "append_chat"
  | "save_report"
  | "log_event";

export interface ProjectSummary {
  id: string;
  name: string;
  description: string;
  owner?: string | null;
  status: string;
  artifact_count: number;
  trace_link_count: number;
}

export interface ChatMessage {
  id?: string;
  role: "user" | "assistant";
  content: string;
  evidence?: string[];
}

export interface ReportSummary {
  id: string;
  project_id: string;
  report_type: string;
  title: string;
  focus?: string[];
  created_at?: string;
}

export interface DatabaseSchema {
  tables: Record<string, string[]>;
}

export interface ChatResponse {
  project_id: string;
  mode: string;
  answer: string;
  evidence: string[];
  suggested_actions: string[];
}

export interface ReportResponse {
  project_id: string;
  report_type: string;
  title: string;
  markdown: string;
  highlights: string[];
  risks: string[];
  report_id: string;
}

export interface DatabaseReadResponse {
  scope: string;
  rows: Array<Record<string, unknown>>;
  total: number;
}

export interface DatabaseWriteResponse {
  operation: string;
  record_id: string;
  message: string;
}

export interface RequirementPoint {
  requirement_id: string;
  statement: string;
}

export interface RequirementExtractionResponse {
  source_filename: string;
  page_count: number;
  project_summary: string;
  requirements: RequirementPoint[];
  warnings: string[];
}

export type RequirementCoverageStatus =
  | "not_found"
  | "candidate"
  | "partial"
  | "implemented"
  | "needs_review";

export interface RequirementCoverage {
  requirement_id: string;
  status: RequirementCoverageStatus;
  code_refs: string[];
  evidence: string[];
  gaps: string[];
  confidence: number;
}

export interface RequirementCoverageResponse {
  repository_path: string;
  results: RequirementCoverage[];
}
