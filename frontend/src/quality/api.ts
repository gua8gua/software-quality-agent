export interface Page<T> { items: T[]; total: number; offset: number; limit: number }
export interface Project { id: string; tenant_id: string; name: string; description: string; dataset_count?: number; run_count?: number }
export interface Dataset { id: string; version: string; created_at: string; provenance: Record<string, unknown>; digest: string }
export interface ArtifactStructure { original_id?: string; original_type?: string; title?: string; layer?: string; source_file?: string; path?: string; content_status?: string; parent_ids?: string[]; tree_paths?: string[][]; relations?: { target_id: string; relation: string; source_relation_type?: string }[]; [key: string]: unknown }
export interface Artifact { id: string; dataset_id?: string; external_id: string; kind: string; revision: string; locator: string; sha256: string; original_file_id: string | null; characters?: number; content?: string; structure?: ArtifactStructure }
export interface Run {
  id: string; project_id: string; dataset_id: string; status: string; stage: string; created_at: string;
  finished_at: string | null; counts: Record<string, number>; error: string | null;
  manifest: Record<string, unknown>;
  config: { plan_id?: string; layer_pair?: string[]; source_ids: string[]; target_ids: string[]; options: Record<string, unknown> };
}
export interface Element { id: string; artifact_id: string; external_id: string; role: string }
export interface Candidate { id: string; source_element_id: string; target_element_id: string; rank: number; similarity: number; decision: string }
export interface Link { id: string; source_artifact_id: string; target_artifact_id: string; relation: string; evidence_candidate_ids: string[] }
export interface Visualization { elements: Element[]; candidates: Candidate[]; links: Link[] }
export interface Capabilities { kinds: { id: string; label: string }[]; extensions: string[]; max_file_bytes: number; max_files: number; embedding_configured: boolean; llm_configured: boolean }
export interface ModelItem { id: string; owned_by: string }
export interface ModelConnection { id: string; name: string; provider: string; base_url: string; is_local: boolean; api_key_configured: boolean; models: ModelItem[]; status: string; status_message: string; last_checked_at: string | null }
export interface ModelTask { id: "tlr_embedding" | "tlr_classification" | "architecture_extraction"; label: string; description: string; capability: "embedding" | "chat" }
export interface ModelBinding { task: ModelTask["id"]; connection_id: string | null; model_id: string | null; dimension: number | null; test_status: string; test_message: string; last_tested_at: string | null; fallback?: { source: string; base_url: string; model_id: string; api_key_configured: boolean } }
export interface ModelConfig { connections: ModelConnection[]; tasks: ModelTask[]; bindings: ModelBinding[] }
export interface Evidence {
  candidate: Candidate & { evidence: { related?: boolean; evidence?: string; source_quote?: string; target_quote?: string; validation_status?: string; raw_response?: unknown } | null };
  source: { artifact_id: string; external_id: string; kind: string; start: number; end: number; content: string; processing?: Record<string, unknown> };
  target: { artifact_id: string; external_id: string; kind: string; start: number; end: number; content: string; processing?: Record<string, unknown> };
}

const base = (import.meta.env.VITE_QUALITY_API_BASE || "/api/v1/tlr").replace(/\/$/, "");
const apiRoot = base.replace(/\/tlr$/, "");
export function url(path: string, tenant: string, project?: string) {
  const query = new URLSearchParams({ tenant_id: tenant });
  if (project) query.set("project_id", project);
  return `${base}${path}?${query}`;
}
export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...init, headers: init.body instanceof FormData ? init.headers : { "Content-Type": "application/json", ...init.headers },
  });
  let body: { code?: number; msg?: string; data?: T };
  try { body = await response.json(); } catch { throw new Error(`服务返回异常（HTTP ${response.status}），请检查后端连接。`); }
  if (!response.ok || body.code !== 0) throw new Error(body.msg || `请求失败：HTTP ${response.status}`);
  return body.data as T;
}
export const get = <T,>(path: string, tenant: string, project?: string) => request<T>(url(path, tenant, project));
export const post = <T,>(path: string, tenant: string, project: string | undefined, body?: unknown) => request<T>(url(path, tenant, project), { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
export const modelUrl = (path: string, tenant: string) => `${apiRoot}/model-config${path}?${new URLSearchParams({ tenant_id: tenant })}`;
export const getModelConfig = (tenant: string) => request<ModelConfig>(modelUrl("", tenant));
export const createModelConnection = (tenant: string, body: { name: string; base_url: string; api_key?: string }) => request<ModelConnection>(modelUrl("/connections", tenant), { method: "POST", body: JSON.stringify(body) });
export const updateModelConnection = (tenant: string, id: string, body: { name: string; base_url: string; api_key?: string }) => request<ModelConnection>(modelUrl(`/connections/${encodeURIComponent(id)}`, tenant), { method: "PUT", body: JSON.stringify(body) });
export const refreshModelConnection = (tenant: string, id: string) => request<ModelConnection>(modelUrl(`/connections/${encodeURIComponent(id)}/refresh`, tenant), { method: "POST" });
export const deleteModelConnection = (tenant: string, id: string) => request<boolean>(modelUrl(`/connections/${encodeURIComponent(id)}`, tenant), { method: "DELETE" });
export const bindModelTask = (tenant: string, task: string, body: { connection_id: string; model_id: string; dimension?: number }) => request<ModelBinding>(modelUrl(`/tasks/${encodeURIComponent(task)}`, tenant), { method: "PUT", body: JSON.stringify(body) });
export const testModelTask = (tenant: string, task: string) => request<ModelBinding>(modelUrl(`/tasks/${encodeURIComponent(task)}/test`, tenant), { method: "POST" });
export const unbindModelTask = (tenant: string, task: string) => request<ModelBinding>(modelUrl(`/tasks/${encodeURIComponent(task)}`, tenant), { method: "DELETE" });
export async function all<T>(path: string, tenant: string, project?: string): Promise<T[]> {
  const rows: T[] = [];
  for (;;) {
    const page = await request<Page<T>>(`${url(path, tenant, project)}&offset=${rows.length}&limit=100`);
    rows.push(...page.items);
    if (rows.length >= page.total) return rows;
    if (!page.items.length) throw new Error("分页结果不完整，请刷新后重试。");
  }
}
export const uploadFiles = (project: string, tenant: string, data: FormData) => request<Dataset>(url(`/projects/${encodeURIComponent(project)}/upload`, tenant), { method: "POST", body: data });
export const errorText = (error: unknown) => error instanceof Error ? error.message : "操作失败，请重试。";
export const date = (value: string | null) => value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "—";
export const statusLabel: Record<string, string> = { pending: "待执行", running: "分析中", completed: "已完成", failed: "失败" };
export const decisionLabel: Record<string, string> = { pending: "尚未判定", related: "正向判定", unrelated: "无关联判定" };
