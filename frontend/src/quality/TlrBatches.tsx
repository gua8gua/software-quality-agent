import { useEffect, useState } from "react";
import { all, date, errorText, runDisplayStatus, statusLabel, type Dataset, type Run } from "./api";
import { Alert, Empty, Loading, Pager } from "./common";
import { LayerRunMatrix } from "./LayerAnalysis";

export const batchKey = (run: Run) => run.config.plan_id ? `plan:${run.config.plan_id}` : `run:${run.id}`;
export const batchPath = (project: string, key: string) => `#/projects/${encodeURIComponent(project)}/batches/${encodeURIComponent(key)}`;
const names: Record<string, string> = { context: "背景 / 风险", requirements: "需求", architecture: "架构 / 接口", design: "详细设计", implementation: "代码实现", verification: "测试", assurance: "评审 / 其它", operation: "发布 / 运维" };
const pairName = (run: Run) => run.config.layer_pair?.length ? run.config.layer_pair.map(k => names[k] || k).join(" → ") : "手工选择范围";
export function groupBatches(runs: Run[]) {
  const groups = new Map<string, Run[]>();
  for (const run of runs) { const key = batchKey(run); groups.set(key, [...(groups.get(key) || []), run]); }
  return [...groups].map(([key, rows]) => {
    const ordered = [...rows].sort((a, b) => (a.config.batch_index ?? 0) - (b.config.batch_index ?? 0) || a.created_at.localeCompare(b.created_at));
    const statuses = rows.map(runDisplayStatus);
    const status = statuses.includes("running") ? "running" : statuses.every(s => s === "completed") ? "completed" : statuses.every(s => s === "pending") ? "pending" : statuses.every(s => s === "failed") ? "failed" : "partial";
    return { key, rows: ordered, label: ordered[0].config.batch_label || (ordered[0].config.plan_id ? `批次 ${ordered[0].config.plan_id.slice(0, 8)}` : `单任务批次 ${ordered[0].id.slice(0, 8)}`), status, created: rows.map(r => r.created_at).sort().at(-1)! };
  }).sort((a, b) => b.created.localeCompare(a.created));
}

export function TlrBatchList({ runs, datasets, project }: { runs: Run[]; datasets: Dataset[]; project: string }) {
  const [page, setPage] = useState(0);
  const batches = groupBatches(runs);
  if (!batches.length) return <Empty title="还没有 TLR 批次"><p>创建层间比较后，在此查看各批次及其子任务。</p></Empty>;
  return <><div className="qm-inset"><h3>TLR 批次记录 · {batches.length} 个批次</h3><p className="muted-text">每个批次包含一个或多个层间子任务。历史单次运行归为单任务批次。</p></div>
    <div className="table-wrap"><table className="data-table"><thead><tr><th>批次 / 创建时间</th><th>资料快照</th><th>子任务</th><th>状态分布</th><th>已判定 / 候选</th><th /></tr></thead><tbody>{batches.slice(page * 20, (page + 1) * 20).map(batch => <tr key={batch.key}>
      <td><a href={batchPath(project, batch.key)}>{batch.label}</a><small>{date(batch.created)}</small></td>
      <td>{[...new Set(batch.rows.map(r => datasets.find(d => d.id === r.dataset_id)?.version || r.dataset_id))].join("、")}</td>
      <td>{batch.rows.length} 个<small>{[...new Set(batch.rows.map(pairName))].join("；")}</small></td>
      <td><span className={`mini-pill ${batch.status}`}>{statusLabel[batch.status]}</span><small>{["completed", "partial", "failed", "running", "pending"].map(s => { const n = batch.rows.filter(r => runDisplayStatus(r) === s).length; return n ? `${statusLabel[s]} ${n}` : ""; }).filter(Boolean).join(" · ")}</small></td>
      <td>{batch.rows.reduce((n, r) => n + (r.counts.classified || 0), 0)} / {batch.rows.reduce((n, r) => n + (r.counts.candidates || 0), 0)}</td>
      <td><a href={batchPath(project, batch.key)}>查看子任务</a></td>
    </tr>)}</tbody></table></div><Pager page={page} size={20} total={batches.length} set={setPage} /></>;
}

export function TlrBatchPage({ tenant, project, id, refresh, begin }: { tenant: string; project: string; id: string; refresh: number; begin: (runs: Run | Run[]) => void }) {
  const [runs, setRuns] = useState<Run[] | null>(null), [error, setError] = useState(""), [tick, setTick] = useState(0);
  useEffect(() => { let active = true; all<Run>(`/projects/${encodeURIComponent(project)}/runs`, tenant).then(rows => { if (active) { setRuns(rows.filter(r => batchKey(r) === id)); setError(""); } }).catch(e => { if (active) setError(errorText(e)); }); return () => { active = false; }; }, [tenant, project, id, refresh, tick]);
  useEffect(() => { if (!runs?.some(r => ["pending", "running"].includes(r.status))) return; const timer = setTimeout(() => setTick(n => n + 1), 3000); return () => clearTimeout(timer); }, [runs]);
  const batch = runs && groupBatches(runs)[0];
  return <><a className="qm-back" href={`#/projects/${encodeURIComponent(project)}/tlr`}>返回 TLR 批次列表</a>{error && <Alert>{error}</Alert>}{!runs ? !error && <Loading /> : !batch ? <Empty title="批次不存在或不属于当前项目" /> : <>
    <div className="qm-heading"><div><h1>{batch.label}</h1><p>{date(batch.created)} · {runs.length} 个子任务</p></div><button onClick={() => setTick(n => n + 1)}>刷新批次</button></div>
    <section className="surface">{runs[0].config.plan_id && <LayerRunMatrix runs={runs} project={project} datasetId={runs[0].dataset_id} fixedPlanId={runs[0].config.plan_id} resume={begin} />}
    <div className="qm-inset"><h2>批次子任务</h2></div><div className="table-wrap"><table className="data-table"><thead><tr><th>子任务</th><th>上层 → 下层</th><th>工件范围</th><th>状态</th><th>已判定 / 候选</th><th>确认关联</th><th /></tr></thead><tbody>{batch.rows.map((r, i) => <tr key={r.id}>
      <td>{i + 1}<small>{r.id.slice(0, 8)}</small></td><td>{pairName(r)}</td><td>{r.config.source_ids.length} → {r.config.target_ids.length}</td><td><span className={`mini-pill ${runDisplayStatus(r)}`}>{statusLabel[runDisplayStatus(r)]}</span></td><td>{r.counts.classified || 0} / {r.counts.candidates || 0}</td><td>{r.counts.links || 0}</td><td><a href={`#/projects/${encodeURIComponent(project)}/runs/${r.id}`}>查看子任务结果</a></td>
    </tr>)}</tbody></table></div></section>
  </>}</>;
}
