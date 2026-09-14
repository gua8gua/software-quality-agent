import { useEffect, useRef, useState, type FormEvent } from "react";
import { all, analysisRequest, date, errorText, get, post, runDisplayStatus, statusLabel, type Artifact, type Dataset, type Page, type Project, type Run } from "./api";
import { Alert, Empty, Loading, Modal, Pager } from "./common";
import "./ConsistencyAnalysis.css";

import { ConsistencyExplorer, consistencyPath } from "./ConsistencyExplorer";
import type { Outcome, Report } from "./consistencyModel";
const labels: Record<Outcome, string> = { implemented: "实现", missing_functionality: "缺失功能", conflict: "冲突", judgement_error: "判断出错" };
const states: Record<string, string> = { prepared: "待判断", running: "分析中", completed: "已完成", failed: "执行失败" };
interface History { analysis_kind?: string; document_relation?: string; id: string; status: string; created_at: string; tlr_run_id: string; dataset_id: string }
const hasBody = (a: Artifact) => a.kind !== "package" && a.structure?.content_status !== "reference_only" && (a.characters ?? a.content?.length ?? 0) > 0;
const documentKind = (a: Artifact) => !["code", "test_code", "package"].includes(a.kind);
const codeKind = (a: Artifact) => ["code", "test_code"].includes(a.kind);
interface Layer { id: string; label: string; artifact_ids: string[] }
export function eligibleTlr(run: Run, datasetId: string, artifacts: Artifact[], kind: "code" | "document" = "code") {
  const byId = new Map(artifacts.filter(hasBody).map(a => [a.external_id, a]));
  return run.dataset_id === datasetId && run.status === "completed"
    && ["completed", "partial"].includes(runDisplayStatus(run))
    && run.config.source_ids.length > 0 && run.config.target_ids.length > 0
    && run.config.source_ids.every(id => {
      const a = byId.get(id);
      return a && documentKind(a);
    })
    && run.config.target_ids.every(id => { const a = byId.get(id); return a && (kind === "code" ? codeKind(a) : documentKind(a)); });
}

export function ConsistencyPanel({ tenant, project, datasets, runs, refresh, changed }: {
  tenant: string; project: Project; datasets: Dataset[]; runs: Run[]; refresh: number; changed: () => void;
}) {
  const [open, setOpen] = useState(false), [page, setPage] = useState(0), [tick, setTick] = useState(0);
  const [history, setHistory] = useState<Page<History> | null>(null), [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    analysisRequest<Page<History>>("consistency", "/runs", tenant, project.id, undefined, { offset: String(page * 20), limit: "20" })
      .then(value => { if (active) { setHistory(value); setError(""); } }).catch(e => { if (active) setError(errorText(e)); });
    return () => { active = false; };
  }, [tenant, project.id, page, tick, refresh]);
  useEffect(() => {
    if (!history?.items.some(r => r.status === "running")) return;
    const timer = setTimeout(() => setTick(v => v + 1), 5000);
    return () => clearTimeout(timer);
  }, [history]);
  return <section className="qm-inset">
    <div className="qm-toolbar"><div><h3>生命周期一致性分析</h3><p className="qm-muted">选择文档与代码，或选择不同生命周期文档，检查实现、集合覆盖与矛盾。</p></div>
      <button className="qm-primary" disabled={!datasets.length} onClick={() => setOpen(true)}>新建一致性分析</button>
      <button onClick={() => setTick(v => v + 1)}>刷新记录</button></div>
    {error && <Alert>{error}</Alert>}
    {!history ? (!error && <Loading />) : !history.items.length ? <Empty title="还没有一致性分析记录"><p>可以复用所选类型的已完成追踪，也可以从项目文档和代码重新开始。</p></Empty> :
      <><div className="qm-table-wrap"><table><thead><tr><th>分析 / 创建时间</th><th>资料快照 / 分析类型</th><th>辅助 TLR</th><th>状态</th><th /></tr></thead>
        <tbody>{history.items.map(row => <tr key={row.id}><td><code>{row.id.slice(0, 8)}</code><small>{date(row.created_at)}</small></td>
          <td>{datasets.find(d => d.id === row.dataset_id)?.version || row.dataset_id.slice(0, 8)}<small>{row.analysis_kind === "document" ? "文档 → 文档" : "文档 → 代码"}</small></td>
          <td><a href={"#/projects/" + encodeURIComponent(project.id) + "/runs/" + row.tlr_run_id}>{row.tlr_run_id.slice(0, 8)}</a></td>
          <td>{states[row.status] || row.status}</td><td><a href={consistencyPath(project.id, row.id)+"/original"}>查看分析</a></td></tr>)}</tbody></table></div>
        <Pager page={page} size={20} total={history.total} set={setPage} /></>}
    {open && <StartAnalysis tenant={tenant} project={project} datasets={datasets} runs={runs} close={() => setOpen(false)}
      changed={changed} prepared={id => { setOpen(false); window.location.hash = consistencyPath(project.id, id) + "/start"; }} />}

  </section>;
}

function StartAnalysis({ tenant, project, datasets, runs, close, prepared, changed }: {
  tenant: string; project: Project; datasets: Dataset[]; runs: Run[]; close: () => void; prepared: (id: string) => void; changed: () => void;
}) {
  const [datasetId, setDatasetId] = useState(datasets[0]?.id || "");
  const [mode, setMode] = useState("fresh"), [tlrId, setTlrId] = useState("");
  const [analysisKind, setAnalysisKind] = useState<"code" | "document">("code");
  const [relation, setRelation] = useState("refinement"), [targetIds, setTargetIds] = useState<string[]>([]);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]), [loading, setLoading] = useState(true);
  const [ids, setIds] = useState<string[]>([]), [busy, setBusy] = useState(false), [stage, setStage] = useState("");
  const [error, setError] = useState(""), [createdTlr, setCreatedTlr] = useState("");
  const [layers, setLayers] = useState<Layer[]>([]);
  const [sourceLayer, setSourceLayer] = useState(""), [targetLayer, setTargetLayer] = useState("");
  useEffect(() => {
    let active = true; setLoading(true); setArtifacts([]); setLayers([]); setError(""); setTlrId(""); setIds([]); setTargetIds([]); setSourceLayer(""); setTargetLayer("");
    Promise.all([all<Artifact>("/datasets/" + datasetId + "/inventory", tenant, project.id),
      get<{ layers: Layer[] }>("/datasets/" + datasetId + "/layers", tenant, project.id)])
      .then(([rows, inventory]) => { if (active) { setArtifacts(rows); setLayers(inventory.layers); } }).catch(e => { if (active) setError(errorText(e)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [tenant, project.id, datasetId]);
  const available = runs.filter(r => eligibleTlr(r, datasetId, artifacts, analysisKind));
  const selectedTlr = available.find(r => r.id === tlrId);
  const targets = artifacts.filter(a => hasBody(a) && (analysisKind === "code" ? codeKind(a) : documentKind(a))
    && !ids.includes(a.external_id) && (mode === "fresh" || selectedTlr?.config.target_ids.includes(a.external_id)));
  const chosenTargets = targets.filter(a => targetIds.includes(a.external_id));
  const documentLayers = layers.map(layer => ({ ...layer, documents: artifacts.filter(a => layer.artifact_ids.includes(a.external_id) && hasBody(a) && documentKind(a)) })).filter(layer => layer.documents.length);
  const layerAllowed = (layer: typeof documentLayers[number], role: "source" | "target") => mode === "fresh" || !!selectedTlr && layer.documents.every(a => selectedTlr.config[role === "source" ? "source_ids" : "target_ids"].includes(a.external_id));
  const unavailableCode = artifacts.filter(a => codeKind(a) && !hasBody(a));
  function selectSource(value: string) {
    setSourceLayer(value); setIds(documentLayers.find(l => l.id === value)?.documents.map(a => a.external_id) || []);
    if (targetLayer === value) { setTargetLayer(""); setTargetIds([]); }
  }
  function changeKind(value: "code" | "document") {
    setAnalysisKind(value); setIds([]); setTlrId(""); setError(""); setSourceLayer(""); setTargetLayer("");
    setTargetIds(value === "code" ? artifacts.filter(a => hasBody(a) && codeKind(a)).map(a => a.external_id) : []);
  }
  function resetMode(value: string) { setMode(value); setIds([]); setTlrId(""); setSourceLayer(""); setTargetLayer(""); setTargetIds(value === "fresh" && analysisKind === "code" ? artifacts.filter(a => hasBody(a) && codeKind(a)).map(a => a.external_id) : []); setError(""); }
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(""); setCreatedTlr("");
    try {
      const scope = { tenant_id: tenant, project_id: project.id };
      let runId = selectedTlr?.id;
      if (mode === "fresh") {
        setStage("1 / 3 · 整理源文档条目与功能类别");
        const hierarchy = await analysisRequest<{ id: string; status: string }>("requirements", "/analyses", tenant, project.id,
          { ...scope, dataset_id: datasetId, source_ids: ids });
        if (hierarchy.status !== "completed") throw new Error("源文档层级整理未完成，请检查模型配置后重试。");
        setStage("2 / 3 · 新建所选文档与目标之间的追踪");
        const run = await post<Run>("/runs", tenant, project.id, {
          ...scope, dataset_id: datasetId, source_ids: ids, target_ids: chosenTargets.map(a => a.external_id),
          options: { requirements_run_id: hierarchy.id, target_preprocessor: "auto", top_k: 10, retrieval_backend: "python" },
        });
        setCreatedTlr(run.id); changed();
        const finished = await post<Run>("/runs/" + run.id + "/execute", tenant, project.id);
        changed();
        if (finished.status !== "completed") throw new Error("新建追踪尚未产出可用结果，可进入该 TLR 查看并恢复；完成或部分完成后可辅助分析。");
        runId = run.id;
      }
      if (!runId) throw new Error("请选择对应类型且已完成的 TLR。");
      setStage("准备一致性分析证据");
      const report = await analysisRequest<Report>("consistency", "/runs", tenant, project.id,
        { ...scope, tlr_run_id: runId, source_ids: ids, target_ids: chosenTargets.map(a => a.external_id), analysis_kind: analysisKind, document_relation: relation });
      prepared(report.id);
    } catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  }
  return <Modal title="新建一致性分析" wide close={() => !busy && close()}><form className="qm-consistency-form" onSubmit={submit}>
    <fieldset disabled={busy} style={{ border: 0, padding: 0 }}>
      <label>分析对象<select aria-label="分析对象" value={analysisKind} onChange={e => changeKind(e.target.value as "code" | "document")}><option value="code">文档 → 代码</option><option value="document">文档 → 文档</option></select></label>
      {analysisKind === "document" && <label>判断口径<select aria-label="判断口径" value={relation} onChange={e => setRelation(e.target.value)}><option value="refinement">下游集合是否覆盖、细化源文档</option><option value="agreement">同层文档对应内容是否一致</option></select><small>源文档是本次比较基准；上下文资料只用于解释，不代替目标覆盖。</small></label>}
      <label>资料快照<select aria-label="资料快照" value={datasetId} onChange={e => setDatasetId(e.target.value)}>{datasets.map(d => <option key={d.id} value={d.id}>{d.version} · {date(d.created_at)}</option>)}</select></label>
      <p className="qm-muted">资料快照是项目资料的固定版本。本次分析使用所选版本，后续上传资料会生成新版本，历史分析仍对应原版本。</p>
      <div className="qm-form-grid qm-consistency-modes">
        <label><input type="radio" name="consistency-mode" checked={mode === "fresh"} onChange={() => resetMode("fresh")} />从零开始</label>
        <label><input type="radio" name="consistency-mode" checked={mode === "existing"} onChange={() => resetMode("existing")} />使用已有 TLR 辅助（含部分完成）</label>
      </div>
      <p className="qm-muted">{mode === "fresh" ? "从当前快照整理源文档条目，匹配所选目标集合，再判断一致性；会保存新的追踪记录。" : "可选择当前快照已完成或部分完成、源端为文档且目标符合本次分析类型的追踪。仅有引用的工件不可选。"}</p>
      {mode === "existing" && <label>辅助追踪<select aria-label="辅助追踪" required value={tlrId} disabled={loading || busy} onChange={e => { setTlrId(e.target.value); setIds([]); setSourceLayer(""); setTargetLayer(""); setTargetIds(analysisKind === "code" ? available.find(r => r.id === e.target.value)?.config.target_ids || [] : []); }}>
        <option value="">请选择一次追踪</option>{available.map(r => <option key={r.id} value={r.id}>{date(r.created_at)} · {r.config.batch_label || (analysisKind === "code" ? "文档 → 代码" : "文档 → 文档")} · {r.id.slice(0, 8)} · {statusLabel[runDisplayStatus(r)]} · {r.counts.links || 0} 条关联</option>)}</select>
        {!loading && !available.length && <p>当前快照没有可用追踪，可以选择“从零开始”。</p>}</label>}
      {selectedTlr && runDisplayStatus(selectedTlr) === "partial" && <p className="qm-muted">本次复用部分完成追踪中已确认的关联。未完成匹配不代表功能缺失；分析会保留匹配不完整的范围信息。</p>}
      {loading ? <Loading /> : <>
        <h3>选择源文档</h3>
        <label>源文档层级<select aria-label="源文档层级" required value={sourceLayer} onChange={e => selectSource(e.target.value)}>
          <option value="">请选择一个层级</option>{documentLayers.map(layer => <option key={layer.id} value={layer.id} disabled={!layerAllowed(layer, "source")}>{layer.label} · 全部 {layer.documents.length} 份文档{!layerAllowed(layer, "source") ? "（辅助追踪未覆盖整层）" : ""}</option>)}
        </select></label>
        <p className="qm-muted">已选 {ids.length} 份源文档。选择层级后包含该层全部有正文的文档；引用节点和包节点不参与分析。</p>
        {mode === "existing" && <p className="qm-muted">辅助追踪的输入范围须包含所选整层文档，匹配结果可以部分完成；输入范围不包含整层时请使用“从零开始”。</p>}
        <h3>选择目标{analysisKind === "code" ? "代码" : "文档"}集合</h3>
        {analysisKind === "document" ? <label>目标文档层级<select aria-label="目标文档层级" required value={targetLayer} onChange={e => { setTargetLayer(e.target.value); setTargetIds(documentLayers.find(l => l.id === e.target.value)?.documents.map(a => a.external_id) || []); }}>
          <option value="">请选择一个层级</option>{documentLayers.map(layer => <option key={layer.id} value={layer.id} disabled={layer.id === sourceLayer || !layerAllowed(layer, "target")}>{layer.label} · 全部 {layer.documents.length} 份文档{layer.id === sourceLayer ? "（已选为源）" : !layerAllowed(layer, "target") ? "（辅助追踪未覆盖整层）" : ""}</option>)}
        </select></label> : <>
        <div className="qm-toolbar"><button type="button" onClick={() => setTargetIds(targets.map(a => a.external_id))}>选择全部目标</button><button type="button" onClick={() => setTargetIds([])}>清空目标</button></div>
        <div style={{ maxHeight: 220, overflow: "auto" }}>{targets.map(a => <label key={a.id} style={{ display: "flex", gap: 8, padding: 6 }}>
          <input type="checkbox" aria-label={"目标：" + (a.structure?.title || a.external_id)} checked={targetIds.includes(a.external_id)}
            onChange={e => setTargetIds(old => e.target.checked ? [...old, a.external_id] : old.filter(id => id !== a.external_id))} />
          {a.structure?.title || a.external_id}<small>{a.locator}</small></label>)}</div>
        {!!unavailableCode.length && <><p role="status">当前快照还有 {unavailableCode.length} 个代码条目缺少源码正文（仅引用或空文件），暂不可分析。请在项目资料库上传对应源码并选择新快照。</p>
          <details><summary>查看缺少正文的代码条目（{unavailableCode.length}）</summary><div style={{ maxHeight: 220, overflow: "auto" }}>{unavailableCode.map(a => <label key={a.id} style={{ display: "flex", gap: 8, padding: 6 }}><input type="checkbox" disabled />{a.structure?.title || a.external_id}<small>缺少源码正文 · {a.locator}</small></label>)}</div></details></>}
        {!targets.length && !unavailableCode.length && <p>{mode === "existing" && !selectedTlr ? "选择辅助追踪后显示目标代码。" : "当前快照没有代码正文，请上传源码或选择包含源码的资料快照。"}</p>}
        </>}
        <p className="qm-muted">已选 {chosenTargets.length} 份目标；将联合检查整组目标，结论仅限所选范围。</p>
      </>}
    </fieldset>
    {error && <Alert>{error}</Alert>}
    {createdTlr && <p>已创建追踪：<a href={"#/projects/" + encodeURIComponent(project.id) + "/runs/" + createdTlr}>{createdTlr.slice(0, 8)}</a></p>}
    {busy && <p role="status">{stage}… 请保持页面打开，后续步骤将依次执行。</p>}
    <footer><button type="button" disabled={busy} onClick={close}>取消</button><button className="qm-primary" disabled={busy || loading || !ids.length || (!chosenTargets.length || (mode === "existing" && !selectedTlr))}>{busy ? "正在准备…" : "开始一致性分析"}</button></footer>
  </form></Modal>;
}

export function AnalysisReport({ tenant, project, id, view = "original", unitId }: { tenant: string; project: string; id: string; view?: string; unitId?: string }) {
  const autoStart = view === "start";
  const [report, setReport] = useState<Report | null>(null), [error, setError] = useState("");
  const [busy, setBusy] = useState(false), [tick, setTick] = useState(0);
  useEffect(() => {
    let active = true;
    analysisRequest<Report>("consistency", "/runs/" + id, tenant, project).then(value => { if (active) setReport(value); })
      .catch(e => { if (active) setError(errorText(e)); });
    return () => { active = false; };
  }, [tenant, project, id, tick]);
  useEffect(() => {
    if (report?.status !== "running" || busy) return;
    const timer = setTimeout(() => setTick(v => v + 1), 5000);
    return () => clearTimeout(timer);
  }, [report, busy]);
  async function execute() {
    setBusy(true); setError("");
    try { setReport(await analysisRequest<Report>("consistency", "/runs/" + id + "/execute", tenant, project, {})); }
    catch (e) { setError(errorText(e)); setTick(v => v + 1); }
    finally { setBusy(false); }
  }
  const started = useRef(false);
  useEffect(() => {
    if (autoStart && report?.status === "prepared" && !started.current) {
      started.current = true; void execute();
    }
  }, [autoStart, report?.status]);
  const displayLabels = report?.outcome_dictionary || labels;
  function download() {
    const href = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: "application/json" }));
    const link = document.createElement("a"); link.href = href; link.download = "consistency-" + id + ".json"; link.click();
    setTimeout(() => URL.revokeObjectURL(href), 1000);
  }
  return <><a className="qm-back" href={"#/projects/" + encodeURIComponent(project) + "/analyses"}>返回一致性分析列表</a><h1>一致性分析详情</h1>
    <div className="qm-consistency-report">
    {error && <Alert>{error}</Alert>}
    {!report ? (!error && <Loading />) : <>
      <p><code>{report.id.slice(0, 8)}</code> · {busy ? "分析中" : states[report.status] || report.status} · {date(report.created_at)}</p>
      <div className="qm-toolbar">
        {(report.status === "prepared" || report.status === "failed") && <button className="qm-primary" disabled={busy} onClick={execute}>{busy ? "正在判断…" : report.status === "prepared" ? "执行一致性判断" : "重试失败的判断"}</button>}
        <button disabled={busy} onClick={() => setTick(v => v + 1)}>刷新</button><button onClick={download}>下载完整 JSON</button>
      </div>
      {report.status === "prepared" && <p>证据已保存，执行后将逐条判断代码实现情况。</p>}
      {busy && <p role="status">正在联合判断目标集合对源文档各部分的对应情况…</p>}
      {report.results.error && <Alert>{report.results.error}</Alert>}
      <p>已处理 {report.metrics.processed_requirements} / {report.metrics.selected_requirements} 份源文档。以下结果允许共存，结论仅限所选目标集合，局部对应不代表整体满足。</p>
      <div className="qm-summary-strip">{Object.entries(displayLabels).map(([value, label]) => <div key={value}><strong>{report.metrics.outcome_counts[value as Outcome] || 0}</strong><span>{label}</span></div>)}</div>
      <ConsistencyExplorer report={report} tenant={tenant} project={project} view={view} unitId={unitId} />
    </>}
    </div>
  </>;
}
