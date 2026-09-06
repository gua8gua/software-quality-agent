import { useEffect, useMemo, useState, type FormEvent } from "react";
import { CheckCircle2, Cloud, KeyRound, Laptop, Plus, RefreshCw, Save, Settings2, Trash2 } from "lucide-react";
import {
  bindModelTask, createModelConnection, date, deleteModelConnection, errorText,
  getModelConfig, refreshModelConnection, testModelTask, unbindModelTask,
  updateModelConnection, type ModelBinding, type ModelConfig as Config,
  type ModelConnection,
} from "./api";
import { Alert, Empty, Loading } from "./common";

type Draft = { connection_id: string; model_id: string; dimension: string };

export function ModelConfigPage({ tenant }: { tenant: string }) {
  const [config, setConfig] = useState<Config | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [editing, setEditing] = useState<ModelConnection | "new" | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});

  async function load() {
    setError("");
    try {
      const value = await getModelConfig(tenant);
      setConfig(value);
      setDrafts(Object.fromEntries(value.bindings.map((item) => [item.task, {
        connection_id: item.connection_id || "", model_id: item.model_id || "",
        dimension: item.dimension?.toString() || "",
      }])));
    } catch (reason) { setError(errorText(reason)); }
  }
  useEffect(() => { void load(); }, [tenant]);
  const byId = useMemo(
    () => new Map(config?.connections.map((item) => [item.id, item]) || []), [config],
  );
  async function act(key: string, operation: () => Promise<unknown>) {
    setBusy(key); setError("");
    try { await operation(); await load(); }
    catch (reason) { setError(errorText(reason)); }
    finally { setBusy(""); }
  }
  async function saveTask(task: string) {
    const value = drafts[task];
    if (!value?.connection_id) {
      await act(`save-${task}`, () => unbindModelTask(tenant, task)); return;
    }
    if (!value.model_id) { setError("请选择模型。"); return; }
    await act(`save-${task}`, () => bindModelTask(tenant, task, {
      connection_id: value.connection_id, model_id: value.model_id,
      dimension: value.dimension ? Number(value.dimension) : undefined,
    }));
  }
  if (!config && !error) return <Loading />;
  return <>
    <div className="qm-heading"><div><div className="qm-eyebrow">MODEL CONFIGURATION</div><h1>模型配置</h1><p>管理 OpenAI 兼容接口，并为每个质量分析任务指定实际调用的模型。</p></div><button className="qm-primary" onClick={() => setEditing("new")}><Plus size={17} />添加模型连接</button></div>
    {error && <Alert>{error}</Alert>}
    <div className="qm-summary-strip"><div><strong>{config?.connections.length || 0}</strong><span>模型连接</span></div><div><strong>{config?.connections.filter((item) => item.status === "available").length || 0}</strong><span>目录可访问</span></div><div><strong>{config?.connections.filter((item) => item.is_local).length || 0}</strong><span>本地模型服务</span></div><div><strong>{config?.bindings.filter((item) => item.connection_id).length || 0}</strong><span>任务已显式绑定</span></div></div>
    <section className="qm-panel"><div className="qm-panel-head"><h2>当前可调用的大模型</h2><button disabled={!!busy} onClick={() => void load()}><RefreshCw size={15} />刷新页面</button></div>
      {!config?.connections.length ? <Empty title="还没有模型连接"><p>添加云端 API 或 Ollama 等本地 OpenAI 兼容服务。</p></Empty> : <div className="qm-model-grid">{config.connections.map((item) => <ConnectionCard key={item.id} connection={item} busy={!!busy} edit={() => setEditing(item)} refresh={() => void act(`refresh-${item.id}`, () => refreshModelConnection(tenant, item.id))} remove={() => { if (window.confirm(`删除连接“${item.name}”？关联的任务选择也会被清除。`)) void act(`delete-${item.id}`, () => deleteModelConnection(tenant, item.id)); }} />)}</div>}
    </section>
    <section className="qm-panel"><div className="qm-panel-head"><div><h2>任务模型选择</h2><small>保存后立即生效；运行记录会保存实际模型快照。</small></div></div><div className="qm-task-list">{config?.tasks.map((task) => {
      const binding = config.bindings.find((item) => item.task === task.id) as ModelBinding;
      const draft = drafts[task.id] || { connection_id: "", model_id: "", dimension: "" };
      const connection = byId.get(draft.connection_id);
      return <article key={task.id}><div className="qm-task-copy"><h3>{task.label}<span className="qm-type">{task.capability === "embedding" ? "向量" : "结构化对话"}</span></h3><p>{task.description}</p>{!binding.connection_id && binding.fallback && <small>当前回退到 .env：{binding.fallback.model_id} · {binding.fallback.api_key_configured ? "密钥已配置" : "密钥缺失"}</small>}</div>
        <label>连接<select value={draft.connection_id} onChange={(event) => setDrafts((value) => ({ ...value, [task.id]: { ...draft, connection_id: event.target.value, model_id: "" } }))}><option value="">使用 .env 回退</option>{config.connections.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.is_local ? "本地" : "远程"}</option>)}</select></label>
        <label>模型<select value={draft.model_id} disabled={!connection} onChange={(event) => setDrafts((value) => ({ ...value, [task.id]: { ...draft, model_id: event.target.value } }))}><option value="">选择模型</option>{connection?.models.map((model) => <option key={model.id} value={model.id}>{model.id} · {model.owned_by}</option>)}</select></label>
        {task.capability === "embedding" && <label>向量维度<input type="number" min="1" value={draft.dimension} onChange={(event) => setDrafts((value) => ({ ...value, [task.id]: { ...draft, dimension: event.target.value } }))} placeholder="例如 1536" /></label>}
        <div className="qm-task-actions"><button className="qm-primary" disabled={!!busy || (!!draft.connection_id && !draft.model_id)} onClick={() => void saveTask(task.id)}><Save size={14} />{draft.connection_id ? "保存" : "使用 .env"}</button><button disabled={!!busy || !binding.connection_id} onClick={() => void act(`test-${task.id}`, () => testModelTask(tenant, task.id))}><CheckCircle2 size={14} />实测</button><small className={binding.test_status === "passed" ? "qm-success" : binding.test_status === "failed" ? "qm-failure" : ""}>{binding.test_status === "passed" ? "调用通过" : binding.test_status === "failed" ? "调用失败" : "未实测"}{binding.test_message ? `：${binding.test_message}` : ""}</small></div></article>;
    })}</div></section>
    {editing && <ConnectionDialog tenant={tenant} current={editing === "new" ? undefined : editing} close={() => setEditing(null)} saved={() => { setEditing(null); void load(); }} />}
  </>;
}

function ConnectionCard({ connection, busy, edit, refresh, remove }: { connection: ModelConnection; busy: boolean; edit: () => void; refresh: () => void; remove: () => void }) {
  const status = connection.status === "available" ? "目录可访问" : connection.status === "unavailable" ? "不可访问" : "未检查";
  return <article className="qm-model-card"><header><span className="qm-model-icon">{connection.is_local ? <Laptop size={19} /> : <Cloud size={19} />}</span><div><h3>{connection.name}</h3><code>{connection.base_url}</code></div><span className={`qm-badge ${connection.status === "available" ? "completed" : connection.status === "unavailable" ? "failed" : ""}`}>{status}</span></header><div className="qm-model-meta"><span>{connection.is_local ? "本地模型" : "远程模型"}</span><span><KeyRound size={13} />{connection.api_key_configured ? "密钥已保存" : connection.is_local ? "无需密钥" : "未保存密钥"}</span><span>{connection.provider}</span></div><p>{connection.status_message || "尚未读取模型目录"} · {date(connection.last_checked_at)}</p><div className="qm-model-list">{connection.models.length ? connection.models.map((model) => <span key={model.id}><strong>{model.id}</strong><small>{model.owned_by}</small></span>) : <small>没有可展示的模型</small>}</div><footer><button disabled={busy} onClick={refresh}><RefreshCw size={14} />重新读取目录</button><button onClick={edit}><Settings2 size={14} />编辑</button><button className="qm-danger" disabled={busy} onClick={remove}><Trash2 size={14} />删除</button></footer></article>;
}

function ConnectionDialog({ tenant, current, close, saved }: { tenant: string; current?: ModelConnection; close: () => void; saved: () => void }) {
  const [name, setName] = useState(current?.name || "");
  const [baseUrl, setBaseUrl] = useState(current?.base_url || "http://127.0.0.1:11434/v1");
  const [apiKey, setApiKey] = useState(""); const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const body = { name: name.trim(), base_url: baseUrl.trim(), ...(apiKey ? { api_key: apiKey } : {}) };
      if (current) await updateModelConnection(tenant, current.id, body);
      else await createModelConnection(tenant, body);
      saved();
    } catch (reason) { setError(errorText(reason)); } finally { setBusy(false); }
  }
  return <dialog className="qm-modal" open><header><div><div className="qm-eyebrow">OPENAI COMPATIBLE</div><h2>{current ? "编辑模型连接" : "添加模型连接"}</h2></div><button className="qm-icon" onClick={close}>×</button></header><form onSubmit={submit}>{error && <Alert>{error}</Alert>}<label>连接名称<input value={name} onChange={(event) => setName(event.target.value)} required maxLength={255} placeholder="例如：本地 Ollama" /></label><label>API Base URL<input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} required placeholder="https://api.example.com/v1" /><small>系统会访问此地址下的 /models。远程地址必须使用 HTTPS。</small></label><label>API 密钥<input type="password" autoComplete="new-password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={current?.api_key_configured ? "留空则保留现有密钥" : "本地服务可留空"} /><small>密钥加密保存，保存后不会再次显示。</small></label><footer><span>保存时会自动读取模型目录。</span><button type="button" onClick={close}>取消</button><button className="qm-primary" disabled={busy} type="submit">{busy ? "连接中…" : "保存并检查"}</button></footer></form></dialog>;
}
