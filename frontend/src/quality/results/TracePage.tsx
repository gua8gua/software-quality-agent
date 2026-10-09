import { useEffect, useMemo, useState } from "react";
import { Button, Select, Table, Tabs } from "antd";
import { ArrowUpRight, CheckCircle2, Download, FileText, GitBranch, Link2, RefreshCw, TriangleAlert } from "lucide-react";
import { api as library, part } from "../api";
import { navigate } from "../../navigation";
import { resultsApi, type Candidate } from "./api";
import { Busy, ErrorNotice, Metrics, NoData, ResultShell, RunSelect, Status, exportJson, useRead } from "./shared";
import { NodeReader } from "./NodeReader";
import "@xyflow/react/dist/style.css";
import "./results.css";
import { TraceDocumentHierarchy, type TraceExpansion } from "./TraceDocumentHierarchy";
import { title, pathOf } from "./canonical";

export default function TracePage({tenant, project, initialRun, initialNode}: {tenant: string; project: string; initialRun?: string; initialNode?: string}) {
  const access = useMemo(() => resultsApi(tenant, project), [tenant, project]);
  const [revision, setRevision] = useState(0); const [runId, setRunId] = useState(initialRun || ""); const [source, setSource] = useState(initialNode || ""); const [selected, setSelected] = useState("");
  const [query, setQuery] = useState(""); const [artifact, setArtifact] = useState(""); const [relation, setRelation] = useState(""); const [targetArtifact, setTargetArtifact] = useState("");
  const [expansionByRun, setExpansionByRun] = useState<Record<string, TraceExpansion>>({});
  const projectInfo = useRead(() => library.project(tenant, project), [tenant, project]);
  const runs = useRead(signal => access.runs(signal), [access, revision]);
  useEffect(() => { if (!runId && runs.data?.length) setRunId(runs.data.find(r => r.status === "completed")?.run_id || runs.data[0].run_id); }, [runs.data, runId]);
  const data = useRead(signal => runId ? access.graph(runId, signal) : Promise.resolve(null), [access, runId, revision]);
  const graph = data.data;
  useEffect(() => {
    if (!graph) return;
    const allowed = graph.units.filter(u => u.side === "source" && (!artifact || u.artifact_id === artifact)).filter(u => {
      const n = graph.nodes.find(n => n.node_id === u.node_id);
      return n && (!query || [title(n), ...pathOf(n, graph.nodes), n.node_id].join(" ").toLowerCase().includes(query.toLowerCase()));
    });
    const selectedSource = graph.nodes.find(node => node.node_id === source);
    const sourceArtifactIds = new Set(graph.units.filter(unit => unit.side === "source" && (!artifact || unit.artifact_id === artifact)).map(unit => unit.artifact_id));
    // A section/document can be inspected without being a TLR leaf. Only an actual
    // scope change invalidates selection; selecting it must not jump to a leaf.
    const sourceInScope = selectedSource && sourceArtifactIds.has(selectedSource.artifact_id);
    if (!sourceInScope) { setSource(allowed[0]?.node_id || ""); setSelected(""); }
  }, [graph, source, artifact, query]);
  const sourceIsUnit = Boolean(graph?.units.some(unit => unit.side === "source" && unit.node_id === source));
  const candidates = useRead(signal => sourceIsUnit && runId ? access.candidates(runId, source, signal) : Promise.resolve([]), [access, runId, source, sourceIsUnit, revision]);
  const activeRun = runs.data?.find(r => r.run_id === runId);
  const visibleGraph = graph ? {...graph, links: graph.links.filter(l => !targetArtifact || graph.units.some(u => u.node_id === l.target_node_id && u.artifact_id === targetArtifact))} : null;
  const filteredLinks = visibleGraph?.links.filter(l => l.source_node_id === source && (!relation || l.relation === relation)) || [];
  const selectedNode = graph?.nodes.find(n => n.node_id === (selected || source));
  const sourceArtifacts = graph?.artifacts.filter(a => graph.units.some(u => u.side === "source" && u.artifact_id === a.artifact_id)) || [];
  const targetArtifacts = graph?.artifacts.filter(a => graph.units.some(u => u.side === "target" && u.artifact_id === a.artifact_id)) || [];
  function selectSource(id: string) { setSource(id); setSelected(""); }
  function changeRun(id: string) { setRunId(id); setSource(""); setSelected(""); setArtifact(""); setTargetArtifact(""); }
  return <ResultShell project={project} name={projectInfo.data?.name || ""} active="trace">
    <div className="result-title"><div><div className="eyebrow">TRACEABILITY · 已有运行结果</div><h1>TLR 追溯链接恢复结果</h1><p>沿文档真实层级查看需求与设计的关联，追溯关系不等于需求已满足。</p></div><div className="result-actions"><Button icon={<RefreshCw size={15} />} onClick={() => setRevision(v => v + 1)}>刷新</Button><Button type="primary" icon={<Download size={15} />} disabled={!graph} onClick={() => exportJson(`TLR-${runId}.json`, {run: activeRun, visualization: graph})}>导出结果</Button></div></div>
    <ErrorNotice error={projectInfo.error || runs.error || data.error} />
    <div className="run-bar"><RunSelect runs={runs.data || []} value={runId} onChange={changeRun} />{activeRun && <><Status value={activeRun.status} /><span>结果完整性：{activeRun.result_status}</span><code title={runId}>{runId}</code></>}</div>
    {runs.loading || data.loading ? <Busy /> : !runs.data?.length ? <section className="result-card"><NoData title="此项目尚无 TLR 运行" detail="本页不会自动生成追溯或 embedding。已有运行保存后，可点击刷新。" /></section> : graph && <>
      <Metrics items={[{title: "需求追溯单元", value: graph.units.filter(u => u.side === "source").length, hint: "本次运行源端 canonical 节点", icon: <FileText />}, {title: "设计追溯单元", value: graph.units.filter(u => u.side === "target").length, hint: "本次运行目标端 canonical 节点", icon: <FilesIcon />}, {title: "正式追溯链接", value: graph.links.length, hint: "仅已完成运行的正式 TraceLink", icon: <Link2 />, tone: "green"}, {title: "候选执行失败", value: graph.candidate_execution_counts.failed || 0, hint: "执行错误与语义不确定分开", icon: <TriangleAlert />, tone: "amber"}]} />
      {activeRun?.error && <ErrorNotice error={activeRun.error} />}
      <div className="trace-layout"><div className="trace-primary result-card"><div className="result-card-heading"><h2><GitBranch size={18} />需求 → 设计追溯视图</h2><span>选择需求查看其全部链接</span></div>
        <div className="trace-filters"><Select aria-label="需求文档" value={artifact} onChange={setArtifact} options={[{value: "", label: "全部需求文档"}, ...sourceArtifacts.map(a => ({value: a.artifact_id, label: a.filename}))]} /><Select aria-label="设计文档" value={targetArtifact} onChange={setTargetArtifact} options={[{value: "", label: "全部设计文档"}, ...targetArtifacts.map(a => ({value: a.artifact_id, label: a.filename}))]} /><Select aria-label="关系筛选" value={relation} onChange={setRelation} options={[{value: "", label: "全部正式关系"}, {value: "direct", label: "直接追溯"}, {value: "related", label: "相关"}]} /></div>
        <TraceDocumentHierarchy graph={graph} source={source} selected={selected} artifact={artifact} targetArtifact={targetArtifact} query={query} relation={relation} expansion={expansionByRun[graph.run_id]} onExpansion={value => setExpansionByRun(current => ({...current, [graph.run_id]: value}))} onSource={selectSource} onTarget={setSelected} onQuery={setQuery} />
        <section className="result-card result-table"><Tabs items={[{key: "links", label: `正式链接（${filteredLinks.length}）`, children: <Table rowKey="id" size="small" dataSource={filteredLinks} pagination={{pageSize: 8, showSizeChanger: true}} scroll={{x: 800}} onRow={l => ({onClick: () => setSelected(l.target_node_id), className: l.target_node_id === selected ? "selected-row" : ""})} columns={[{title: "需求节点", width: 200, render: () => <span className="table-preview">{title(graph.nodes.find(n => n.node_id === source))}</span>}, {title: "设计节点", width: 230, render: (_, l) => <span className="table-preview">{title(graph.nodes.find(n => n.node_id === l.target_node_id))}</span>}, {title: "关系", width: 120, render: (_, l) => <Status value={l.relation} />}, {title: "判断理由", dataIndex: "explanation"}]} />}, {key: "candidates", label: `候选诊断（${candidates.data?.length || 0}）`, children: <><ErrorNotice error={candidates.error} /><Table<Candidate> rowKey="candidate_id" loading={candidates.loading} size="small" dataSource={candidates.data} pagination={{pageSize: 8}} scroll={{x: 1020}} onRow={c => ({onClick: () => setSelected(c.target_node_id)})} expandable={{expandedRowRender: c => <><p>{c.explanation || "尚无语义判断理由"}</p><p>错误：{c.error_code || "无"} · 检索来源：{c.retrieval_sources.join(" / ")}</p><code>{c.candidate_id}</code></>}} columns={[{title: "设计节点", width: 220, render: (_, c) => <span className="table-preview">{title(graph.nodes.find(n => n.node_id === c.target_node_id))}</span>}, {title: "RRF 排名", dataIndex: "fused_rank", width: 90}, {title: "Dense 分数", render: (_, c) => c.dense_score?.toFixed(4) ?? "—", width: 100}, {title: "BM25 分数", render: (_, c) => c.bm25_score?.toFixed(3) ?? "—", width: 100}, {title: "RRF 分数", render: (_, c) => c.rrf_score.toFixed(5), width: 100}, {title: "关系", render: (_, c) => <Status value={c.relation} />}, {title: "执行", render: (_, c) => <Status value={c.execution_status} />}, {title: "校验", render: (_, c) => <Status value={c.validation_status} />}]} /><p className="result-footnote">检索分数不是置信度，不进行百分比换算。失败候选不会被显示成“无链接”。</p></>}]} /></section>
        <p className="hierarchy-note">左、右两侧均为实际 canonical 层级；连线只显示已保存的正式 TraceLink。搜索和文档筛选不会改变原始数据。</p>
      </div><aside className="trace-detail result-card"><div className="result-card-heading"><h2><FileText size={18} />{selected ? "设计节点详情" : "需求节点详情"}</h2>{selected && <Button type="link" size="small" onClick={() => setSelected("")}>返回需求</Button>}</div>{selectedNode ? <><NodeReader key={selectedNode.node_id} access={access} node={selectedNode.node_id} project={project} /><div className="detail-divider" /><div className="result-card-heading"><h2>关联设计</h2><span>{filteredLinks.length} 项</span></div><div className="linked-list">{filteredLinks.map(l => <button key={l.id} className={selected === l.target_node_id ? "linked-item active" : "linked-item"} onClick={() => setSelected(l.target_node_id)}><div><Status value={l.relation} /><ArrowUpRight size={14} /></div><strong>{title(graph.nodes.find(n => n.node_id === l.target_node_id))}</strong><small>{l.explanation || "未保存理由"}</small></button>)}</div><Button className="analysis-link" disabled={!graph.units.some(unit => unit.side === "source" && unit.node_id === source)} title="选择需求语块后可查看对应审核" icon={<CheckCircle2 size={16} />} onClick={() => navigate(`/projects/${part(project)}/analysis/${part(runId)}/${part(source)}`)}>查看此需求的审核</Button></> : <NoData title="未选择节点" detail="点击文档树中的需求。" />}</aside></div>
    </>}
  </ResultShell>;
}
function FilesIcon() { return <FileText />; }
