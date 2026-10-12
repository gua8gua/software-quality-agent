import { useState, type FormEvent } from "react";
import { api, type DocumentRole, type Modality, type Project } from "./api";
import { Alert, Modal } from "./common";

export function NewProjectDialog({ tenant, close, done }: { tenant: string; close: () => void; done: (project: Project) => void }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try { done(await api.createProject(tenant, name.trim(), description.trim())); }
    catch (error) { setError(String(error)); }
    finally { setBusy(false); }
  }
  return <Modal title="新建项目" close={() => { if (!busy) close(); }}><form onSubmit={submit}>
    <label>项目名称<input required maxLength={255} value={name} onChange={event => setName(event.target.value)} /></label>
    <label>说明<textarea value={description} onChange={event => setDescription(event.target.value)} /></label>
    {error && <Alert>{error}</Alert>}
    <footer><button type="button" disabled={busy} onClick={close}>取消</button><button className="primary" disabled={busy || !name.trim()}>{busy ? "正在创建…" : "创建"}</button></footer>
  </form></Modal>;
}

export function NewFolderDialog({ tenant, project, parent, close, done }: {
  tenant: string; project: string; parent: string | null; close: () => void; done: () => void;
}) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try { await api.createFolder(tenant, project, parent, name.trim()); done(); }
    catch (error) { setError(String(error)); }
    finally { setBusy(false); }
  }
  return <Modal title="新建文件夹" close={() => { if (!busy) close(); }}><form onSubmit={submit}>
    <label>名称<input required maxLength={255} value={name} onChange={event => setName(event.target.value)} /></label>
    {error && <Alert>{error}</Alert>}
    <footer><button type="button" disabled={busy} onClick={close}>取消</button><button className="primary" disabled={busy || !name.trim()}>创建</button></footer>
  </form></Modal>;
}

export function UploadDialog({ tenant, project, folder, modality, close, done }: {
  tenant: string; project: string; folder: string | null; modality: Modality; close: () => void; done: () => void;
}) {
  const [role, setRole] = useState<DocumentRole>("requirement");
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [progress, setProgress] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    const pending = [...files];
    try {
      while (pending.length) {
        const file = pending[0]; setProgress(`正在保存：${file.name}`);
        await api.upload(tenant, project, folder, file, modality, modality === "text" ? role : null);
        pending.shift(); setFiles([...pending]);
      }
      done();
    } catch (error) { setError(`已保存的文件不会重复提交。${String(error)}`); }
    finally { setBusy(false); setProgress(""); }
  }
  return <Modal title={modality === "text" ? "上传文本" : "上传代码"} close={() => { if (!busy) close(); }}><form onSubmit={submit}>
    {modality === "text" && <label>文档子类<select disabled={busy} value={role} onChange={event => setRole(event.target.value as DocumentRole)}>
      <option value="requirement">需求说明文档</option><option value="design">设计说明文档</option>
    </select></label>}
    <label>文件<input type="file" multiple disabled={busy} accept={modality === "text" ? ".pdf,.docx,.txt,.md" : undefined}
      onChange={event => setFiles(Array.from(event.target.files || []))} /></label>
    <p className="muted">{modality === "text" ? "支持 PDF、DOCX、TXT、Markdown。" : "代码文件采用 UTF-8 编码。"}</p>
    <ul>{files.map(file => <li key={`${file.name}/${file.lastModified}`}>{file.name}</li>)}</ul>
    {progress && <p role="status">{progress}</p>}{error && <Alert>{error}</Alert>}
    <footer><button type="button" disabled={busy} onClick={close}>关闭</button><button className="primary" disabled={busy || !files.length}>{busy ? "正在保存…" : "上传"}</button></footer>
  </form></Modal>;
}
