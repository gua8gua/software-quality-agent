export type Modality = "text" | "code";
export type DocumentRole = "requirement" | "design";
export type Project = { id: string; tenant_id: string; name: string; description: string };
export type Folder = { id: string; project_id: string; parent_id: string | null; name: string };
type FileFields = {
  id: string; project_id: string; file_id: string | null; folder_id: string | null;
  filename: string; external_id: string; revision: string; file_format: string; language: string;
  media_type: string; original_file_url: string;
  size_bytes: number | null; uploaded_at: string | null;
};
export type Artifact = FileFields & (
  { modality: "text"; engineering_role: DocumentRole } |
  { modality: "code"; engineering_role: null }
);

const base = (import.meta.env.VITE_PROJECT_API_BASE || "/api/v1").replace(/\/$/, "");
export function projectUrl(tenant: string, path: string) {
  return `${base}/projects${path}?tenant_id=${encodeURIComponent(tenant)}`;
}
export const part = encodeURIComponent;
export function originalUrl(file: Artifact) {
  return new URL(file.original_file_url, new URL(base, window.location.href)).href;
}
async function request<T>(tenant: string, path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(projectUrl(tenant, path), init);
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    const detail = data?.detail;
    throw new Error(typeof detail === "string" ? detail : detail ? JSON.stringify(detail) : `HTTP ${response.status}`);
  }
  return response.status === 204 ? undefined as T : response.json();
}
function json(method: string, body: unknown): RequestInit {
  return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}
export const api = {
  projects: (tenant: string) => request<Project[]>(tenant, ""),
  createProject: (tenant: string, name: string, description: string) => request<Project>(tenant, "", json("POST", {
    tenant_id: tenant, project_id: crypto.randomUUID(), name, description,
  })),
  project: (tenant: string, id: string) => request<Project>(tenant, `/${part(id)}`),
  deleteProject: (tenant: string, id: string) => request<void>(tenant, `/${part(id)}`, { method: "DELETE" }),
  folders: (tenant: string, id: string) => request<Folder[]>(tenant, `/${part(id)}/folders`),
  createFolder: (tenant: string, id: string, parent_id: string | null, name: string) =>
    request<Folder>(tenant, `/${part(id)}/folders`, json("POST", { parent_id, name })),
  deleteFolder: (tenant: string, id: string, folder: string) =>
    request<void>(tenant, `/${part(id)}/folders/${part(folder)}`, { method: "DELETE" }),
  artifacts: (tenant: string, id: string) => request<Artifact[]>(tenant, `/${part(id)}/artifacts`),
  deleteFile: (tenant: string, id: string, file: string) => request<void>(tenant, `/${part(id)}/artifacts/${part(file)}`, { method: "DELETE" }),
  upload: (tenant: string, id: string, folder: string | null, file: File, type: Modality, role: DocumentRole | null) => {
    const body = new FormData();
    body.append("file", file);
    body.append("metadata", JSON.stringify({ external_id: `${folder || "root"}/${file.name}`, folder_id: folder,
      modality: type, engineering_role: role }));
    return request<Artifact>(tenant, `/${part(id)}/artifacts`, { method: "POST", body });
  },
};
export function typeLabel(file: Artifact) {
  return file.modality === "code" ? "代码" : file.engineering_role === "requirement" ? "需求说明文档" : "设计说明文档";
}
