import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Alert, Button, Checkbox, Input, Pagination, Select, Tabs, Tag, message } from "antd";
import { Background, BackgroundVariant, Handle, MarkerType, Position, ReactFlow, ReactFlowProvider,
  useReactFlow, useStore, type Edge, type Node, type NodeProps } from "@xyflow/react";
import ELK from "elkjs/lib/elk.bundled.js";
import { Bot, CheckCircle2, ChevronDown, ChevronUp, Clock3, Copy, FileText, Globe2, Info, Lightbulb,
  ListChecks, Maximize, RefreshCw, Search, ShieldCheck, Wrench, ZoomIn, ZoomOut } from "lucide-react";
import { part } from "../api";
import { Busy, ErrorNotice, NoData } from "./shared";
import { roleInfo, toolLabel, type WorkflowNode, type WorkflowStep, type WorkflowView } from "./workflowRecords";
import "@xyflow/react/dist/style.css";
import "./workflow.css";

const statusNames: Record<string, string> = {completed: "已完成", running: "运行中", pending: "待执行",
  blocked: "已阻断", failed: "失败", unresolved: "未解决", not_recorded: "未记录", partial: "部分完成"};
function ExecutionTag({value}: {value: string}) {
  const color = value === "completed" ? "green" : ["blocked", "failed"].includes(value) ? "red" : value === "running" ? "blue" : "default";
  return <Tag className="workflow-status" color={color}>{value === "completed" && <CheckCircle2 size={12} />}{statusNames[value] || value}</Tag>;
}
const icons = {manager: Bot, analysis: FileText, evidence: Search, web: Globe2, suggestion: Lightbulb, validator: ShieldCheck, other: Bot};
const date = (value: string) => value && !Number.isNaN(Date.parse(value)) ? new Date(value).toLocaleString("zh-CN", {hour12: false}) : "时间未记录";
const kindNames = {model: "模型输出", tool: "工具调用", note: "工作说明", error: "错误记录"};

type AgentNode = Node<{item: WorkflowNode}, "agent">;
function AgentCard({data, selected}: NodeProps<AgentNode>) {
  const item = data.item, Icon = icons[item.role as keyof typeof icons] || Bot;
  return <div className={`workflow-agent-card ${selected ? "is-selected" : ""}`}>
    <Handle type="target" position={Position.Left} />
    <span className="workflow-agent-icon"><Icon size={20} /></span>
    <div className="workflow-agent-main"><div><strong>{item.title}</strong><ExecutionTag value={item.status} /></div>
      <p>{item.purpose.split(" · ")[1]}</p><span className={`workflow-phase ${item.phase.includes("工具") ? "tool" : "model"}`} title={item.phase}>{item.phase}</span>
    </div><Handle type="source" position={Position.Right} />
  </div>;
}
const nodeTypes = {agent: AgentCard};
const elk = new ELK();
function WorkflowCanvas({view, selected, select}: {view: WorkflowView; selected: string; select: (id: string) => void}) {
  const [nodes, setNodes] = useState<AgentNode[]>([]), [layoutError, setLayoutError] = useState("");
  const {zoomIn, zoomOut, fitView} = useReactFlow();
  const canvasWidth = useStore(s => s.width), canvasHeight = useStore(s => s.height);
  useEffect(() => {
    let active = true; setLayoutError("");
    elk.layout({id: "root", layoutOptions: {"elk.algorithm": "layered", "elk.direction": "RIGHT",
      "elk.spacing.nodeNode": "35", "elk.layered.spacing.nodeNodeBetweenLayers": "48", "elk.padding": "[top=24,left=24,bottom=24,right=24]"},
      children: view.nodes.map(n => ({id: n.id, width: 232, height: 120})),
      edges: view.edges.map(e => ({id: e.id, sources: [e.source], targets: [e.target]}))}).then(graph => {
        if (!active) return;
        setNodes(view.nodes.map(n => ({id: n.id, type: "agent", data: {item: n}, draggable: false,
          position: {x: graph.children?.find(c => c.id === n.id)?.x || 0, y: graph.children?.find(c => c.id === n.id)?.y || 0}})));
      }).catch(e => {if (active) setLayoutError(String(e));});
    return () => {active = false;};
  }, [view.nodes, view.edges]);
  useEffect(() => {if (nodes.length && canvasWidth && canvasHeight) {const frame = requestAnimationFrame(() => void fitView({padding: .08, minZoom: .1, maxZoom: 1})); return () => cancelAnimationFrame(frame);}}, [nodes, canvasWidth, canvasHeight, fitView]);
  const edges: Edge[] = view.edges.map(e => ({...e, type: "smoothstep", markerEnd: {type: MarkerType.ArrowClosed, color: "#3887ef", width: 16, height: 16},
    style: {stroke: "#3887ef", strokeWidth: 1.6}}));
  return <section className="result-card workflow-graph-card"><div className="workflow-section-heading"><h2>LLM 工作流程</h2><span><Info size={14} /> 点击节点查看详情</span>
    <div className="workflow-canvas-controls"><Button size="small" icon={<ZoomIn size={14} />} onClick={() => void zoomIn()}>放大</Button><Button size="small" icon={<ZoomOut size={14} />} onClick={() => void zoomOut()}>缩小</Button><Button size="small" icon={<Maximize size={14} />} onClick={() => void fitView({padding: .08, minZoom: .1, maxZoom: 1})}>适应画布</Button></div></div>
    <ErrorNotice error={layoutError} /><div className="workflow-canvas">
      <ReactFlow nodes={nodes.map(n => ({...n, selected: n.id === selected}))} edges={edges} nodeTypes={nodeTypes}
        onNodeClick={(_, n) => select(n.id)} nodesConnectable={false} nodesDraggable={false} elementsSelectable
        minZoom={.1} maxZoom={1.8} fitView panOnScroll preventScrolling={false} deleteKeyCode={null}>
        <Background variant={BackgroundVariant.Dots} gap={18} size={1} color="#dfe8f6" />
      </ReactFlow>
    </div><div className="workflow-graph-note">按实际调用顺序展示；同一 Agent 再次接管会成为新节点。当前记录未显示并行分支。</div>
  </section>;
}

function JsonPane({title, value}: {title: string; value: unknown}) {
  const content = useMemo(() => typeof value === "string" ? value : JSON.stringify(value, null, 2) || "未记录", [value]);
  const [chunk, setChunk] = useState(1); const limit = 12000, count = Math.ceil(content.length / limit);
  useEffect(() => setChunk(1), [content]);
  return <section className="workflow-json-pane"><div><strong>{title}</strong><Button size="small" type="text" aria-label={`复制${title}`} icon={<Copy size={13} />} onClick={() => {
    if (!navigator.clipboard) {void message.info("当前浏览器不支持直接复制，请选择正文复制。"); return;}
    void navigator.clipboard.writeText(content).then(() => message.success("已复制完整记录")).catch(() => message.warning("复制失败，请选择正文复制。"));
  }} /></div><pre>{content.slice((chunk - 1) * limit, chunk * limit)}</pre>{count > 1 && <div className="workflow-json-pager"><span>完整记录分 {count} 页显示</span><Pagination simple current={chunk} total={count} pageSize={1} onChange={setChunk} /></div>}</section>;
}

type StepSummary = WorkflowView["steps"][number];
function RecordList({steps, detail, nodeMode = false}: {steps: StepSummary[]; detail: (id: string) => Promise<WorkflowStep | null>; nodeMode?: boolean}) {
  const [open, setOpen] = useState<string[]>([]), [details, setDetails] = useState<Record<string, WorkflowStep>>({});
  const [filter, setFilter] = useState<string[]>([]), [page, setPage] = useState(1), [query, setQuery] = useState(""), [error, setError] = useState("");
  const rows = steps.filter(s => (!filter.length || filter.includes(s.kind)) &&
    `${s.title} ${s.summary} ${s.agent} ${s.tool || ""}`.toLowerCase().includes(query.toLowerCase()));
  const pageRows = rows.slice((page - 1) * 20, page * 20);
  useEffect(() => {setOpen([]); setDetails({}); setPage(1);}, [steps]);
  useEffect(() => {setPage(1);}, [query, filter]);
  const expand = async (ids: string[]) => {
    setOpen(ids);
    for (const id of ids) if (!details[id]) {
      try {const result = await detail(id); if (result) setDetails(old => ({...old, [id]: result}));}
      catch (e) {setError(String(e));}
    }
  };
  return <div className="workflow-record-panel"><div className="workflow-record-toolbar"><div><h3>{nodeMode ? "执行轨迹" : "全流程执行面板"}</h3><span>{nodeMode ? "当前节点" : "此执行尝试"}共 {steps.length} 条公开记录</span></div>
    <div><Button size="small" icon={<ChevronDown size={14} />} onClick={() => void expand(pageRows.map(s => s.id))}>展开本页</Button><Button size="small" icon={<ChevronUp size={14} />} onClick={() => setOpen([])}>收起全部</Button></div></div>
    {!nodeMode && <div className="workflow-record-filters"><Input prefix={<Search size={14} />} aria-label="搜索工作记录" allowClear placeholder="搜索 Agent、工具或记录" value={query} onChange={e => setQuery(e.target.value)} /><Checkbox.Group value={filter} onChange={v => setFilter(v as string[])} options={[{label: "模型输出", value: "model"}, {label: "工具调用", value: "tool"}, {label: "错误记录", value: "error"}, {label: "工作说明", value: "note"}]} /><span>可多选记录类型</span></div>}
    <ErrorNotice error={error} />
    <div className="workflow-record-list">{pageRows.map(step => <article key={step.id} className={`workflow-record ${open.includes(step.id) ? "expanded" : ""}`}>
      <button className="workflow-record-header" aria-expanded={open.includes(step.id)} aria-label={`查看第 ${step.ordinal} 步 ${step.title}`} onClick={() => void expand(open.includes(step.id) ? open.filter(id => id !== step.id) : [...open, step.id])}>
        <span className={`workflow-step-number ${step.kind}`}>{step.ordinal}</span><time title={step.timeBasis === "model_request" ? "关联模型请求的开始时间；不是工具的精确执行时间" : "实际保存的事件时间"}>{date(step.at)}</time><span className="workflow-record-agent"><Bot size={13} />{roleInfo(step.agent).title}</span>
        <span className={`workflow-kind ${step.kind}`}>{kindNames[step.kind]}</span><span className="workflow-record-summary" title={step.summary}>{step.summary}</span>
        <span className="workflow-duration"><Clock3 size={13} />{step.durationMs === null ? "未记录" : `${(step.durationMs / 1000).toFixed(1)}s`}</span><ExecutionTag value={step.status} />{open.includes(step.id) ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
      </button>{open.includes(step.id) && <div className="workflow-record-body">{details[step.id] ? <>
        {step.tool && <p className="workflow-technical-name"><Wrench size={13} />{step.tool}{step.callId && <code>调用 ID：{step.callId}</code>}</p>}
        {step.kind === "tool" && step.timeBasis === "model_request" && <p className="workflow-record-time-note">本步骤没有独立工具时间；列表采用关联模型请求的开始时间。耗时未记录。</p>}
        <div className="workflow-json-columns"><JsonPane title={step.kind === "tool" ? "工具参数" : "已保存输入信息"} value={details[step.id].input} /><JsonPane title={step.kind === "tool" ? "工具结果" : "公开输出 / 记录"} value={details[step.id].output} /></div>
      </> : <Busy />}</div>}
    </article>)}</div>{!rows.length && <NoData title="没有符合条件的记录" detail="调整筛选条件可查看其他步骤。" />}
    {rows.length > 20 && <div className="workflow-record-pagination"><span>逐页查看全部记录，展开操作仅作用于当前页</span><Pagination current={page} total={rows.length} pageSize={20} showSizeChanger={false} onChange={setPage} /></div>}
  </div>;
}

export default function ReviewWorkflow({tenant, project, review, sentence, sourceText, revision}: {
  tenant: string; project: string; review: string; sentence: string; sourceText: string; revision: number;
}) {
  const worker = useRef<Worker | null>(null), nextId = useRef(0);
  const loadEpoch = useRef(0);
  const pending = useRef(new Map<number, {resolve: (value: any) => void; reject: (e: Error) => void}>());
  const [view, setView] = useState<WorkflowView | null>(null), [selected, setSelected] = useState(""), [tab, setTab] = useState("node");
  const [loading, setLoading] = useState(true), [error, setError] = useState("");
  const send = useCallback((request: Record<string, unknown>) => new Promise<any>((resolve, reject) => {
    const id = ++nextId.current;
    if (!worker.current) {reject(new Error("工作记录读取器尚未准备")); return;}
    pending.current.set(id, {resolve, reject}); worker.current.postMessage({...request, id});
  }), []);
  useEffect(() => {
    const w = new Worker(new URL("./workflow.worker.ts", import.meta.url), {type: "module"}); worker.current = w;
    w.onmessage = e => {const item = pending.current.get(e.data.id); if (!item) return; pending.current.delete(e.data.id); e.data.error ? item.reject(new Error(e.data.error)) : item.resolve(e.data.result);};
    w.onerror = () => {for (const item of pending.current.values()) item.reject(new Error("读取工作记录时发生错误")); pending.current.clear();};
    return () => {++loadEpoch.current; w.terminate(); worker.current = null; for (const item of pending.current.values()) item.reject(new Error("读取已取消")); pending.current.clear();};
  }, []);
  const load = useCallback(async (attempt?: number, refresh = false) => {
    const epoch = ++loadEpoch.current;
    setLoading(true); setError("");
    try {
      const result: WorkflowView | null = await send(attempt !== undefined && !refresh ? {action: "attempt", attempt} : {action: "load", attempt,
        url: `/api/agent/review-suggestions/${part(review)}/${part(sentence)}?project_id=${part(project)}&tenant_id=${part(tenant)}`});
      if (epoch !== loadEpoch.current) return;
      setView(result); setSelected(previous => result?.nodes.some(n => n.id === previous) ? previous :
        result?.nodes.find(n => n.role === "analysis")?.id || result?.nodes[0]?.id || "");
      if (!result?.nodes.length) setTab("all");
    } catch (e) {if (epoch === loadEpoch.current) setError(e instanceof Error ? e.message : String(e));}
    finally {if (epoch === loadEpoch.current) setLoading(false);}
  }, [review, sentence, project, tenant, send]);
  useEffect(() => {void load();}, [load, revision]);
  const node = view?.nodes.find(n => n.id === selected);
  const nodeSteps = useMemo(() => view?.steps.filter(s => s.nodeId === selected) || [], [view, selected]);
  const detail = useCallback((id: string) => send({action: "detail", stepId: id}), [send]);
  return <div className="review-workflow"><div className="workflow-run-toolbar"><span><Clock3 size={14} />{view ? date(view.startedAt) : "读取执行记录"}</span><span><ListChecks size={14} />{view?.steps.length || 0} 条步骤记录</span>
    {view && <><ExecutionTag value={view.status} /><Select aria-label="选择执行尝试" disabled={loading} value={view.attempt} onChange={n => void load(n)} options={view.attempts.map(a => ({value: a.number, label: `第 ${a.number} 次执行 · ${statusNames[a.status] || a.status} · ${a.modelCount} 次模型请求`}))} /></>}
    <Button size="small" loading={loading} icon={<RefreshCw size={14} />} onClick={() => void load(view?.attempt === view?.attempts[0]?.number ? undefined : view?.attempt, true)}>刷新记录</Button></div>
    <ErrorNotice error={error} />{loading ? <Busy /> : !view ? <section className="result-card"><NoData title="尚无可展示的 LLM 工作记录" detail="此语段没有保存模型调用轨迹。不会将未执行角色显示为已完成。" /></section> : <>
      {view.nodes.length ? <ReactFlowProvider><WorkflowCanvas view={view} selected={selected} select={id => {setSelected(id); setTab("node");}} /></ReactFlowProvider> : <section className="result-card"><NoData title="未保存模型调用节点" detail="模型请求之前的执行错误仍可在下方全流程记录中查看。不生成虚构的 Agent 节点。" /></section>}
      {view.error && <Alert className="workflow-run-error" type="warning" showIcon title={`此尝试存在执行异常：${view.error.code}`} description={view.error.message} />}
      <section className="result-card workflow-inspector"><Tabs activeKey={tab} onChange={setTab} items={[
        {key: "node", label: "节点详情", children: node && <><div className="workflow-node-heading"><h2>节点详情 · {node.title}</h2><ExecutionTag value={node.status} /></div>
          <div className="workflow-node-summary"><div><strong><Bot size={15} />Agent 职责</strong><p>{node.purpose}</p><strong><Clock3 size={15} />当前阶段</strong><p><span className="workflow-phase model">{node.phase}</span></p><strong><FileText size={15} />审核语段</strong><p className="workflow-source-text">{sourceText}</p></div>
            <div><strong><ListChecks size={15} />输出与状态</strong><p>保存了 {nodeSteps.filter(s => s.kind === "model").length} 次模型调用、{nodeSteps.filter(s => s.kind === "tool").length} 次工具调用{nodeSteps.some(s => s.kind === "error") ? "；有执行错误记录" : ""}。</p><strong><Wrench size={15} />使用工具</strong><p className="workflow-tools">{node.tools.length ? node.tools.map(t => <Tag key={t} title={t}>{toolLabel(t)}</Tag>) : "本节点没有记录工具调用"}</p><strong><Info size={15} />记录范围</strong><p>展示公开输出及实际保存的工具记录。“思考”表示正在等待模型输出，不展示或补写隐藏推理。</p></div></div>
          <RecordList key={`${view.attempt}/${selected}`} steps={nodeSteps} detail={detail} nodeMode /></>},
        {key: "all", label: "全流程执行面板", children: <RecordList key={`all/${view.attempt}`} steps={view.steps} detail={detail} />},
      ]} /></section>
    </>}
  </div>;
}
