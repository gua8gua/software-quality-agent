import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { CheckCircle2, Cloud, KeyRound, Laptop, Plus, RefreshCw, Save, Settings2, Trash2 } from "lucide-react";
import {
  bindModelTask, createModelConnection, date, deleteModelConnection, errorText,
  getModelConfig, refreshModelConnection, testModelTask, unbindModelTask,
  updateModelConnection, updateModelMetadata, type ModelBinding, type ModelCapability,
  type ModelConfig as Config, type ModelConnection, type ModelItem, type ModelProvider,
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
    <div className="qm-heading"><div><div className="eyebrow">MODEL CONFIGURATION</div><h1>模型配置</h1><p>管理 OpenAI 兼容接口，并为每个质量分析任务指定实际调用的模型。</p></div><button className="primary-button" onClick={() => setEditing("new")}><Plus size={17} />添加模型连接</button></div>
    {error && <Alert>{error}</Alert>}
    <div className="qm-summary-strip"><div><strong>{config?.connections.length || 0}</strong><span>模型连接</span></div><div><strong>{config?.connections.filter((item) => item.status === "available").length || 0}</strong><span>目录可访问</span></div><div><strong>{config?.connections.filter((item) => item.is_local).length || 0}</strong><span>本地模型服务</span></div><div><strong>{config?.bindings.filter((item) => item.connection_id).length || 0}</strong><span>任务已显式绑定</span></div></div>
    <section className="surface"><div className="panel-header"><h2>当前可调用的大模型</h2><button disabled={!!busy} onClick={() => void load()}><RefreshCw size={15} />刷新页面</button></div>
      {!config?.connections.length ? <Empty title="还没有模型连接"><p>添加云端 API 或 Ollama 等本地 OpenAI 兼容服务。</p></Empty> : <div className="qm-model-grid">{config.connections.map((item) => <ConnectionCard key={item.id} connection={item} busy={!!busy} edit={() => setEditing(item)} refresh={() => void act(`refresh-${item.id}`, () => refreshModelConnection(tenant, item.id))} setCapabilities={(model, capabilities) => void act(`model-${item.id}-${model.id}`, () => updateModelMetadata(tenant, item.id, model.id, capabilities))} remove={() => { if (window.confirm(`删除连接“${item.name}”？关联的任务选择也会被清除。`)) void act(`delete-${item.id}`, () => deleteModelConnection(tenant, item.id)); }} />)}</div>}
    </section>
    <section className="surface"><div className="panel-header"><div><h2>任务模型选择</h2><small>保存后立即生效；运行记录会保存实际模型快照。</small></div></div><div className="qm-task-list">{config?.tasks.map((task) => {
      const binding = config.bindings.find((item) => item.task === task.id) as ModelBinding;
      const draft = drafts[task.id] || { connection_id: "", model_id: "", dimension: "" };
      const connection = byId.get(draft.connection_id);
      const eligibleConnections = config.connections.filter((item) => item.capabilities.includes(task.capability));
      const eligibleModels = connection?.models.filter((model) => model.capabilities.includes(task.capability) || model.capabilities.includes("unknown")) || [];
      return <article key={task.id}><div className="qm-task-copy"><h3>{task.label}<span className="qm-type">{task.capability === "embedding" ? "向量" : "结构化对话"}</span></h3><p>{task.description}</p>{!binding.connection_id && binding.fallback && <small>当前使用后端 .env：{binding.fallback.model_id} · {binding.fallback.api_key_configured ? "密钥已配置" : "密钥缺失"}</small>}</div>
        <label>连接<select value={draft.connection_id} onChange={(event) => setDrafts((value) => ({ ...value, [task.id]: { ...draft, connection_id: event.target.value, model_id: "" } }))}><option value="">使用后端 .env 配置</option>{eligibleConnections.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.is_local ? "本地" : "远程"}</option>)}</select>{!eligibleConnections.length && <small>暂无支持{task.capability === "embedding" ? "向量" : "对话"}能力的连接</small>}</label>
        <label>模型<select value={draft.model_id} disabled={!connection} onChange={(event) => { const model = eligibleModels.find((item) => item.id === event.target.value); setDrafts((value) => ({ ...value, [task.id]: { ...draft, model_id: event.target.value, dimension: task.capability === "embedding" && model?.embedding_dimension ? String(model.embedding_dimension) : draft.dimension } })); }}><option value="">{connection ? "选择模型" : "请先选择连接"}</option>{eligibleModels.map((model) => <option key={model.id} value={model.id}>{model.id}{model.capabilities.includes("unknown") ? " · 能力待实测" : ""}</option>)}</select>{connection && !eligibleModels.length && <small>此连接没有匹配该任务能力的模型</small>}</label>
        {task.capability === "embedding" && <label>向量维度<input type="number" min="1" value={draft.dimension} onChange={(event) => setDrafts((value) => ({ ...value, [task.id]: { ...draft, dimension: event.target.value } }))} placeholder="例如 1536" /></label>}
        <div className="qm-task-actions"><button className="primary-button" disabled={!!busy || (!!draft.connection_id && !draft.model_id)} onClick={() => void saveTask(task.id)}><Save size={14} />{draft.connection_id ? "保存" : "恢复 .env 配置"}</button><button disabled={!!busy || !binding.connection_id} onClick={() => void act(`test-${task.id}`, () => testModelTask(tenant, task.id))}><CheckCircle2 size={14} />实测</button><small className={binding.test_status === "passed" ? "qm-success" : binding.test_status === "failed" ? "qm-failure" : ""}>{binding.test_status === "passed" ? "调用通过" : binding.test_status === "failed" ? "调用失败" : "未实测"}{binding.test_message ? `：${binding.test_message}` : ""}</small></div></article>;
    })}</div></section>
    {editing && <ConnectionDialog tenant={tenant} providers={config?.providers || []} current={editing === "new" ? undefined : editing} close={() => setEditing(null)} saved={() => { setEditing(null); void load(); }} />}
  </>;
}

const capabilityLabels: Record<ModelCapability, string> = { chat: "对话", embedding: "向量编码", rerank: "重排", vision: "视觉", image_generation: "图像生成", speech: "语音合成", transcription: "语音识别", unknown: "能力未知" };
const editableCapabilities: ModelCapability[] = ["chat", "embedding", "rerank", "vision", "image_generation", "speech", "transcription"];

function ConnectionCard({ connection, busy, edit, refresh, setCapabilities, remove }: { connection: ModelConnection; busy: boolean; edit: () => void; refresh: () => void; setCapabilities: (model: ModelItem, capabilities: ModelCapability[]) => void; remove: () => void }) {
  const status = connection.status === "available" ? "目录可访问" : connection.status === "unavailable" ? "不可访问" : "未检查";
  return <article className="qm-model-card"><header><span className="qm-model-icon">{connection.is_local ? <Laptop size={19} /> : <Cloud size={19} />}</span><div><h3>{connection.name}</h3><code>{connection.base_url}</code></div><span className={`mini-pill ${connection.status === "available" ? "completed" : connection.status === "unavailable" ? "failed" : ""}`}>{status}</span></header><div className="qm-model-meta"><span>{connection.is_local ? "本地模型" : "远程模型"}</span><span><KeyRound size={13} />{connection.api_key_configured ? "密钥已保存" : connection.is_local ? "无需密钥" : "未保存密钥"}</span><span>{connection.provider_label}</span></div><p>{connection.status_message || "尚未读取模型目录"} · {date(connection.last_checked_at)}</p><details className="qm-model-disclosure"><summary>可调用模型（{connection.models.length}）</summary><div className="qm-model-list">{connection.models.length ? connection.models.map((model) => <ModelMetadata key={model.id} model={model} busy={busy} save={(capabilities) => setCapabilities(model, capabilities)} />) : <small>没有可展示的模型，请重新读取目录。</small>}</div></details><footer><button disabled={busy} onClick={refresh}><RefreshCw size={14} />重新读取目录</button><button onClick={edit}><Settings2 size={14} />编辑</button><button className="qm-danger" disabled={busy} onClick={remove}><Trash2 size={14} />删除</button></footer></article>;
}

function ModelMetadata({ model, busy, save }: { model: ModelItem; busy: boolean; save: (capabilities: ModelCapability[]) => void }) {
  const [editing, setEditing] = useState(false);
  const [selected, setSelected] = useState<ModelCapability[]>(model.capabilities.filter((item) => item !== "unknown"));
  const detail = [model.family, model.parameter_size, model.quantization_level, model.embedding_dimension ? `${model.embedding_dimension} 维` : null].filter(Boolean).join(" · ");
  return <div className="qm-model-entry"><div><strong>{model.id}</strong><small>{model.owned_by}{detail ? ` · ${detail}` : ""}</small><div className="qm-capability-tags">{model.capabilities.map((item) => <span key={item}>{capabilityLabels[item]}</span>)}<small>{model.capability_source === "ollama" ? "Ollama 自动识别" : model.capability_source === "provider" ? "提供方声明" : model.capability_source === "probe" ? "调用实测" : model.capability_source === "manual" ? "人工设置" : "需实测或人工设置"}</small></div></div><button type="button" disabled={busy} onClick={() => setEditing((value) => !value)}>设置类型</button>{editing && <div className="qm-capability-editor">{editableCapabilities.map((item) => <label key={item}><input type="checkbox" checked={selected.includes(item)} onChange={() => setSelected((value) => value.includes(item) ? value.filter((entry) => entry !== item) : [...value, item])} />{capabilityLabels[item]}</label>)}<button type="button" className="primary-button" disabled={busy} onClick={() => { save(selected.length ? selected : ["unknown"]); setEditing(false); }}>保存类型</button></div>}</div>;
}

function ConnectionDialog({ tenant, providers, current, close, saved }: { tenant: string; providers: ModelProvider[]; current?: ModelConnection; close: () => void; saved: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const currentProvider: ModelProvider["id"] = current
    ? providers.some((item) => item.id === current.provider) ? current.provider as ModelProvider["id"] : "custom"
    : "deepseek";
  const [providerId, setProviderId] = useState<ModelProvider["id"]>(currentProvider);
  const [name, setName] = useState(current?.name || "DeepSeek 官方 API");
  const [baseUrl, setBaseUrl] = useState(current?.base_url || "http://127.0.0.1:11434/v1");
  const [apiKey, setApiKey] = useState(""); const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const provider = providers.find((item) => item.id === providerId);
  useEffect(() => {
    const element = dialog.current;
    if (element && !element.open) element.showModal();
    return () => { if (element?.open) element.close(); };
  }, []);
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const body = { name: name.trim(), provider: providerId, ...(provider?.base_url_editable ? { base_url: baseUrl.trim() } : {}), ...(apiKey ? { api_key: apiKey } : {}) };
      if (current) await updateModelConnection(tenant, current.id, body);
      else await createModelConnection(tenant, body);
      saved();
    } catch (reason) { setError(errorText(reason)); } finally { setBusy(false); }
  }
  return <dialog ref={dialog} className="qm-modal" onCancel={(event) => { event.preventDefault(); close(); }}><header><div><div className="eyebrow">MODEL PROVIDER</div><h2>{current ? "编辑模型 API" : "添加模型 API"}</h2></div><button className="qm-icon" type="button" aria-label="关闭弹窗" onClick={close}>×</button></header><form onSubmit={submit}>{error && <Alert>{error}</Alert>}<label>服务提供方<select value={providerId} onChange={(event) => { const id = event.target.value as ModelProvider["id"]; setProviderId(id); const selected = providers.find((item) => item.id === id); if (!name || name === provider?.label) setName(selected?.label || ""); if (selected?.default_base_url) setBaseUrl(selected.default_base_url); }}>{providers.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select><small>{provider?.description}</small></label><label>连接名称<input value={name} onChange={(event) => setName(event.target.value)} required maxLength={255} placeholder="例如：团队 DeepSeek" /></label>{provider?.base_url_editable ? <label>API Base URL<input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} required placeholder="https://api.example.com/v1" /><small>保存后后端会访问此地址下的 /models。</small></label> : <label>官方 API 地址<input value={provider?.default_base_url || ""} readOnly /><small>该地址由后端预设，无需手工填写。</small></label>}<label>API 密钥<input type="password" autoComplete="new-password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} required={!current?.api_key_configured && !!provider?.api_key_required} placeholder={current?.api_key_configured ? "留空则保留现有密钥" : provider?.api_key_required ? "粘贴 API 密钥" : "本地服务可留空"} /><small>密钥加密保存，保存后不会再次显示。</small></label><footer><span>保存后由后端读取当前密钥可访问的模型。</span><button type="button" onClick={close}>取消</button><button className="primary-button" disabled={busy} type="submit">{busy ? "读取中…" : "保存并读取模型"}</button></footer></form></dialog>;
}
