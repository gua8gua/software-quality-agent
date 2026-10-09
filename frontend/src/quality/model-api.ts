export type ModelCapability = "chat" | "embedding" | "rerank" | "vision" | "image_generation" | "speech" | "transcription" | "unknown";
export interface ModelItem { id: string; owned_by: string; capabilities: ModelCapability[]; capability_source: "provider" | "ollama" | "probe" | "manual" | "unknown"; format: string | null; family: string | null; parameter_size: string | null; quantization_level: string | null; embedding_dimension: number | null; verification: Record<string, string> }
export interface ModelProvider { id: "deepseek" | "local_openai" | "custom"; label: string; description: string; default_base_url: string | null; base_url_editable: boolean; api_key_required: boolean; is_local: boolean; capabilities: Array<"embedding" | "chat"> }
export interface ModelConnection { id: string; name: string; provider: string; provider_label: string; capabilities: Array<"embedding" | "chat">; base_url: string; is_local: boolean; api_key_configured: boolean; models: ModelItem[]; status: string; status_message: string; last_checked_at: string | null }
export type ModelTaskId = "tlr_embedding" | "tlr_llm" | "review_analysis" | "agent_chat" | "peer_llm";
export interface ModelTask { id: ModelTaskId; label: string; description: string; capability: "embedding" | "chat"; group: string; group_label: string }
export interface ModelBinding { task: ModelTask["id"]; connection_id: string | null; model_id: string | null; dimension: number | null; temperature: number | null; test_status: string; test_message: string; last_tested_at: string | null; fallback?: { source: string; base_url?: string; model_id?: string; api_key_configured?: boolean; note?: string } }
export interface ModelConfig { providers: ModelProvider[]; connections: ModelConnection[]; tasks: ModelTask[]; bindings: ModelBinding[] }

import { consoleRequest as request } from "../console-api";
export const errorText = (value: unknown) => value instanceof Error ? value.message : String(value);
export const date = (value: string | null | undefined) => value ? new Date(value).toLocaleString("zh-CN") : "尚未检查";
export const modelUrl = (path: string, tenant: string) => `/api/v1/model-config${path}?${new URLSearchParams({tenant_id: tenant})}`;
export const getModelConfig = (tenant: string) => request<ModelConfig>(modelUrl("", tenant));
export interface ModelConnectionInput { name: string; provider: ModelProvider["id"]; base_url?: string; api_key?: string }
export const createModelConnection = (tenant: string, body: ModelConnectionInput) => request<ModelConnection>(modelUrl("/connections", tenant), { method: "POST", body: JSON.stringify(body) });
export const updateModelConnection = (tenant: string, id: string, body: ModelConnectionInput) => request<ModelConnection>(modelUrl(`/connections/${encodeURIComponent(id)}`, tenant), { method: "PUT", body: JSON.stringify(body) });
export const refreshModelConnection = (tenant: string, id: string) => request<ModelConnection>(modelUrl(`/connections/${encodeURIComponent(id)}/refresh`, tenant), { method: "POST" });
export const updateModelMetadata = (tenant: string, connectionId: string, modelId: string, capabilities: ModelCapability[]) => request<ModelItem>(modelUrl(`/connections/${encodeURIComponent(connectionId)}/models/${encodeURIComponent(modelId)}`, tenant), { method: "PUT", body: JSON.stringify({ capabilities }) });
export const deleteModelConnection = (tenant: string, id: string) => request<boolean>(modelUrl(`/connections/${encodeURIComponent(id)}`, tenant), { method: "DELETE" });
export const bindModelTask = (tenant: string, task: string, body: { connection_id: string; model_id: string; dimension?: number; temperature?: number }) => request<ModelBinding>(modelUrl(`/tasks/${encodeURIComponent(task)}`, tenant), { method: "PUT", body: JSON.stringify(body) });
export const testModelTask = (tenant: string, task: string) => request<ModelBinding>(modelUrl(`/tasks/${encodeURIComponent(task)}/test`, tenant), { method: "POST" });
export const unbindModelTask = (tenant: string, task: string) => request<ModelBinding>(modelUrl(`/tasks/${encodeURIComponent(task)}`, tenant), { method: "DELETE" });
