import type { ChatMessage, ChatResponse, DatabaseSchema, ProjectSummary } from "./types";

const base = (import.meta.env.VITE_AGENT_API_BASE || "").replace(/\/$/, "");
export async function consoleRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(base + path, {...init, headers: init?.body instanceof FormData ? init.headers : {"Content-Type": "application/json", ...init?.headers}});
  const payload = await response.json().catch(() => null);
  if (!response.ok || (payload?.code !== undefined && payload.code !== 0)) {
    throw new Error(typeof payload?.detail === "string" ? payload.detail : payload?.msg || `服务请求失败（HTTP ${response.status}）`);
  }
  return (payload?.code === 0 ? payload.data : payload) as T;
}
export async function listProjects(tenant = "local"): Promise<ProjectSummary[]> {
  return consoleRequest<ProjectSummary[]>(`/api/v1/console/projects?tenant_id=${encodeURIComponent(tenant)}`);
}
export const listChatHistory = (project: string, tenant = "local") => consoleRequest<ChatMessage[]>(`/api/chat/history?${new URLSearchParams({project_id: project, tenant_id: tenant})}`);
export const resetChat = (project: string, tenant = "local") => consoleRequest<{cleared: boolean}>(`/api/chat/history?${new URLSearchParams({project_id: project, tenant_id: tenant})}`, {method: "DELETE"});
export const sendChat = (payload: {project_id: string; tenant_id: string; message: string; mode: "quality" | "traceability" | "summary"; history: ChatMessage[]}) => consoleRequest<ChatResponse>("/api/chat", {method: "POST", body: JSON.stringify(payload)});
export const loadSchema = () => consoleRequest<DatabaseSchema>("/api/v1/console/schema");
