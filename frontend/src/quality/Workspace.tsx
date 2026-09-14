import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { ArrowLeft, ArrowUpRight, ChevronRight, Database, Download, FileText, FolderOpen, GitBranch, Layers, Plus, RefreshCw, Search, Settings2, ShieldCheck, Upload } from "lucide-react";
import { all, date, errorText, get, post, runDisplayStatus, statusLabel, url, type Artifact, type Capabilities, type Dataset, type Project, type Run, type Visualization } from "./api";
import { Alert, Empty, Loading, Pager } from "./common";
import { NewProject, UploadDialog } from "./Dialogs";
import { Results } from "./Results";
import { LayerAnalysis, LayerRunMatrix } from "./LayerAnalysis";
import { AnalysisReport, ConsistencyPanel } from "./ConsistencyAnalysis";
import { TlrBatchList, TlrBatchPage, batchKey, batchPath, groupBatches } from "./TlrBatches";
import { StructureTree, StructureDetail } from "./Structure";
import { ModelConfigPage } from "./ModelConfig";

const projectPath = (id: string) => `/projects/${encodeURIComponent(id)}`;
function navigate(path: string) { window.location.hash = path; }
function useRoute() {
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => { const update = () => setHash(window.location.hash); window.addEventListener("hashchange", update); return () => window.removeEventListener("hashchange", update); }, []);
  return useMemo(() => { try { return hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent); } catch { return []; } }, [hash]);
}

export default function Workspace() {
  const route = useRoute();
  useEffect(() => { window.scrollTo(0, 0); }, [route.join("/")]);
  const [tenant, setTenant] = useState(import.meta.env.VITE_TENANT_ID || "local");
  const [tenantDraft, setTenantDraft] = useState(tenant), [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [actionError, setActionError] = useState(""), [refresh, setRefresh] = useState(0);
  const executing = useRef(new Set<string>());
  useEffect(() => { let active = true; get<Capabilities>("/capabilities", tenant).then(value => { if (active) setCapabilities(value); }).catch(() => { if (active) setCapabilities(null); }); return () => { active = false; }; }, [tenant, refresh]);
  const kinds = useMemo(() => new Map(capabilities?.kinds.map(k => [k.id, k.label]) || []), [capabilities]);
  const queue = useRef(Promise.resolve());
  const begin = useCallback((value: Run | Run[]) => {
    const runs=Array.isArray(value)?value:[value];if(!runs.length)return;
    const batchId=Array.isArray(value)?runs[0].config.plan_id:undefined;
    if(batchId&&runs.every(run=>run.config.plan_id===batchId)){
      const key=`batch:${batchId}`;if(executing.current.has(key))return;executing.current.add(key);
      window.location.hash = batchPath(runs[0].project_id, batchKey(runs[0]));setActionError("");
      void post<{failures:{run_id:string;message:string}[]}>(`/plans/${batchId}/resume`,tenant,runs[0].project_id).then(result=>{if(result.failures.length)setActionError(`批次中有 ${result.failures.length} 个任务仍未完成：${result.failures.map(item=>item.run_id.slice(0,8)).join("、")}`);}).catch(e=>setActionError(errorText(e))).finally(()=>{executing.current.delete(key);setRefresh(v=>v+1);});
      return;
    }
    navigate(runs.length===1?`${projectPath(runs[0].project_id)}/runs/${runs[0].id}`:projectPath(runs[0].project_id));
    for(const run of runs){
      if(executing.current.has(run.id))continue;executing.current.add(run.id);
      queue.current=queue.current.then(async()=>{setActionError("");try{const resume=run.status==="failed"||(run.status==="completed"&&run.stage==="completed_with_errors");await post<Run>(`/runs/${run.id}/${resume?"resume":"execute"}`,tenant,run.project_id);}catch(e){setActionError(errorText(e));}finally{executing.current.delete(run.id);setRefresh(v=>v+1);}});
    }
  }, [tenant]);
  const project = route[0] === "projects" ? route[1] : undefined;
  const isModels = route[0] === "models";
  const detail = route[2];
  const detailLabel: Record<string, string> = { runs: "TLR 子任务结果", batches: "TLR 批次", tlr: "TLR 批次记录", consistency: "一致性分析详情", analyses: "一致性分析", artifacts: "资料详情" };
  function applyTenant(event: FormEvent) { event.preventDefault(); const value = tenantDraft.trim(); if (value) { setTenant(value); setActionError(""); navigate("/projects"); } }
  return <div className="qm-app"><aside className="qm-sidebar"><a className="qm-brand" href="#/projects"><span><ShieldCheck size={23} /></span><div>软件质量<span>QUALITY WORKSPACE</span></div></a><p className="qm-nav-label">工作台</p><a className={`qm-nav-item ${!isModels ? "active" : ""}`} href="#/projects"><FolderOpen size={19} />项目资料库</a><a className={`qm-nav-item ${isModels ? "active" : ""}`} href="#/models"><Settings2 size={19} />模型配置</a><div className="qm-sidebar-bottom"><Database size={18} /><span>项目 · 制品 · 追踪关系<small>软件质量管理后端</small></span></div></aside>
    <div className="qm-shell"><header className="qm-topbar"><div className="qm-breadcrumb"><a href={isModels ? "#/models" : "#/projects"}>{isModels ? "模型配置" : "项目资料库"}</a>{project && <><ChevronRight size={14} /><a href={`#${projectPath(project)}`}>{project}</a></>}{detail && <><ChevronRight size={14} /><span>{detailLabel[detail] || "资料详情"}</span></>}</div><form className="qm-tenant" onSubmit={applyTenant}><label htmlFor="workspace">工作空间</label><input id="workspace" value={tenantDraft} onChange={e => setTenantDraft(e.target.value)} maxLength={128} required /><button disabled={!tenantDraft.trim()}>切换</button></form></header>
      <main className="qm-main">{actionError && <Alert>{actionError}</Alert>}
        {isModels ? <ModelConfigPage key={tenant} tenant={tenant} /> : !project ? <Projects key={tenant} tenant={tenant} /> : detail === "artifacts" && route[3] ? <ArtifactPage key={`${tenant}-${route[3]}`} tenant={tenant} project={project} id={route[3]} kinds={kinds} /> : detail === "runs" && route[3] ? <RunPage key={`${tenant}-${route[3]}`} tenant={tenant} project={project} id={route[3]} refresh={refresh} begin={begin} /> : detail === "batches" && route[3] ? <TlrBatchPage key={`${tenant}-${route[3]}`} tenant={tenant} project={project} id={route[3]} refresh={refresh} begin={begin} /> : detail === "consistency" && route[3] ? <AnalysisReport key={`${tenant}-${route[3]}`} tenant={tenant} project={project} id={route[3]} view={route[4]} unitId={route[5]} /> : <ProjectPage initialTab={detail === "tlr" ? "runs" : detail === "analyses" ? "consistency" : "data"} key={`${tenant}-${project}-${detail}`} tenant={tenant} projectId={project} refresh={refresh} capabilities={capabilities} kinds={kinds} begin={begin} />}
      </main>
    </div></div>;
}

function Projects({ tenant }: { tenant: string }) {
  const [projects, setProjects] = useState<Project[]>([]), [loading, setLoading] = useState(true), [error, setError] = useState("");
  const [search, setSearch] = useState(""), [newProject, setNewProject] = useState(false), [tick, setTick] = useState(0), [page, setPage] = useState(0);
  useEffect(() => { let active = true; setLoading(true); setError(""); all<Project>("/projects", tenant).then(rows => { if (active) setProjects(rows); }).catch(e => { if (active) setError(errorText(e)); }).finally(() => { if (active) setLoading(false); }); return () => { active = false; }; }, [tenant, tick]);
  const filtered = projects.filter(p => `${p.name} ${p.id} ${p.description}`.toLowerCase().includes(search.toLowerCase()));
  return <><div className="qm-heading"><div><div className="qm-eyebrow">PROJECT LIBRARY</div><h1>所有项目</h1><p>从项目出发，查看软件资料、版本和追踪检测结果。</p></div><button className="qm-primary" onClick={() => setNewProject(true)}><Plus size={18} />新建项目</button></div>
    <div className="qm-summary-strip"><div><strong>{projects.length}</strong><span>软件项目</span></div><div><strong>{projects.reduce((sum, p) => sum + (p.dataset_count || 0), 0)}</strong><span>资料快照</span></div><div><strong>{projects.reduce((sum, p) => sum + (p.run_count || 0), 0)}</strong><span>TLR 运行记录</span></div></div>
    <div className="qm-toolbar qm-project-tools"><div className="qm-search"><Search size={17} /><input aria-label="搜索项目" placeholder="搜索项目名称、标识或说明…" value={search} onChange={e => { setSearch(e.target.value); setPage(0); }} /></div><button onClick={() => setTick(v => v + 1)} disabled={loading}><RefreshCw size={16} />刷新</button></div>
    {error ? <Alert>{error} 当前未展示任何替代或示例数据。</Alert> : loading ? <Loading /> : !filtered.length ? <Empty title={projects.length ? "没有匹配的项目" : "当前工作空间还没有项目"}><p>新建项目后，上传需求、设计、代码或测试资料。</p><button className="qm-primary" onClick={() => setNewProject(true)}>新建项目</button></Empty> : <><div className="qm-project-grid">{filtered.slice(page * 12, (page + 1) * 12).map(p => <a className="qm-project-card" key={p.id} href={`#${projectPath(p.id)}`}><div className="qm-card-top"><span className="qm-folder-icon"><FolderOpen size={23} /></span><ArrowUpRight size={18} /></div><h2>{p.name}</h2><code>{p.id}</code><p>{p.description || "暂无项目说明"}</p><div className="qm-card-counts"><span><Layers size={15} />{p.dataset_count || 0} 份资料快照</span><span><GitBranch size={15} />{p.run_count || 0} 次 TLR</span></div><div className="qm-card-footer">进入项目<ChevronRight size={17} /></div></a>)}</div><Pager page={page} size={12} total={filtered.length} set={setPage} /></>}
    {newProject && <NewProject tenant={tenant} close={() => setNewProject(false)} saved={p => { setNewProject(false); navigate(projectPath(p.id)); }} />}
  </>;
}

function ProjectPage({ tenant, projectId, capabilities, kinds, begin, refresh, initialTab = "data" }: { initialTab?: string; refresh: number; tenant: string; projectId: string; capabilities: Capabilities | null; kinds: Map<string, string>; begin: (run: Run | Run[]) => void }) {
  const [project, setProject] = useState<Project | null>(null), [datasets, setDatasets] = useState<Dataset[]>([]), [runs, setRuns] = useState<Run[]>([]);
  const [datasetId, setDatasetId] = useState(""), [artifacts, setArtifacts] = useState<Artifact[]>([]), [loading, setLoading] = useState(true), [inventoryLoading, setInventoryLoading] = useState(false);
  const [error, setError] = useState(""), [inventoryError, setInventoryError] = useState(""), [tick, setTick] = useState(0);
  const [tab, setTab] = useState(initialTab), [search, setSearch] = useState(""), [kind, setKind] = useState("all"), [page, setPage] = useState(0);
  const [upload, setUpload] = useState(false), [analysis, setAnalysis] = useState(false);
  const dataset = datasets.find(d => d.id === datasetId);
  useEffect(() => {
    let active = true; if (!project) setLoading(true); setError("");
    Promise.all([get<Project>(`/projects/${encodeURIComponent(projectId)}`, tenant), all<Dataset>(`/projects/${encodeURIComponent(projectId)}/datasets`, tenant), all<Run>(`/projects/${encodeURIComponent(projectId)}/runs`, tenant)])
      .then(([p, ds, rs]) => { if (!active) return; setProject(p); setDatasets(ds); setRuns(rs); setDatasetId(old => ds.some(d => d.id === old) ? old : ds[0]?.id || ""); })
      .catch(e => { if (active) setError(errorText(e)); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [tenant, projectId, tick, refresh]);
  useEffect(() => { if (!runs.some(r=>r.status==="running" || r.status==="pending")) return; const timer=setTimeout(()=>setTick(v=>v+1),3000); return ()=>clearTimeout(timer); },[runs]);
  useEffect(() => {
    let active = true; setArtifacts([]); setPage(0); setInventoryError("");
    if (!datasetId) return;
    setInventoryLoading(true); all<Artifact>(`/datasets/${datasetId}/inventory`, tenant, projectId).then(rows => { if (active) setArtifacts(rows); }).catch(e => { if (active) setInventoryError(errorText(e)); }).finally(() => { if (active) setInventoryLoading(false); });
    return () => { active = false; };
  }, [tenant, projectId, datasetId]);
  const filtered = artifacts.filter(a => (kind === "all" || a.kind === kind) && `${a.external_id} ${a.locator} ${a.structure?.title || ""} ${a.structure?.original_id || ""}`.toLowerCase().includes(search.toLowerCase()));
  const batchCount = groupBatches(runs).length;
  if (loading) return <Loading />;
  if (error) return <Alert>{error}</Alert>;
  if (!project) return <Empty title="项目不存在" />;
  return <><a className="qm-back" href="#/projects"><ArrowLeft size={15} />所有项目</a><div className="qm-heading"><div><div className="qm-eyebrow">PROJECT / {project.id}</div><h1>{project.name}</h1><p>{project.description || "查看项目资料与历史分析记录"}</p></div><div className="qm-toolbar"><button disabled={!datasets.length} onClick={() => setTab("consistency")}><ShieldCheck size={17} />一致性分析</button><button disabled={!capabilities} onClick={() => setUpload(true)}><Upload size={17} />上传资料</button><button className="qm-primary" disabled={!dataset || artifacts.length < 2 || inventoryLoading || !!inventoryError} onClick={() => setAnalysis(true)}><GitBranch size={17} />重新进行 TLR 检测</button></div></div>
    {capabilities && (!capabilities.embedding_configured || !capabilities.llm_configured) && <div className="qm-notice">环境变量中的模型接口尚未配置完整。你可以在 <a href="#/models">模型配置</a> 中为 TLR 任务选择模型；任务绑定会优先于 .env。</div>}
    <div className="qm-summary-strip"><div><strong>{artifacts.length}</strong><span>当前快照制品</span></div><div><strong>{datasets.length}</strong><span>资料快照</span></div><div><strong>{batchCount}</strong><span>TLR 批次</span></div><div><strong>{runs.filter(r => r.status === "completed").length}</strong><span>已完成子任务</span></div></div>
    <section className="qm-panel"><div className="qm-panel-head"><div className="qm-tabs" role="tablist"><button role="tab" aria-selected={tab === "consistency"} onClick={() => setTab("consistency")}>一致性分析</button><button role="tab" aria-selected={tab === "data"} onClick={() => setTab("data")}>资料清单</button><button role="tab" aria-selected={tab === "structure"} onClick={() => setTab("structure")}>结构关系</button><button role="tab" aria-selected={tab === "runs"} onClick={() => setTab("runs")}>TLR 运行记录 <span>{batchCount} 批次</span></button></div><button onClick={() => setTick(v => v + 1)}><RefreshCw size={15} />刷新</button></div>
      {tab === "data" && <><div className="qm-toolbar qm-inset"><label className="qm-inline-label">资料快照<select value={datasetId} onChange={e => { setDatasetId(e.target.value); setKind("all"); setSearch(""); }} aria-label="资料快照">{!datasets.length && <option value="">暂无快照</option>}{datasets.map(d => <option value={d.id} key={d.id}>{d.version} · {date(d.created_at)}</option>)}</select></label><input aria-label="搜索制品" placeholder="搜索标识或文件名…" value={search} onChange={e => { setSearch(e.target.value); setPage(0); }} /><select value={kind} aria-label="筛选文件业务类型" onChange={e => { setKind(e.target.value); setPage(0); }}><option value="all">全部业务类型</option>{[...new Set(artifacts.map(a => a.kind))].map(k => <option key={k} value={k}>{kinds.get(k) || k}</option>)}</select></div>
        {inventoryError ? <Alert>{inventoryError}</Alert> : inventoryLoading ? <Loading /> : !filtered.length ? <Empty title={artifacts.length ? "没有匹配的资料" : "尚未上传项目资料"}><p>每个文件都需指定所属项目与业务类型。</p><button disabled={!capabilities} onClick={() => setUpload(true)}>上传本地文件</button></Empty> : <><div className="qm-table-wrap"><table><thead><tr><th>资料标识 / 文件</th><th>业务类型</th><th>版本</th><th>正文字符数</th><th>原始文件</th><th /></tr></thead><tbody>{filtered.slice(page * 20, (page + 1) * 20).map(a => <tr key={a.id}><td><a className="qm-artifact-name" href={`#${projectPath(projectId)}/artifacts/${a.id}`}><FileText size={17} /><span>{a.structure?.title || a.structure?.original_id || a.external_id}<small>{a.locator || "未提供文件位置"}</small></span></a></td><td><span className="qm-type">{kinds.get(a.kind) || a.kind}</span></td><td>{a.revision}</td><td className="qm-mono">{a.characters?.toLocaleString()}</td><td>{a.structure?.content_status === "reference_only" ? "仅有引用" : a.original_file_id ? "已保存" : "文本导入"}</td><td><a className="qm-text-link" href={`#${projectPath(projectId)}/artifacts/${a.id}`}>查看详情 <ChevronRight size={14} /></a></td></tr>)}</tbody></table></div><Pager page={page} size={20} total={filtered.length} set={setPage} /></>}
      </>}
      <div hidden={tab !== "consistency"}><ConsistencyPanel tenant={tenant} project={project} datasets={datasets} runs={runs} refresh={tick + refresh} changed={() => setTick(v => v + 1)} /></div>
      {tab === "structure" && <StructureTree artifacts={artifacts} datasetId={datasetId} tenant={tenant} project={projectId} />}
      {tab === "runs" && <TlrBatchList runs={runs} datasets={datasets} project={projectId} />}
    </section>
    {upload && capabilities && <UploadDialog tenant={tenant} project={project} dataset={dataset} capabilities={capabilities} close={() => setUpload(false)} saved={ds => { setUpload(false); setDatasets(old => [ds, ...old]); setDatasetId(ds.id); setTab("data"); setTick(v => v + 1); }} />}
    {analysis && dataset && <LayerAnalysis tenant={tenant} project={project} dataset={dataset} artifacts={artifacts} kinds={kinds} close={() => setAnalysis(false)} created={r => { setAnalysis(false); setRuns(old=>[...r,...old]); setTab("runs"); begin(r); }} />}
  </>;
}

function ArtifactPage({ tenant, project, id, kinds }: { tenant: string; project: string; id: string; kinds: Map<string, string> }) {
  const [data, setData] = useState<Artifact | null>(null), [error, setError] = useState(""), [raw, setRaw] = useState(false);
  useEffect(() => { let active = true; get<Artifact>(`/artifacts/${id}`, tenant, project).then(a => { if (active) setData(a); }).catch(e => { if (active) setError(errorText(e)); }); return () => { active = false; }; }, [id, tenant, project]);
  if (error) return <Alert>{error}</Alert>;
  if (!data) return <Loading />;
  return <><a className="qm-back" href={`#${projectPath(project)}`}><ArrowLeft size={15} />返回项目</a><div className="qm-heading"><div><div className="qm-eyebrow">ARTIFACT DETAIL</div><h1>{data.external_id}</h1><p>{data.locator}</p></div><a className="qm-button" href={url(`/artifacts/${id}/download`, tenant, project)}><Download size={17} />{data.original_file_id ? "下载原始文件" : "下载正文"}</a></div><div className="qm-detail-grid"><section className="qm-panel"><div className="qm-panel-head"><h2>{raw ? "结构化记录" : "完整正文"}</h2><button onClick={() => setRaw(v => !v)}>{raw ? "查看正文" : "查看 JSON"}</button></div><pre className="qm-document">{raw ? JSON.stringify(data, null, 2) : data.content}</pre></section><aside className="qm-panel qm-metadata"><h2>资料信息</h2><dl><dt>所属项目</dt><dd><a href={`#${projectPath(project)}`}>{project}</a></dd><dt>业务类型</dt><dd>{kinds.get(data.kind) || data.kind}</dd><dt>制品版本</dt><dd>{data.revision}</dd><dt>正文字符数</dt><dd>{data.content?.length.toLocaleString()}</dd><dt>记录 ID</dt><dd className="qm-mono">{data.id}</dd><dt>正文 SHA-256</dt><dd className="qm-mono">{data.sha256}</dd><dt>项目与类型来源</dt><dd>外部输入 / 用户指定</dd></dl></aside></div><StructureDetail artifact={data} tenant={tenant} project={project} /></>;
}

const stages = [ ["preprocessing", "预处理"], ["embedding", "向量化"], ["retrieval", "候选检索"], ["classification", "逐对判定"], ["aggregation", "链接聚合"], ["completed", "完成"] ];
function RunPage({ tenant, project, id, refresh, begin }: { tenant: string; project: string; id: string; refresh: number; begin: (r: Run | Run[]) => void }) {
  const [run, setRun] = useState<Run | null>(null), [data, setData] = useState<Visualization | null>(null), [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [batchRuns, setBatchRuns] = useState<Run[]>([]);
  const [error, setError] = useState(""), [tick, setTick] = useState(0);
  useEffect(() => {
    let active = true; let timer: ReturnType<typeof setTimeout>;
    async function load() {
      try { const r = await get<Run>(`/runs/${id}`, tenant, project); if (!active) return; setRun(r); setError("");
        if (r.status === "pending" || r.status === "running") timer = setTimeout(load, 2000);
      } catch (e) { if (active) { setError(errorText(e)); timer = setTimeout(load, 5000); } }
    } void load(); return () => { active = false; clearTimeout(timer); };
  }, [tenant, project, id, refresh, tick]);
  const datasetId = run?.dataset_id, status = run?.status;
  const planId = run?.config.plan_id;
  useEffect(() => { if (!datasetId) return; let active = true; all<Artifact>(`/datasets/${datasetId}/inventory`, tenant, project).then(a => { if (active) setArtifacts(a); }).catch(e => { if (active) setError(errorText(e)); }); return () => { active = false; }; }, [datasetId, tenant, project]);
  useEffect(() => { if (!planId) { setBatchRuns([]); return; } let active = true; get<{runs:Run[]}>(`/plans/${planId}/runs`, tenant, project).then(value => { if (active) setBatchRuns(value.runs); }).catch(e => { if (active) setError(errorText(e)); }); return () => { active = false; }; }, [planId, tenant, project, refresh, tick]);
  useEffect(() => { if (!status) return; let active = true; get<Visualization>(`/runs/${id}/visualization`, tenant, project).then(value => { if (active) setData(value); }).catch(e => { if (active) setError(errorText(e)); }); return () => { active = false; }; }, [tenant, project, id, status, refresh, tick]);
  const onArtifact = useCallback((artifactId: string) => navigate(`${projectPath(project)}/artifacts/${artifactId}`), [project]);
  if (!run) return error ? <Alert>{error}</Alert> : <Loading />;
  const step = stages.findIndex(s => s[0] === run.stage);
  const displayStatus = runDisplayStatus(run);
  const canResume = (run.status === "failed" || (run.status === "completed" && run.stage === "completed_with_errors")) && (run.counts.candidates || 0) > (run.counts.classified || 0);
  return <><a className="qm-back" href={batchPath(project, batchKey(run))}><ArrowLeft size={15} />返回所属批次</a><div className="qm-heading"><div><div className="qm-eyebrow">TRACEABILITY RUN / {run.id.slice(0, 8)}</div><h1>TLR 检测结果 <span className={`qm-badge ${displayStatus}`}>{statusLabel[displayStatus]}</span></h1><p>{run.config.batch_label || (run.config.plan_id ? `批次 ${run.config.plan_id.slice(0,8)}` : "单次运行")} · 创建于 {date(run.created_at)}</p></div><div className="qm-toolbar"><button onClick={() => setTick(v => v + 1)}><RefreshCw size={16} />刷新结果</button>{run.status === "pending" && <button className="qm-primary" onClick={() => begin(run)}>执行此运行</button>}{canResume && <button className="qm-primary" onClick={() => begin(run)}>从断点继续此运行</button>}</div></div>
    {error && <Alert>{error}</Alert>}{run.status === "failed" && <Alert>检测在“{stages.find(s => s[0] === run.stage)?.[1] || run.stage}”阶段失败（{run.error}）。已保存中间数据；修正配置后可返回项目重新检测。</Alert>}{displayStatus === "partial" && <div className="qm-notice">分析已完成可用部分，但有 {Array.isArray(run.manifest.node_failures) ? run.manifest.node_failures.length : 0} 个节点失败；结果中已保留并标注失败节点，未判定节点不能视为无关联。</div>}
    {planId&&<LayerRunMatrix runs={batchRuns} project={project} datasetId={run.dataset_id} resume={begin} fixedPlanId={planId} currentRunId={run.id} />}
    <div className="qm-steps">{stages.map(([key, label], index) => <div key={key} className={index < step || run.status === "completed" ? "done" : index === step ? "current" : ""}><span>{index + 1}</span>{label}</div>)}</div>
    <div className="qm-summary-strip"><div><strong>{run.config.source_ids.length}</strong><span>源制品</span></div><div><strong>{run.config.target_ids.length}</strong><span>目标制品</span></div><div><strong>{run.counts.classified || 0}<small> / {run.counts.candidates || 0}</small></strong><span>已判定 / 候选对</span></div><div><strong>{run.status === "completed" ? run.counts.links || 0 : "—"}</strong><span>最终追踪链接</span></div></div>
    {data ? <Results run={run} data={data} artifacts={artifacts} tenant={tenant} project={project} onArtifact={onArtifact} /> : <Loading />}
    <details className="qm-panel qm-run-info"><summary>查看运行配置与复现信息</summary><pre>{JSON.stringify({ config: run.config, manifest: run.manifest, counts: run.counts }, null, 2)}</pre></details>
  </>;
}
