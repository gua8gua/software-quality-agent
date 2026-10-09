import { projectUrl, part } from "../api";

export type Page<T> = { items: T[]; has_more: boolean; next_offset?: number };
export type Run = { run_id: string; status: string; result_status: string; stage: string; created_at: string; finished_at: string | null; error: string | null; config?: Record<string, unknown>; metrics?: Record<string, unknown> };
export type TlrScopeNode = Canonical & { side: "source" | "target"; selectable: boolean; used: boolean; preview: string };
export type TlrScopeArtifact = { artifact_id: string; filename: string; engineering_role: string; side: "source" | "target"; used_node_count: number };
export type TlrScope = { run_id: string; artifacts: TlrScopeArtifact[]; nodes: TlrScopeNode[]; selected_source_node_ids: string[]; selected_target_node_ids: string[]; note: string };
export type Canonical = { node_id: string; artifact_id: string; parent_id: string | null; node_type: string; title: string; preview: string; reading_order: number; provenance: {page_no?: number}[] };
export type Unit = {unit_id: string; node_id: string; artifact_id: string; side: string; ordinal: number; role: string};
export type Link = {id: string; candidate_id: string; source_node_id: string; target_node_id: string; relation: string; explanation: string; evidence: unknown};
export type Visualization = {run_id: string; nodes: Canonical[]; units: Unit[]; links: Link[]; artifacts: {artifact_id: string; filename: string; engineering_role: string}[]; candidate_execution_counts: Record<string, number>};
export type RunCreateResult = {id: string; tenant_id: string; project_id: string; status: string; result_status: string; stage: string; config: Record<string, unknown>; metrics: Record<string, unknown>; error: string | null; created_at: string; finished_at: string | null};
export type Candidate = {candidate_id: string; source_node_id: string; target_node_id: string; relation: string | null; fused_rank: number | null; dense_rank: number | null; dense_score: number | null; bm25_rank: number | null; bm25_score: number | null; rrf_score: number; retrieval_sources: string[]; execution_status: string; validation_status: string; error_code: string | null; explanation: string; evidence: unknown};
export type NodeDetail = Canonical & {text: string; heading_path: string[]; text_start: number; text_total_chars: number; has_more_text: boolean};
export type Review = {review_id: string; batch_id?: string | null; tlr_run_id: string; requirement_node_id: string; requirement_preview: string; status: string; summary: Record<string, unknown>; created_at: string};
export type AssessmentStatus = "implemented" | "uncovered" | "issues" | "analysis_error" | "not_analyzed";
export type OverallEvidence = {evidence_id: string; node_id: string; start_offset: number; end_offset: number; exact_quote: string; candidate_id?: string | null};
export type OverallIssue = {issue_id: string; source_quote: string; reason: string; evidence: OverallEvidence[]};
export type Assessment = {status: AssessmentStatus; evaluation_text: string; finalized: boolean; suggestion_required: boolean; issues: OverallIssue[]; proposal_fingerprint?: string; validation?: unknown;
  semantic_status?: Exclude<AssessmentStatus, "analysis_error" | "not_analyzed"> | null;
  assessment_validity?: "accepted" | "proposed" | "stale" | "rejected" | "missing";
  execution_status?: string;
  execution_error?: {code?: string | null; message?: string | null} | null;
  semantic_result_available?: boolean;
  semantic_result_final?: boolean;
  source_anchor_status?: "complete" | "incomplete";
  source_unanchored_check_ids?: string[];
};
export type AnalysisBatch = {batch_id: string; name: string; description: string; tlr_run_id: string; status: string; scope: {source_artifact_ids: string[]; target_artifact_ids: string[]; selected_source_artifact_ids: string[]; selected_target_artifact_ids: string[]; selected_source_node_ids?: string[]; selected_target_node_ids?: string[]; excluded_artifact_ids: string[]; source_node_count: number; unsupported_source_node_count: number}; finished_count: number; status_counts: Record<string, number>; execution_status_counts?: Record<string, number>; created_at: string};
export type BatchDetail = AnalysisBatch & {review_ids: string[]; reviews: (Review & {artifact_id: string; assessment: Assessment; execution: {status: string; error_code: string | null; error_message: string | null; attempt?: number | null; attempt_id?: string | null} | null})[]};
export type Sentence = {sentence_id: string; ordinal: number; text: string; status: string; start_offset: number; end_offset: number; checks_finalized: boolean; assessment: Assessment};
export type Check = {check_id: string; sentence_id: string; ordinal: number; category: string; statement: string; source_quote: string; status: string; note: string};
export type Evidence = {evidence_id: string; check_id: string; design_node_id: string; start_offset: number; end_offset: number; exact_quote: string; relation: string; source: string; candidate_id: string | null; validation_status: string};
export type Task = {task_id: string; role: string; status: string; error_code: string | null; error_message: string | null; output: unknown};
export type Workspace = {review_id: string; tlr_run_id: string; requirement_node_id: string; scope?: Record<string, unknown>; status: string; assessment: Assessment; summary: Record<string, unknown>; sentences: Sentence[]; checks: Check[]; evidence: Evidence[]; tasks: Task[]; events: {event_id: string; actor_role: string; event_type: string; status: string; payload: unknown}[]; mandatory_visits: unknown[]};
export type Draft = {iteration: number; suggestion_text: string; problem_summary: string; rationale: string; check_ids: string[]; issue_ids: string[]; unresolved_questions: string[]};
export type Checkpoint = {workflow_status: string; stage: string; suggestion_drafts: Draft[]; validation_feedback: {valid: boolean; draft_iteration: number; issues: string[]; required_revision: string}[]; latest_output: {execution_status: string; suggestion_text: string; problem_summary: string; rationale: string; affected_check_ids: string[]; affected_issue_ids: string[]; unresolved_questions: string[]; error_code: string | null; error_message: string | null} | null};

async function read<T>(url: string, signal?: AbortSignal): Promise<T> {
  const r = await fetch(url, {signal});
  if (!r.ok) { const d = await r.json().catch(() => null); throw new Error(typeof d?.detail === "string" ? d.detail : `读取失败（HTTP ${r.status}）`); }
  return r.json();
}
export async function allPages<T>(load: (offset: number) => Promise<Page<T>>): Promise<T[]> {
  const items: T[] = []; let offset = 0;
  while (true) { const page = await load(offset); items.push(...page.items); if (!page.has_more) return items;
    if (page.next_offset === undefined || page.next_offset <= offset) throw new Error("分页游标没有推进"); offset = page.next_offset; }
}
export function resultsApi(tenant: string, project: string) {
  const root = `/${part(project)}`;
  const url = (path: string, query = "") => projectUrl(tenant, root + path) + query;
  const base = (import.meta.env.VITE_PROJECT_API_BASE || "/api/v1").replace(/\/$/, "");
  const traceUrl = (path: string) => `${base}${path}`;
  return {
    runs: (signal?: AbortSignal) => allPages<Run>(offset => read(url(`/information/tlr-runs`, `&limit=100&offset=${offset}`), signal)),
    graph: (run: string, signal?: AbortSignal) => read<Visualization>(url(`/information/tlr-runs/${part(run)}/visualization`), signal),
    scope: (run: string, signal?: AbortSignal) => read<TlrScope>(url(`/information/tlr-runs/${part(run)}/scope`), signal),
    candidates: (run: string, node: string, signal?: AbortSignal) => allPages<Candidate>(offset => read(url(`/information/tlr-runs/${part(run)}/nodes/${part(node)}/results`, `&limit=100&offset=${offset}`), signal)),
    node: (node: string, offset = 0, signal?: AbortSignal) => read<NodeDetail>(url(`/information/nodes/${part(node)}`, `&text_start=${offset}&text_limit=8000`), signal),
    reviews: (run?: string, node?: string, signal?: AbortSignal) => allPages<Review>(offset => read(url(`/reviews`, `&limit=100&offset=${offset}${run ? `&tlr_run_id=${part(run)}` : ""}${node ? `&requirement_node_id=${part(node)}` : ""}`), signal)),
    batches: (signal?: AbortSignal) => allPages<AnalysisBatch>(offset => read(url("/reviews/batch/list", `&limit=100&offset=${offset}`), signal)),
    batch: (id: string, signal?: AbortSignal) => read<BatchDetail>(url(`/reviews/batch/${part(id)}`), signal),
    workspace: (review: string, signal?: AbortSignal) => read<Workspace>(url(`/reviews/${part(review)}/workspace`), signal),
    checkpoint: async (review: string, sentence: string, signal?: AbortSignal): Promise<Checkpoint | null> => {
      const r = await fetch(`/api/agent/review-suggestions/${part(review)}/${part(sentence)}?project_id=${part(project)}&tenant_id=${part(tenant)}`, {signal});
      if (r.status === 404) return null;
      if (!r.ok) throw new Error(`建议服务读取失败（HTTP ${r.status}），并非“没有建议”`);
      return r.json();
    },
    createRun: async (sourceArtifactIds: string[], targetArtifactIds: string[], taskName: string, taskDescription: string, signal?: AbortSignal) => {
      const r = await fetch(traceUrl("/traceability/runs"), {method: "POST", headers: {"Content-Type": "application/json"}, signal,
        body: JSON.stringify({tenant_id: tenant, project_id: project, source_artifact_ids: sourceArtifactIds, target_artifact_ids: targetArtifactIds, task_name: taskName, task_description: taskDescription})});
      if (!r.ok) throw new Error(`创建追溯任务失败（HTTP ${r.status}）`);
      return r.json() as Promise<RunCreateResult>;
    },
    executeRun: async (runId: string, signal?: AbortSignal) => {
      const r = await fetch(`/api/tasks/trace/${part(runId)}/action`, {method: "POST", signal,
        headers: {"Content-Type": "application/json"}, body: JSON.stringify({project_id: project, tenant_id: tenant, action: "resume"})});
      if (!r.ok) { const body = await r.json().catch(() => null); throw new Error(typeof body?.detail === "string" ? body.detail : `执行追溯任务失败（HTTP ${r.status}）`); }
      return r.json() as Promise<{status: string; job_id?: number}>;
    },
    createReview: async (runId: string, requirementNodeId: string, signal?: AbortSignal) => {
      const r = await fetch(url("/reviews"), {method: "POST", headers: {"Content-Type": "application/json"}, signal,
        body: JSON.stringify({tlr_run_id: runId, requirement_node_id: requirementNodeId})});
      if (!r.ok) { const body = await r.json().catch(() => null); throw new Error(typeof body?.detail === "string" ? body.detail : `创建分析任务失败（HTTP ${r.status}）`); }
      return r.json() as Promise<{review_id: string; status: string; tlr_run_id: string; requirement_node_id: string}>;
    },
    createReviewBatch: async (runId: string, sourceArtifactIds: string[], targetArtifactIds: string[], name: string, description: string, sourceNodeIds: string[] = [], targetNodeIds: string[] = [], signal?: AbortSignal) => {
      const r = await fetch(url("/reviews/batch"), {method: "POST", headers: {"Content-Type": "application/json"}, signal,
        body: JSON.stringify({tlr_run_id: runId, source_artifact_ids: sourceArtifactIds, target_artifact_ids: targetArtifactIds, source_node_ids: sourceNodeIds, target_node_ids: targetNodeIds, name, description})});
      if (!r.ok) { const body = await r.json().catch(() => null); throw new Error(typeof body?.detail === "string" ? body.detail : `创建批量分析任务失败（HTTP ${r.status}）`); }
      return r.json() as Promise<{batch_id: string; review_ids: string[]; source_node_count: number; skipped_source_node_count: number; tlr_run_id: string}>;
    },
    prepareReview: async (reviewId: string, signal?: AbortSignal) => {
      const r = await fetch(url(`/reviews/${part(reviewId)}/prepare`), {method: "POST", signal});
      if (!r.ok) { const body = await r.json().catch(() => null); throw new Error(typeof body?.detail === "string" ? body.detail : `准备分析任务失败（HTTP ${r.status}）`); }
      return r.json();
    },
    runReviewAgents: async (reviewId: string, signal?: AbortSignal) => {
      const r = await fetch(`/api/agent/review-suggestions`, {method: "POST", headers: {"Content-Type": "application/json"}, signal,
        body: JSON.stringify({project_id: project, review_id: reviewId, tenant_id: tenant})});
      if (!r.ok) { const body = await r.json().catch(() => null); throw new Error(typeof body?.detail === "string" ? body.detail : `一致性分析执行失败（HTTP ${r.status}）`); }
      return r.json() as Promise<{review_id: string; batch_id: string; status: string; job_id?: number}>;
    },
    runReviewAgentsBatch: async (batchId: string, signal?: AbortSignal) => {
      const r = await fetch(`/api/agent/review-suggestions/batch`, {method: "POST", headers: {"Content-Type": "application/json"}, signal,
        body: JSON.stringify({project_id: project, batch_id: batchId, tenant_id: tenant})});
      if (!r.ok) { const body = await r.json().catch(() => null); throw new Error(typeof body?.detail === "string" ? body.detail : `批量一致性分析失败（HTTP ${r.status}）`); }
      return r.json() as Promise<{batch_id: string; status: string}>;
    },
  };
}
