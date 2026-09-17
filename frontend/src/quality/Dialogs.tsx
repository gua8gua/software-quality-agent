import { useState, type FormEvent } from "react";
import { Upload, X } from "lucide-react";
import { type Artifact, type Capabilities, type Dataset, type Project, type Run, post, uploadFiles, errorText } from "./api";
import { Alert, Modal } from "./common";

export function NewProject({ tenant, close, saved }: { tenant: string; close: () => void; saved: (project: Project) => void }) {
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const data = new FormData(event.currentTarget); setBusy(true); setError("");
    try { saved(await post<Project>("/projects", tenant, undefined, { tenant_id: tenant, project_id: String(data.get("id")).trim(), name: String(data.get("name")).trim(), description: data.get("description") })); }
    catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  }
  return <Modal title="新建软件项目" close={() => !busy && close()}><form onSubmit={submit}>
    <label>项目名称<input name="name" required maxLength={255} placeholder="例如：软件质量管理系统" autoFocus /></label>
    <label>项目标识<input name="id" required maxLength={128} pattern=".*\S.*" placeholder="例如：quality-management" /><small>用于明确资料所属项目，创建后保持不变。</small></label>
    <label>项目说明<textarea name="description" maxLength={5000} rows={3} placeholder="软件用途、范围或版本信息" /></label>
    {error && <Alert>{error}</Alert>}<footer><button type="button" disabled={busy} onClick={close}>取消</button><button className="primary-button" disabled={busy}>{busy ? "正在创建…" : "创建项目"}</button></footer>
  </form></Modal>;
}

interface FileRow { file: File; external_id: string; kind: string }
export function UploadDialog({ tenant, project, dataset, capabilities, close, saved }: { tenant: string; project: Project; dataset?: Dataset; capabilities: Capabilities; close: () => void; saved: (dataset: Dataset) => void }) {
  const [rows, setRows] = useState<FileRow[]>([]), [version, setVersion] = useState("");
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [replace, setReplace] = useState(false);
  const [bulkKind, setBulkKind] = useState("");
  function addFiles(files: FileList | null) {
    if (!files) return;
    const additions = Array.from(files);
    if (rows.length + additions.length > capabilities.max_files) { setError("单批最多 50 个文件。"); return; }
    if (additions.some(f => f.size > capabilities.max_file_bytes)) { setError("单个文件不能超过 10 MiB。"); return; }
    setRows(old => [...old, ...additions.map(file => ({ file, external_id: file.name, kind: bulkKind }))]); setError("");
  }
  function change(index: number, patch: Partial<FileRow>) { setRows(old => old.map((row, i) => i === index ? { ...row, ...patch } : row)); }
  async function submit(event: FormEvent) {
    event.preventDefault(); setError("");
    if (!rows.length || rows.some(row => !row.kind || !row.external_id.trim())) { setError("请添加文件，并填写每个文件的标识和业务类型。"); return; }
    if (new Set(rows.map(row => row.external_id.trim())).size !== rows.length) { setError("本批次的文件标识不能重复。"); return; }
    const data = new FormData(); data.set("tenant_id", tenant); data.set("version", version.trim());
    if (dataset) data.set("base_dataset_id", dataset.id);
    data.set("replace_existing", String(replace));
    data.set("metadata", JSON.stringify(rows.map(row => ({ external_id: row.external_id.trim(), kind: row.kind, revision: version.trim() }))));
    rows.forEach(row => data.append("files", row.file)); setBusy(true);
    try { saved(await uploadFiles(project.id, tenant, data)); } catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  }
  return <Modal title="上传项目资料" close={() => !busy && close()} wide><form onSubmit={submit}>
    <div className="qm-form-grid"><label>所属项目<input value={`${project.name} · ${project.id}`} readOnly /></label><label>本次资料版本<input value={version} onChange={e => setVersion(e.target.value)} required maxLength={128} placeholder="例如：v1.0 / 2026-09-06" /></label></div>
    <p className="muted-text">{dataset ? `以 ${dataset.version} 的资料为基础创建新快照，保留原版本。` : "创建项目的第一份资料快照。"} 文件类型由你指定。</p>
    <label className="qm-upload"><Upload size={25} /><strong>选择本地文件</strong><span>文本、源代码、PDF、DOCX · 单文件最多 10 MiB</span><input type="file" multiple accept={capabilities.extensions.join(",")} onChange={e => { addFiles(e.target.files); e.target.value = ""; }} disabled={busy} aria-label="选择本地文件" /></label>
    <label>批量设置业务类型<select value={bulkKind} onChange={e => { const kind = e.target.value; setBulkKind(kind); setRows(old => old.map(row => ({ ...row, kind }))); }}><option value="">请选择，或在下方逐个指定</option>{capabilities.kinds.map(kind => <option key={kind.id} value={kind.id}>{kind.label}</option>)}</select></label>
    <div className="qm-upload-rows">{rows.map((row, index) => <div className="qm-upload-row" key={`${index}-${row.file.name}`}><div><strong>{row.file.name}</strong><small>{(row.file.size / 1024).toFixed(1)} KiB</small></div><input aria-label={`${row.file.name} 的标识`} value={row.external_id} maxLength={128} onChange={e => change(index, { external_id: e.target.value })} required /><select aria-label={`${row.file.name} 的类型`} value={row.kind} onChange={e => change(index, { kind: e.target.value })} required><option value="">请选择类型</option>{capabilities.kinds.map(k => <option value={k.id} key={k.id}>{k.label}</option>)}</select><button type="button" className="qm-icon" aria-label={`移除 ${row.file.name}`} disabled={busy} onClick={() => setRows(old => old.filter((_, i) => i !== index))}><X size={16} /></button></div>)}</div>
    {dataset && <label className="qm-check"><input type="checkbox" checked={replace} onChange={e => setReplace(e.target.checked)} />允许在新快照中替换同标识制品（旧快照不变）</label>}
    {error && <Alert>{error}</Alert>}<footer><span>{rows.length} 个文件</span><button type="button" disabled={busy} onClick={close}>取消</button><button className="primary-button" disabled={busy || !rows.length}>{busy ? "提取正文并保存…" : "上传并保存"}</button></footer>
  </form></Modal>;
}

export function AnalysisDialog({ tenant, project, dataset, artifacts, kinds, close, created }: { tenant: string; project: Project; dataset: Dataset; artifacts: Artifact[]; kinds: Map<string, string>; close: () => void; created: (run: Run) => void }) {
  const [sources, setSources] = useState<string[]>([]), [targets, setTargets] = useState<string[]>([]);
  const [topK, setTopK] = useState(20), [engine, setEngine] = useState("python"), [busy, setBusy] = useState(false), [error, setError] = useState("");
  function preset(test: boolean) { setSources(artifacts.filter(a => a.kind === "requirement").map(a => a.external_id)); setTargets(artifacts.filter(a => test ? ["test_case", "test_code", "test"].includes(a.kind) : a.kind === "code").map(a => a.external_id)); }
  function toggle(id: string, source: boolean) {
    const update = (ids: string[]) => ids.includes(id) ? ids.filter(x => x !== id) : [...ids, id];
    if (source) { setSources(update); setTargets(old => old.filter(x => x !== id)); } else { setTargets(update); setSources(old => old.filter(x => x !== id)); }
  }
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try { created(await post<Run>("/runs", tenant, project.id, { tenant_id: tenant, project_id: project.id, dataset_id: dataset.id, source_ids: sources, target_ids: targets, options: { top_k: topK, source_preprocessor: "auto", target_preprocessor: "auto", chunk_size: 2000, retrieval_backend: engine } })); }
    catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  }
  return <Modal title="重新进行 TLR 检测" close={() => !busy && close()} wide><form onSubmit={submit}>
    <p><strong>{project.name}</strong> / {dataset.version}</p><p className="muted-text">新建独立运行，保留已有结果。选择有方向的两组资料，例如需求 → 代码。</p>
    <div className="inline-controls"><button type="button" onClick={() => preset(false)}>需求 → 代码</button><button type="button" onClick={() => preset(true)}>需求 → 测试</button><button type="button" onClick={() => { setSources([]); setTargets([]); }}>清空选择</button></div>
    <div className="qm-selection"><table className="data-table"><thead><tr><th>制品</th><th>类型</th><th>源资料</th><th>目标资料</th></tr></thead><tbody>{artifacts.map(a => <tr key={a.id}><td>{a.external_id}</td><td>{kinds.get(a.kind) || a.kind}</td><td><input type="checkbox" aria-label={`${a.external_id} 作为源`} checked={sources.includes(a.external_id)} onChange={() => toggle(a.external_id, true)} /></td><td><input type="checkbox" aria-label={`${a.external_id} 作为目标`} checked={targets.includes(a.external_id)} onChange={() => toggle(a.external_id, false)} /></td></tr>)}</tbody></table></div>
    <div className="qm-form-grid"><label>每个源单元的候选数（Top-k）<input type="number" min={1} max={100} value={topK} onChange={e => setTopK(Number(e.target.value))} required /></label><label>检索方式<select value={engine} onChange={e => setEngine(e.target.value)}><option value="python">余弦检索 · Python</option><option value="lissa">原版 LiSSA · Java</option></select></label></div>
    {error && <Alert>{error}</Alert>}<footer><span>{sources.length} 个源 · {targets.length} 个目标</span><button type="button" disabled={busy} onClick={close}>取消</button><button className="primary-button" disabled={busy || !sources.length || !targets.length}>{busy ? "创建运行…" : "开始检测"}</button></footer>
  </form></Modal>;
}
