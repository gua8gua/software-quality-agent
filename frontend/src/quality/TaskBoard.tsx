import { useEffect, useMemo, useState } from "react";
import { Alert, Button, Empty, Input, Modal, Progress, Select, Spin, Table, Tabs, Tag } from "antd";
import { Activity, CheckCircle2, Clock3, Cpu, ListTodo, Pause, Play, Plus, RefreshCw, Search, ShieldAlert } from "lucide-react";
import { navigate } from "../navigation";
import { part } from "./api";
import "./task-board.css";

type Task = {task_id: string; business_id: string; project_id: string; project_name: string; kind: "trace" | "analysis"; name: string; status: string; business_status: string; stage: string; source_files: string[]; target_files: string[]; dependency_id: string | null; created_at: string; done: number; total: number | null; counts: Record<string, number>; error: string | null; job_id: number | null; queue_status: string | null; priority: number; attempts: number; resource: string; href: string; scope_limited: boolean};
type Board = {tasks: Task[]; projects: {id: string; name: string}[]; queue_available: boolean; resources: {worker_capacity: number; model_task_capacity: number; running: number; queued: number; model: string; context_window: number; idle_deadline_seconds: number; unit_deadline_seconds: number}};
type Review = {review_id: string; requirement_node_id: string; requirement_preview: string; tlr_run_id: string; execution: {status: string; error_code?: string; error_message?: string} | null; assessment: {finalized: boolean; status: string} | null};
type Detail = {task: Task; business: {reviews?: Review[]; error?: string; metrics?: unknown}; events?: {job_id: number; type: string; at: string}[]};
const stateLabels: Record<string, string> = {pending: "未启动", queued: "队列中", waiting_resource: "等待资源", running: "运行中", interrupting: "正在中断", interrupted: "已中断", blocked: "执行阻断", partial: "部分完成", completed: "已完成", unmanaged: "状态待核对", idle: "无需建议"};
const colors: Record<string, string> = {queued: "blue", waiting_resource: "orange", running: "processing", interrupting: "orange", blocked: "red", partial: "gold", completed: "green"};
const stageLabels: Record<string, string> = {semantic_annotation: "文档标注", retrieval_projection: "检索准备", dense_index: "向量检索准备", hybrid_retrieval: "混合检索", fine_validation: "追溯验证", completed: "已完成"};
const badge = (value: string) => <Tag color={colors[value]}>{stateLabels[value] || value}</Tag>;
async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, options); const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : `请求失败（${response.status}）`);
  return data;
}

export default function TaskBoard({tenant, project}: {tenant: string; project?: string}) {
  const [board, setBoard] = useState<Board | null>(null), [detail, setDetail] = useState<Detail | null>(null);
  const [revision, setRevision] = useState(0), [loading, setLoading] = useState(true), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [kind, setKind] = useState("all"), [state, setState] = useState("all"), [projectFilter, setProjectFilter] = useState(project || "all");
  const [priority, setPriority] = useState("all"), [search, setSearch] = useState(""), [tab, setTab] = useState("all"), [selected, setSelected] = useState<string | null>(null);
  const [fetchedAt, setFetchedAt] = useState("");
  const [newTask, setNewTask] = useState(false), [newProject, setNewProject] = useState(project), [newKind, setNewKind] = useState("trace");
  useEffect(() => { const controller = new AbortController(); setLoading(true);
    request<Board>(`/api/tasks?tenant_id=${part(tenant)}${project ? `&project_id=${part(project)}` : ""}`, {signal: controller.signal})
      .then(value => {setBoard(value); setError(""); setFetchedAt(new Date().toLocaleTimeString("zh-CN")); setSelected(old => old && value.tasks.some(t => t.task_id === old) ? old : value.tasks[0]?.task_id || null);})
      .catch(e => {if (!controller.signal.aborted) setError(String(e));}).finally(() => {if (!controller.signal.aborted) setLoading(false);});
    return () => controller.abort();
  }, [tenant, project, revision]);
  const selectedTask = board?.tasks.find(t => t.task_id === selected);
  useEffect(() => {setDetail(null); if (!selectedTask) return; const controller = new AbortController();
    request<Detail>(`/api/tasks/${selectedTask.kind}/${part(selectedTask.business_id)}?tenant_id=${part(tenant)}&project_id=${part(selectedTask.project_id)}`, {signal: controller.signal})
      .then(setDetail).catch(e => {if (!controller.signal.aborted) setError(String(e));}); return () => controller.abort();
  }, [selectedTask?.task_id, revision, tenant]);
  const tasks = board?.tasks || [];
  const filtered = useMemo(() => tasks.filter(t => (kind === "all" || t.kind === kind) && (state === "all" || t.status === state)
    && (projectFilter === "all" || t.project_id === projectFilter) && (priority === "all" || Math.sign(t.priority).toString() === priority)
    && (!search || [t.name, t.project_name, ...t.source_files, ...t.target_files].join(" ").toLowerCase().includes(search.toLowerCase()))
    && (tab === "all" || (tab === "waiting" ? ["queued", "waiting_resource", "pending"].includes(t.status) : tab === "errors" ? ["blocked", "partial", "interrupted", "unmanaged"].includes(t.status) : t.status === tab))), [tasks, kind, state, projectFilter, priority, search, tab]);
  async function action(task: Task, command: "interrupt" | "resume" | "retry_failed") {
    setBusy(true); try {
      await request(`/api/tasks/${task.kind}/${part(task.business_id)}/action`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({tenant_id: tenant, project_id: task.project_id, action: command})});
      setRevision(v => v + 1);
    } catch (e) {setError(String(e));} finally {setBusy(false);}
  }
  function interrupt(task: Task) {Modal.confirm({title: "中断此任务？", content: "将停止当前模型工作。已保存的检查点、证据和结果保留，可在中断确认后恢复。", okText: "中断任务", cancelText: "返回", onOk: () => action(task, "interrupt")});}
  const active = (task: Task) => ["running", "queued", "waiting_resource"].includes(task.status);
  const resources = board?.resources;
  const stats = [
    {name: "队列中", values: ["queued"], icon: ListTodo, color: "blue"}, {name: "运行中", values: ["running", "interrupting"], icon: Activity, color: "green"},
    {name: "等待资源", values: ["waiting_resource"], icon: Clock3, color: "orange"}, {name: "执行阻断", values: ["blocked"], icon: ShieldAlert, color: "red"},
    {name: "已完成", values: ["completed"], icon: CheckCircle2, color: "green"}, {name: "可恢复", values: ["partial", "interrupted"], icon: RefreshCw, color: "purple"},
  ];
  return <section className="task-board">
    <nav className="queue-breadcrumb"><a href="#/projects">项目管理</a><span>/</span>{project && <><a href={`#/projects/${part(project)}`}>{board?.projects[0]?.name || "当前项目"}</a><span>/</span></>}任务队列</nav>
    <header className="queue-title"><div><h1>任务队列管理</h1><p>统一管理追溯与一致性分析的排队、资源占用、执行和恢复</p></div><Button onClick={() => navigate(project ? `/projects/${part(project)}` : "/projects")}>返回项目</Button></header>
    {error && <Alert type="error" showIcon message={error} />}
    {board && !board.queue_available && <Alert type="warning" showIcon message="持久队列未连接，任务列表只读，未启动任何模型工作" />}
    <div className="queue-stats">{stats.map(({name, values, icon: Icon, color}) => <article key={name}><span>{name}</span><div><strong>{tasks.filter(t => values.includes(t.status)).length}</strong><Icon className={color} size={26}/></div><small>当前任务状态</small></article>)}</div>
    <section className="queue-card">
      <div className="queue-filters">
        <Select aria-label="任务类型" value={kind} onChange={setKind} options={[{value: "all", label: "全部任务类型"}, {value: "trace", label: "追溯任务"}, {value: "analysis", label: "一致性分析"}]} />
        <Select aria-label="任务状态" value={state} onChange={setState} options={[{value: "all", label: "全部状态"}, ...Object.entries(stateLabels).map(([value, label]) => ({value, label}))]} />
        <Select aria-label="所属项目" value={projectFilter} onChange={setProjectFilter} options={[{value: "all", label: "全部项目"}, ...(board?.projects || []).map(p => ({value: p.id, label: p.name}))]} />
        <Select aria-label="优先级" value={priority} onChange={setPriority} options={[{value: "all", label: "全部优先级"}, {value: "1", label: "高"}, {value: "0", label: "普通"}, {value: "-1", label: "低"}]} />
        <Input aria-label="搜索任务" prefix={<Search size={14}/>} value={search} onChange={e => setSearch(e.target.value)} placeholder="搜索任务或工件" allowClear />
        <Button loading={loading} icon={<RefreshCw size={14}/>} onClick={() => setRevision(v => v + 1)}>刷新</Button><Button type="primary" icon={<Plus size={14}/>} onClick={() => setNewTask(true)}>新建任务</Button>
      </div>
      <Tabs activeKey={tab} onChange={setTab} items={[{key: "all", label: `全部任务 (${tasks.length})`}, {key: "running", label: "运行中"}, {key: "waiting", label: "排队 / 等待"}, {key: "errors", label: "中断 / 异常"}, {key: "completed", label: "已完成"}]} />
      <Table<Task> rowKey="task_id" size="small" loading={loading} dataSource={filtered} scroll={{x: 1240}} pagination={{pageSize: 6, showSizeChanger: false}} onRow={task => ({onClick: () => setSelected(task.task_id)})} rowClassName={task => task.task_id === selected ? "queue-row-selected" : ""} columns={[
        {title: "任务名称", width: 180, render: (_, t) => <div className="queue-name"><strong>{t.name}</strong><small>{t.scope_limited ? "局部恢复范围" : "完整工件范围"}</small></div>},
        {title: "类型 / 项目", width: 120, render: (_, t) => <><Tag color={t.kind === "trace" ? "blue" : "green"}>{t.kind === "trace" ? "追溯任务" : "一致性分析"}</Tag><small className="queue-project">{t.project_name}</small></>},
        {title: "源工件 → 目标工件", width: 215, render: (_, t) => <div className="queue-files" title={[...t.source_files, ...t.target_files].join("\n")}><span>{t.source_files.join("、") || "—"}</span><span>→ {t.target_files.join("、") || "—"}</span></div>},
        {title: "依赖", width: 85, render: (_, t) => t.dependency_id ? <a onClick={e => e.stopPropagation()} href={`#/projects/${part(t.project_id)}/trace/${part(t.dependency_id)}`}>已有追溯</a> : "—"},
        {title: "任务状态", width: 110, render: (_, t) => badge(t.status)},
        {title: "业务阶段", width: 95, render: (_, t) => stageLabels[t.stage] || t.stage}, {title: "优先级", width: 60, render: (_, t) => t.priority > 0 ? "高" : t.priority < 0 ? "低" : "普通"},
        {title: "资源需求", width: 115, dataIndex: "resource"},
        {title: "处理进度", width: 115, render: (_, t) => t.total ? <><Progress size="small" percent={Math.floor(100 * t.done / t.total)} showInfo={false}/><small>{t.done} / {t.total} 已处理</small></> : t.status === "completed" ? "已完成" : "按阶段记录"},
        {title: "操作", width: 115, fixed: "right", render: (_, t) => <div onClick={e => e.stopPropagation()}><Button size="small" type="link" onClick={() => navigate(t.href)}>查看</Button>{active(t) ? <Button size="small" type="link" danger disabled={busy} onClick={() => interrupt(t)}>中断</Button> : t.status !== "completed" && t.status !== "interrupting" && <Button size="small" type="link" disabled={busy || !board?.queue_available || t.status === "unmanaged"} onClick={() => void action(t, "resume")}>恢复</Button>}</div>},
      ]}/><p className="queue-footnote">截至 {fetchedAt || "—"} 的已保存状态 · 已处理包括成功和执行阻断，不等于需求已实现。刷新仅查询，不启动模型。</p>
    </section>
    <div className="queue-bottom">
      <section className="queue-card queue-detail"><h2>任务详情与子任务概览 {selectedTask && <small>{selectedTask.name}</small>}</h2>{selectedTask ? (!detail || detail.task.task_id !== selectedTask.task_id ? <div className="queue-detail-note"><Spin size="small"/> 正在读取当前任务详情…</div> : <Tabs items={[
        {key: "children", label: "子任务", children: detail?.business.reviews ? <Table<Review> size="small" rowKey="review_id" dataSource={detail.business.reviews} pagination={{pageSize: 4, showSizeChanger: false}} columns={[{title: "需求语块", ellipsis: true, dataIndex: "requirement_preview"}, {title: "执行状态", width: 105, render: (_, r) => badge(r.execution?.status || "pending")}, {title: "总体评价", width: 130, render: (_, r) => r.assessment?.finalized ? ({implemented: "已实现", issues: "存在异常", uncovered: "无覆盖"} as Record<string, string>)[r.assessment.status] || r.assessment.status : "尚未形成有效结论"}, {title: "查看", width: 65, render: (_, r) => <a href={`#/projects/${part(selectedTask.project_id)}/analysis/${part(r.tlr_run_id)}/${part(r.requirement_node_id)}?review=${part(r.review_id)}`}>详情</a>}]} /> : <div className="queue-detail-note">追溯按 annotation、检索及 candidate 检查点恢复。<Button type="link" onClick={() => navigate(selectedTask.href)}>查看追溯阶段记录</Button></div>},
        {key: "log", label: "执行记录", children: <div className="queue-log"><p>队列：{selectedTask.queue_status || "历史任务未进入当前队列"} · 执行尝试：{selectedTask.attempts}</p>{detail?.events?.map((e, i) => <p key={i}>{new Date(e.at).toLocaleString("zh-CN")} · {e.type}</p>)}{detail?.business.error && <Alert type="error" message={detail.business.error}/>} {(detail?.business.reviews || []).filter(r => r.execution?.error_code).map(r => <p key={r.review_id}><Tag color="red">{r.execution?.error_code}</Tag>{r.execution?.error_message}</p>)}</div>},
        {key: "dependency", label: "依赖与恢复", children: <div className="queue-detail-note"><p>{selectedTask.kind === "analysis" ? "基于已完成追溯，仅审核本任务所选工件支持的语块，不重新生成 embedding。" : "保留已有分析、检索、Fine Trace 检查点；恢复不会清空已保存结果。"}</p><p>中断后先等待执行器确认，再恢复原范围。运行中的任务不会被优先级抢占。</p><div><Button disabled={!active(selectedTask) || busy} icon={<Pause size={14}/>} onClick={() => interrupt(selectedTask)}>中断任务</Button><Button disabled={active(selectedTask) || selectedTask.status === "completed" || selectedTask.status === "interrupting" || busy} icon={<Play size={14}/>} onClick={() => void action(selectedTask, "resume")}>恢复原任务</Button></div></div>},
      ]}/>) : <Empty description="选择任务查看详情"/>}{selectedTask && ["partial", "blocked", "interrupted"].includes(selectedTask.status) && <div className="queue-retry"><Button disabled={busy} onClick={() => void action(selectedTask, "retry_failed")}>重试失败项</Button><small>恢复只继续中断与未处理项；此操作明确重新尝试已结束的失败项。</small></div>}</section>
      <section className="queue-card queue-resources"><h2><Cpu size={17}/>资源与调度</h2><div className="queue-resource-stats"><div><small>执行器并发上限</small><strong>{resources?.worker_capacity ?? "—"}</strong></div><div><small>模型任务槽</small><strong>{resources?.model_task_capacity ?? "—"}</strong></div><div><small>当前执行 / 排队</small><strong>{resources ? `${resources.running} / ${resources.queued}` : "—"}</strong></div></div>
        <div className="queue-resource-row"><span>模型</span><b>{resources?.model || "—"}</b></div><div className="queue-resource-row"><span>上下文准入上限</span><b>{resources?.context_window.toLocaleString() || "—"} tokens</b></div>
        <div className="queue-resource-row"><span>业务无进展期限</span><b>{resources ? `${resources.idle_deadline_seconds / 60} 分钟` : "—"}</b></div><div className="queue-resource-row"><span>单语块执行期限</span><b>{resources ? `${resources.unit_deadline_seconds / 60} 分钟` : "—"}</b></div>
        <p>两类任务共用持久资源锁，按优先级与入队时间调度。每次模型调用先核对真实 tokenizer 与上下文预算。</p><small>这里显示调度配额，不虚构 GPU 显存或模型实时利用率。</small>
      </section>
    </div>
    <Modal title="新建任务" open={newTask} onCancel={() => setNewTask(false)} cancelText="取消" okText="选择工件" okButtonProps={{disabled: !newProject}} onOk={() => {setNewTask(false); navigate(`/projects/${part(newProject!)}/${newKind}/start`);}}><div className="queue-create"><label>所属项目<Select aria-label="新任务项目" value={newProject} onChange={setNewProject} options={board?.projects.map(p => ({value: p.id, label: p.name}))}/></label><label>任务类型<Select value={newKind} onChange={setNewKind} options={[{value: "trace", label: "追溯任务"}, {value: "analysis", label: "一致性分析"}]}/></label></div></Modal>
  </section>;
}
