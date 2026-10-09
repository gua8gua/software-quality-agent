import { useMemo, useState } from "react";
import { Button, Collapse, Table } from "antd";
import { Plus, RefreshCw } from "lucide-react";
import { navigate } from "../../navigation";
import { api as library, part } from "../api";
import { resultsApi, type AnalysisBatch, type Review, type Run } from "./api";
import { ErrorNotice, ResultShell, Status, useRead } from "./shared";
import "./results.css";

export default function TaskListPage({tenant, project, mode}: {tenant: string; project: string; mode: "trace" | "analysis"}) {
  const access = useMemo(() => resultsApi(tenant, project), [tenant, project]);
  const [revision, setRevision] = useState(0);
  const info = useRead(() => library.project(tenant, project), [tenant, project]);
  const files = useRead(() => library.artifacts(tenant, project), [tenant, project]);
  const runs = useRead(signal => access.runs(signal), [access, revision]);
  const batches = useRead(signal => mode === "analysis" ? access.batches(signal) : Promise.resolve([]), [access, mode, revision]);
  const reviews = useRead(signal => mode === "analysis" ? access.reviews(undefined, undefined, signal) : Promise.resolve([]), [access, mode, revision]);
  const root = `/projects/${part(project)}/${mode}`;
  const names = (ids: unknown) => <div className="task-list-files">{Array.isArray(ids) && ids.map(id => <span key={String(id)} title={files.data?.find(f => f.id === id)?.filename}>{files.data?.find(f => f.id === id)?.filename || "文件已移除"}</span>)}</div>;
  const openRun = (run: Run) => navigate(`${root}/${part(run.run_id)}`);
  const openBatch = (batch: AnalysisBatch) => navigate(`${root}/batch/${part(batch.batch_id)}`);
  const legacy = (reviews.data || []).filter(review => !review.batch_id);
  return <ResultShell project={project} name={info.data?.name || ""} active={mode}>
    <div className="task-list-header"><div><h2>{mode === "trace" ? "追溯任务" : "一致性分析"}</h2><p>{mode === "trace" ? "查看已有任务与追溯结果，或选择工件建立新的追溯。" : "按工件创建分析任务，查看逐语块进度、审核事实和修改意见。"}</p></div><div><Button icon={<RefreshCw size={15} />} onClick={() => setRevision(v => v + 1)}>刷新</Button><Button type="primary" icon={<Plus size={16} />} onClick={() => navigate(`${root}/start`)}>{mode === "trace" ? "新建追溯" : "新建一致性分析"}</Button></div></div>
    <ErrorNotice error={info.error || files.error || runs.error || batches.error || reviews.error} />
    <section className="result-card task-list-table">{mode === "trace" ?
      <Table<Run> rowKey="run_id" dataSource={runs.data || []} loading={runs.loading} scroll={{x: 850}} pagination={{pageSize: 10}} columns={[
        {title: "任务名称", render: (_, run) => <button className="task-list-name" onClick={() => openRun(run)}>{String(run.config?.task_name || "需求—设计追溯")}</button>},
        {title: "源工件", render: (_, run) => names(run.config?.source_artifact_ids)}, {title: "目标工件", render: (_, run) => names(run.config?.target_artifact_ids)},
        {title: "状态", width: 110, render: (_, run) => <Status value={run.status} />}, {title: "创建时间", width: 170, render: (_, run) => new Date(run.created_at).toLocaleString("zh-CN")},
        {title: "操作", width: 100, render: (_, run) => <Button type="link" onClick={() => openRun(run)}>查看结果</Button>},
      ]} /> :
      <Table<AnalysisBatch> rowKey="batch_id" dataSource={batches.data || []} loading={batches.loading} scroll={{x: 850}} pagination={{pageSize: 10}} columns={[
        {title: "任务名称", render: (_, batch) => <button className="task-list-name" onClick={() => openBatch(batch)}>{batch.name}</button>},
        {title: "源工件", render: (_, batch) => names(batch.scope.source_artifact_ids)}, {title: "目标工件", render: (_, batch) => names(batch.scope.target_artifact_ids)},
        {title: "进度", width: 100, render: (_, batch) => `${batch.finished_count} / ${batch.scope.source_node_count}`},
        {title: "状态", width: 110, render: (_, batch) => <Status value={batch.status} />}, {title: "创建时间", width: 170, render: (_, batch) => new Date(batch.created_at).toLocaleString("zh-CN")},
        {title: "操作", width: 100, render: (_, batch) => <Button type="link" onClick={() => openBatch(batch)}>查看分析</Button>},
      ]} />}</section>
    {mode === "analysis" && legacy.length > 0 && <Collapse className="legacy-review-list" items={[{key: "legacy", label: `已有单项审核记录（${legacy.length}）`, children: <><p className="result-footnote">以下为原有单语块记录，不代表对完整工件的分析。</p><Table<Review> size="small" rowKey="review_id" dataSource={legacy} pagination={{pageSize: 5}} columns={[{title: "需求内容", dataIndex: "requirement_preview", ellipsis: true}, {title: "状态", render: (_, review) => <Status value={review.status} />}, {title: "操作", render: (_, review) => <Button type="link" onClick={() => navigate(`${root}/${part(review.tlr_run_id)}/${part(review.requirement_node_id)}?review=${part(review.review_id)}`)}>查看记录</Button>}]} /></> }]} />}
  </ResultShell>;
}
