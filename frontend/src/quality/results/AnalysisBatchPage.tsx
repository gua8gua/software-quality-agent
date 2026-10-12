import { useEffect, useMemo, useState } from "react";
import { Button, Checkbox, Collapse, Drawer, Input, Progress, Table, Tabs, Tag, Tree } from "antd";
import type { TreeDataNode } from "antd";
import { ArrowLeft, ArrowRight, CheckCircle2, FileText, Folder, GitBranch, Play, RefreshCw, Search, TriangleAlert } from "lucide-react";
import { navigate } from "../../navigation";
import { api as library, part } from "../api";
import { resultsApi, type Canonical } from "./api";
import { AssessmentPanel, AssessmentStatusTag } from "./AssessmentPanel";
import { distribution, hierarchyScope, type BatchReview } from "./analysisHierarchy";
import { NodeReader } from "./NodeReader";
import { title, pathOf } from "./canonical";
import { Busy, ErrorNotice, NoData, ResultShell, Status, useRead } from "./shared";
import "./results.css";

const categories = [
  {key: "implemented", name: "已实现", color: "#54b98a"}, {key: "uncovered", name: "无覆盖", color: "#efbc53"},
  {key: "issues", name: "存在异常", color: "#ea7977"}, {key: "analysis_error", name: "分析异常", color: "#a68adc"},
  {key: "not_analyzed", name: "未分析", color: "#c6cedb"},
] as const;

export default function AnalysisBatchPage({tenant, project, batchId}: {tenant: string; project: string; batchId: string}) {
  const access = useMemo(() => resultsApi(tenant, project), [tenant, project]);
  const [revision, setRevision] = useState(0), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [side, setSide] = useState<"source" | "target">("source"), [selected, setSelected] = useState("");
  const [expandedBySide, setExpandedBySide] = useState<{source: string[] | null; target: string[] | null}>({source: null, target: null});
  const [leafId, setLeafId] = useState(""), [query, setQuery] = useState(""), [readNode, setReadNode] = useState("");
  const [onlyProblems, setOnlyProblems] = useState(false), [showLeaves, setShowLeaves] = useState(true), [issueTab, setIssueTab] = useState("all");
  const info = useRead(() => library.project(tenant, project), [tenant, project]);
  const result = useRead(signal => access.batch(batchId, signal), [access, batchId, revision]);
  const files = useRead(() => library.artifacts(tenant, project), [tenant, project]);
  const batch = result.data;
  const tree = useRead(signal => batch ? access.graph(batch.tlr_run_id, signal) : Promise.resolve(null), [access, batch?.tlr_run_id]);
  const graph = tree.data;
  const model = useMemo(() => graph && batch ? hierarchyScope(graph, batch.reviews, side, batch.scope.target_artifact_ids) : null, [graph, batch, side]);
  useEffect(() => { if (model && !model.reviews(selected).length) setSelected(model.children.get("")?.[0]?.node_id || ""); }, [model, selected]);
  const scoped = model?.reviews(selected) || [];
  const focused = scoped.find(r => r.review_id === leafId) || scoped[0];
  const workspace = useRead(signal => focused ? access.workspace(focused.review_id, signal) : Promise.resolve(null), [access, focused?.review_id, revision]);
  const counts = distribution(batch?.reviews || []), localCounts = distribution(scoped);
  const finalized = batch?.reviews.filter(r => r.assessment?.finalized).length || 0;
  const percent = batch?.reviews.length ? Math.round(100 * finalized / batch.reviews.length) : 0;
  const current = model?.nodes.get(selected), children = model?.children.get(selected) || [];
  const links = graph?.links.filter(l => scoped.some(r => r.requirement_node_id === l.source_node_id)
    && graph.nodes.some(n => n.node_id === l.target_node_id && batch?.scope.target_artifact_ids.includes(n.artifact_id))) || [];
  const issues = scoped.filter(r => ["uncovered", "issues", "analysis_error"].includes(r.assessment?.status || ""));
  const issueRows = issues.filter(r => issueTab === "all" || r.assessment.status === issueTab);
  function selectNode(id: string) {
    setSelected(id); setLeafId(""); setReadNode("");
    if (!id || !model) return;
    const ancestors = new Set<string>(); let node = model.nodes.get(id);
    while (node?.parent_id && !ancestors.has(node.parent_id)) {
      ancestors.add(node.parent_id); node = model.nodes.get(node.parent_id);
    }
    setExpandedBySide(old => ({...old, [side]: [...new Set([...(old[side] || (model.children.get("") || []).map(n => n.node_id)), ...ancestors])]}));
  }
  function makeTree(nodes: Canonical[]): TreeDataNode[] {
    if (!model) return [];
    return nodes.flatMap(node => {
      const reviews = model.reviews(node.node_id), descendants = model.children.get(node.node_id) || [], nested = makeTree(descendants);
      const branch = descendants.length > 0;
      const match = !query.trim() || [title(node), ...pathOf(node, graph!.nodes)].join(" ").toLowerCase().includes(query.toLowerCase());
      const problem = reviews.some(r => ["issues", "uncovered", "analysis_error"].includes(r.assessment?.status || ""));
      if ((!match && !nested.length) || (onlyProblems && !problem) || (!showLeaves && !branch)) return [];
      const done = reviews.filter(r => r.assessment?.finalized).length;
      return [{key: node.node_id, title: <div className="analysis-tree-title"><span title={title(node)}>{title(node)}</span><small>{reviews.length}</small><em className={problem ? "problem" : done === reviews.length && done ? "done" : ""}>{done}/{reviews.length}</em></div>,
        icon: branch ? <Folder size={15} /> : <FileText size={14} />, children: nested}];
    });
  }
  async function resume() {
    setBusy(true); setError("");
    try { await access.runReviewAgentsBatch(batchId); setRevision(v => v + 1); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  }
  return <ResultShell project={project} name={info.data?.name || ""} active="analysis">
    <div className="task-list-header"><div><h2>{batch?.name || "完整工件一致性分析"}</h2><p>按文档层级汇总已保存结论，从章节下钻至语块、检查点与原文证据。</p></div><div>
      <Button icon={<ArrowLeft size={15} />} onClick={() => navigate(`/projects/${part(project)}/analysis`)}>任务列表</Button><Button icon={<RefreshCw size={15} />} onClick={() => setRevision(v => v + 1)}>刷新进度</Button>
      {batch && batch.status !== "running" && (batch.status !== "completed" || finalized !== batch.reviews.length) && <Button type="primary" loading={busy} icon={<Play size={15} />} onClick={() => void resume()}>继续执行 / 恢复</Button>}
    </div></div><ErrorNotice error={info.error || result.error || files.error || tree.error || error} />
    {result.loading ? <Busy /> : batch && <>
      <section className="result-card analysis-dashboard-metrics"><div className="analysis-valid-progress"><span>有效分析完成度</span><strong>{percent}%</strong><Progress percent={percent} showInfo={false} /><small>已审核整体评价 {finalized} / {batch.reviews.length}</small></div>
        <div className="analysis-stat"><span className="analysis-stat-icon"><FileText /></span><div><span>审核语块</span><strong>{batch.reviews.length}</strong></div></div>
        {categories.map(c => <div className={`analysis-stat ${c.key}`} key={c.key}><span className="analysis-stat-icon" style={{color: c.color}}>{c.key === "implemented" ? <CheckCircle2 /> : c.key === "not_analyzed" ? <Search /> : <TriangleAlert />}</span><div><span>{c.name}</span><strong>{counts[c.key]}</strong></div></div>)}
      </section>
      <div className="analysis-batch-runline"><Status value={batch.status} /><span>已保存执行记录 {batch.finished_count} / {batch.reviews.length}（包含失败，不是实现率）</span><Collapse ghost size="small" items={[{key: "scope", label: "工件范围与运行说明", children: <div>
        <p>源工件：{batch.scope.source_artifact_ids.map(id => files.data?.find(f => f.id === id)?.filename || "文件已移除").join("、")}</p><p>目标工件：{batch.scope.target_artifact_ids.map(id => files.data?.find(f => f.id === id)?.filename || "文件已移除").join("、")}</p>
        <p>基于已有追溯记录，未重新运行追溯或 embedding。后台运行不依赖页面保持打开。</p></div>}]} /></div>
      {tree.loading ? <Busy /> : !model ? <NoData title="无法读取文档层级" detail="请查看读取错误，未以扁平列表伪造层级。" /> : <div className="analysis-hierarchy-layout">
        <aside className="result-card analysis-hierarchy-sidebar"><div className="result-card-heading"><h2>需求层级 / 设计层级</h2></div><Tabs activeKey={side} onChange={v => {setSide(v as "source" | "target"); selectNode("");}} items={[{key: "source", label: "需求层级"}, {key: "target", label: "设计层级"}]} />
          <Input aria-label="搜索文档层级" placeholder="搜索章节或原文" prefix={<Search size={15} />} allowClear value={query} onChange={e => setQuery(e.target.value)} /><div className="analysis-tree-options"><Checkbox checked={onlyProblems} onChange={e => setOnlyProblems(e.target.checked)}>仅看异常</Checkbox><Checkbox checked={showLeaves} onChange={e => setShowLeaves(e.target.checked)}>显示语块</Checkbox></div>
          <Tree blockNode showIcon showLine expandedKeys={query.trim() ? [...model.children.keys()] : expandedBySide[side] || (model.children.get("") || []).map(n => n.node_id)} onExpand={keys => setExpandedBySide(old => ({...old, [side]: keys.map(String)}))} selectedKeys={[selected]} onSelect={keys => keys.length && selectNode(String(keys[0]))} treeData={makeTree(model.children.get("") || [])} />
          <p className="analysis-tree-note">{side === "source" ? "分子是已审核总评价数，分母是本次范围内的语块数。" : "仅正式链接涉及的设计层级；数值为关联需求的评价，不代表设计自身独立评价。"}</p>
        </aside>
        <main className="result-card analysis-hierarchy-main"><div className="result-card-heading"><h2>当前节点汇总</h2><Tag color="blue">{side === "source" ? "需求节点" : "关联设计节点"}</Tag></div>
          <div className="analysis-node-banner"><FileText size={24} /><div><h3>{title(current)}</h3><p>{current ? pathOf(current, graph!.nodes).join(" › ") || "文档根级" : "请选择节点"}</p></div><div><span>关联需求 {scoped.length} 个</span><span>关联设计 {new Set(links.map(l => l.target_node_id)).size} 个</span></div></div>
          <div className="analysis-summary-grid"><section><h3>下属语块结论分布 <small>{scoped.filter(r => r.assessment?.finalized).length} / {scoped.length} 已审核</small></h3><div className="analysis-distribution-bar">{categories.filter(c => localCounts[c.key] > 0).map(c => <span key={c.key} style={{background: c.color, flex: localCounts[c.key]}} title={`${c.name} ${localCounts[c.key]}`} />)}</div><div className="analysis-distribution-legend">{categories.map(c => <span key={c.key}><i style={{background: c.color}} />{c.name}<strong>{localCounts[c.key]}</strong></span>)}</div></section>
            <section><h3>关联设计与调查范围</h3><p><GitBranch size={14} /> 正式设计链接 <strong>{links.length}</strong></p><p>有效总评价 <strong>{scoped.filter(r => r.assessment?.finalized).length}</strong></p><p>执行异常 <strong>{localCounts.analysis_error}</strong></p></section></div>
          <p className="analysis-rollup-note">章节统计只汇总下属已保存事实，不是模型对整章的独立裁决。</p>
          <section className="analysis-child-list"><h3>{children.length ? "子节点列表" : "当前语块分析"}</h3>{children.length ? <Table<Canonical> rowKey="node_id" size="small" pagination={{pageSize: 8, showSizeChanger: false}} dataSource={children} onRow={n => ({onClick: () => selectNode(n.node_id), className: "analysis-clickable-row"})} columns={[
            {title: "章节 / 语块", render: (_, n) => <span className="analysis-child-title" title={title(n)}><FileText size={14} />{title(n)}</span>}, {title: "已审核 / 总数", width: 105, render: (_, n) => `${model.reviews(n.node_id).filter(r => r.assessment?.finalized).length} / ${model.reviews(n.node_id).length}`}, {title: "业务异常", width: 85, render: (_, n) => model.reviews(n.node_id).filter(r => ["issues", "uncovered"].includes(r.assessment?.status || "")).length}, {title: "操作", width: 75, render: () => <span className="analysis-drill">下钻 →</span>},
          ]} /> : focused && <AssessmentPanel assessment={focused.assessment} title="语块总体评价" onReadNode={setReadNode} />}</section>
          <section className="analysis-problem-list"><h3>问题聚合</h3><Tabs activeKey={issueTab} onChange={setIssueTab} items={[{key: "all", label: `全部 ${issues.length}`}, {key: "uncovered", label: `无覆盖 ${localCounts.uncovered}`}, {key: "issues", label: `存在异常 ${localCounts.issues}`}, {key: "analysis_error", label: `分析异常 ${localCounts.analysis_error}`}]} />
            <Table<BatchReview> rowKey="review_id" size="small" dataSource={issueRows} pagination={{pageSize: 6, showSizeChanger: false}} onRow={r => ({onClick: () => {setLeafId(r.review_id); setReadNode("");}, className: r.review_id === focused?.review_id ? "selected-row" : "analysis-clickable-row"})} columns={[{title: "需求语块", width: 145, render: (_, r) => <span className="table-preview">{r.requirement_preview}</span>}, {title: "结论", width: 96, render: (_, r) => <AssessmentStatusTag assessment={r.assessment} />}, {title: "评价说明", render: (_, r) => <div className="analysis-problem-description">{r.assessment.evaluation_text}</div>}]} /><p className="result-footnote">分析异常不是需求缺陷。未分析与异常中断不触发修改建议。</p>
          </section>
        </main>
        <aside className="result-card analysis-hierarchy-detail"><div className="result-card-heading"><h2>语块详情与证据</h2></div>{focused ? <>
          <div className="analysis-detail-scroll" key={focused.review_id}><ErrorNotice error={workspace.error} />
          {workspace.loading ? <Busy /> : workspace.data && <>
            <div className="analysis-detail-section"><h4>分析结论</h4><AssessmentStatusTag assessment={workspace.data.assessment} /><p>{workspace.data.assessment.evaluation_text || "尚未保存分析结论。"}</p></div>
            <div className="analysis-detail-section"><h4>检查点完成情况</h4>{workspace.data.checks.length ? workspace.data.checks.map(c => <div className="analysis-point" key={c.check_id}><Status value={c.status} /><p>{c.statement}</p>{c.note && <small>{c.note}</small>}</div>) : <p>尚未建立检查点，不能视为已实现。</p>}</div>
          </>}</div>
          <div className="analysis-detail-entries">
          <Button className="analysis-full-detail" block onClick={() => navigate(`/projects/${part(project)}/analysis/${part(batch.tlr_run_id)}/${part(focused.requirement_node_id)}?review=${part(focused.review_id)}`)}>查看完整评审{focused.assessment?.suggestion_required ? "与修改建议" : "记录"} →</Button>
          <Button className="analysis-full-detail" block onClick={() => navigate(`/projects/${part(project)}/analysis/${part(batch.tlr_run_id)}/${part(focused.requirement_node_id)}?review=${part(focused.review_id)}&view=workflow`)}>查看 LLM 工作过程 →</Button>
          </div>
        </> : <NoData title="没有关联审核语块" detail="请在左侧选择本次范围内的章节或语块。" />}</aside>
      </div>}
    </>}
    <Drawer title="设计原文与位置" open={!!readNode} onClose={() => setReadNode("")} size={560}>{readNode && <NodeReader access={access} node={readNode} project={project} />}</Drawer>
  </ResultShell>;
}
