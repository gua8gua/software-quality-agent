import { useEffect, useMemo, useRef, useState } from "react";
import { Alert, Button, Checkbox, Empty, Input, Modal, Steps, Table, Tag, Tree, type TreeDataNode } from "antd";
import { FileText, Folder as FolderIcon, GitBranch, Play, UserRound, X } from "lucide-react";
import { navigate } from "../../navigation";
import { api as library, part, type Artifact, type Folder } from "../api";
import { Busy, ErrorNotice, NoData, ResultShell, Status, useRead } from "./shared";
import { resultsApi, type Run, type TlrScope, type TlrScopeNode } from "./api";
import "./results.css";

const ROOT = "__root__";

function roleLabel(role: "requirement" | "design") {
  return role === "requirement" ? "需求说明文档" : "设计说明文档";
}

function fileFormat(file: Artifact) {
  return file.file_format?.replace(/^\./, "").toUpperCase() || file.media_type || "文件";
}

function folderTree(folders: Folder[]): TreeDataNode[] {
  const nodes = new Map(folders.map(folder => [folder.id, { key: folder.id, title: folder.name, icon: <FolderIcon size={15} />, children: [] as TreeDataNode[] }]));
  const root: TreeDataNode = { key: ROOT, title: "项目文件", icon: <FolderIcon size={15} />, children: [] };
  for (const folder of [...folders].sort((a, b) => a.name.localeCompare(b.name, "zh-CN"))) {
    const node = nodes.get(folder.id);
    if (!node) continue;
    const parent = folder.parent_id ? nodes.get(folder.parent_id) : root;
    parent?.children?.push(node);
  }
  return [root];
}

function fileFolderPath(folders: Folder[], folderId: string | null) {
  const byId = new Map(folders.map(folder => [folder.id, folder]));
  const parts: string[] = [];
  const visited = new Set<string>();
  let current = folderId ? byId.get(folderId) : undefined;
  while (current && !visited.has(current.id)) {
    visited.add(current.id);
    parts.unshift(current.name);
    current = current.parent_id ? byId.get(current.parent_id) : undefined;
  }
  return ["项目文件", ...parts].join(" / ");
}

/** Selection stops at artifact level. The tree only scopes the file list. */
function ArtifactScopePicker({
  role, files, folders, value, onChange, label,
}: {
  role: "requirement" | "design";
  files: Artifact[];
  folders: Folder[];
  value: string[];
  onChange: (value: string[]) => void;
  label: string;
}) {
  const options = files.filter(file => file.modality === "text" && file.engineering_role === role);
  const [folderId, setFolderId] = useState<string | null>(null);
  const initialized = useRef(false);
  useEffect(() => {
    if (!initialized.current && options.length) {
      setFolderId(options.find(file => value.includes(file.id))?.folder_id ?? options[0].folder_id);
      initialized.current = true;
    }
  }, [options, value]);
  const visible = options.filter(file => file.folder_id === folderId);
  const selected = options.filter(file => value.includes(file.id));
  const toggle = (id: string, checked: boolean) => onChange(checked ? [...new Set([...value, id])] : value.filter(item => item !== id));
  return <section className="task-picker result-card">
    <div className="task-picker-heading">
      <span className={`task-picker-icon ${role}`}><FileText size={18} /></span>
      <div><h2>{label}</h2><p>工件类型：<Tag color={role === "requirement" ? "green" : "blue"}>{roleLabel(role)}</Tag></p></div>
      <span className="task-picker-count">已选 {selected.length} 份</span>
    </div>
    <div className="artifact-scope-picker">
      <div className="artifact-folder-pane"><div className="scope-pane-title">项目文件</div>
        <Tree showIcon blockNode treeData={folderTree(folders)} selectedKeys={[folderId || ROOT]} defaultExpandAll onSelect={keys => setFolderId(keys[0] && keys[0] !== ROOT ? String(keys[0]) : null)} />
      </div>
      <div className="artifact-file-pane"><div className="scope-pane-toolbar"><span>{fileFolderPath(folders, folderId)}</span><small>{visible.length} 份可选工件</small></div>
        <div className="artifact-file-columns"><span>文件名</span><span>格式</span><span>上传时间</span></div>
        {visible.length ? visible.map(file => <label className={`artifact-file-row ${value.includes(file.id) ? "checked" : ""}`} key={file.id}>
          <Checkbox checked={value.includes(file.id)} onChange={event => toggle(file.id, event.target.checked)} /><FileText size={16} className="artifact-file-icon" />
          <span className="artifact-file-name" title={file.filename}>{file.filename}</span><Tag>{fileFormat(file)}</Tag><small>{file.uploaded_at ? new Date(file.uploaded_at).toLocaleDateString("zh-CN") : "—"}</small>
        </label>) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前目录没有此类工件" />}
      </div>
      <div className="artifact-selected-pane"><div className="scope-pane-title"><span>已选工件（{selected.length}）</span>{selected.length > 0 && <Button type="link" size="small" onClick={() => onChange([])}>清空</Button>}</div>
        {selected.length ? selected.map(file => <div className="artifact-selected-row" key={file.id}><span title={file.filename}>{file.filename}</span><Button type="text" size="small" aria-label={`移除 ${file.filename}`} icon={<X size={14} />} onClick={() => toggle(file.id, false)} /></div>) : <p className="scope-empty">请在中间列表勾选工件</p>}
      </div>
    </div>
  </section>;
}

function nodeTitle(node: TlrScopeNode) {
  return node.title || node.preview || `${node.node_type} · ${node.node_id.slice(0, 8)}`;
}

function treeForScope(scope: TlrScope, side: "source" | "target", artifactIds: string[]): TreeDataNode[] {
  const allowedArtifacts = new Set(artifactIds);
  const nodes = scope.nodes.filter(node => node.side === side && allowedArtifacts.has(node.artifact_id));
  const byId = new Map(nodes.map(node => [node.node_id, node]));
  const children = new Map<string | null, TlrScopeNode[]>();
  for (const node of nodes) {
    const parentId = node.parent_id && byId.has(node.parent_id) ? node.parent_id : null;
    const group = children.get(parentId) || [];
    group.push(node);
    children.set(parentId, group);
  }
  const build = (parentId: string | null): TreeDataNode[] => (children.get(parentId) || [])
    .sort((a, b) => a.reading_order - b.reading_order || a.node_id.localeCompare(b.node_id))
    .map(node => {
      const childNodes = build(node.node_id);
      return {
        key: node.node_id,
        title: <span className="tlr-node-title" title={node.preview}>{nodeTitle(node)}{node.selectable ? "" : " · 结构"}</span>,
        children: childNodes.length ? childNodes : undefined,
        disableCheckbox: !node.selectable && !childNodes.length,
      };
    });
  return build(null);
}

function TlrNodeScopePicker({
  scope, side, artifactIds, onArtifactIds, nodeIds, onNodeIds,
}: {
  scope: TlrScope;
  side: "source" | "target";
  artifactIds: string[];
  onArtifactIds: (ids: string[]) => void;
  nodeIds: string[];
  onNodeIds: (ids: string[]) => void;
}) {
  const artifacts = scope.artifacts.filter(item => item.side === side);
  const nodeById = new Map(scope.nodes.map(node => [node.node_id, node]));
  const selectableIn = (ids: string[]) => scope.nodes.filter(node => node.side === side && ids.includes(node.artifact_id) && node.selectable).map(node => node.node_id);
  const toggleArtifact = (artifactId: string, checked: boolean) => {
    const nextArtifacts = checked ? [...new Set([...artifactIds, artifactId])] : artifactIds.filter(id => id !== artifactId);
    const nextNodes = checked ? [...new Set([...nodeIds, ...selectableIn([artifactId])])] : nodeIds.filter(id => nodeById.get(id)?.artifact_id !== artifactId);
    onArtifactIds(nextArtifacts);
    onNodeIds(nextNodes);
  };
  const checked = new Set(nodeIds);
  const removeNode = (nodeId: string) => onNodeIds(nodeIds.filter(id => id !== nodeId));
  const label = side === "source" ? "需求侧节点范围" : "设计侧节点范围";
  const tree = treeForScope(scope, side, artifactIds);
  return <section className="task-picker result-card tlr-node-scope">
    <div className="task-picker-heading">
      <span className={`task-picker-icon ${side === "source" ? "requirement" : "design"}`}><GitBranch size={18} /></span>
      <div><h2>{label}</h2><p>仅显示此 TLR 实际参与追溯的节点；结构节点用于展开和级联选择。</p></div>
      <span className="task-picker-count">已选 {nodeIds.length} 个节点</span>
    </div>
    <div className="tlr-node-scope-grid">
      <div className="tlr-scope-artifacts"><div className="scope-pane-title">TLR 涉及工件</div>
        {artifacts.map(artifact => <label className={`tlr-artifact-option ${artifactIds.includes(artifact.artifact_id) ? "checked" : ""}`} key={artifact.artifact_id}>
          <Checkbox checked={artifactIds.includes(artifact.artifact_id)} onChange={event => toggleArtifact(artifact.artifact_id, event.target.checked)} />
          <FileText size={15} /><span title={artifact.filename}>{artifact.filename}</span><small>{artifact.used_node_count} 个节点</small>
        </label>)}
        {!artifacts.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="此侧没有可用工件" />}
      </div>
      <div className="tlr-scope-tree"><div className="scope-pane-toolbar"><span>TLR 可追溯节点</span><small>{tree.length ? "勾选父节点可级联选择全部子节点" : "先选择工件"}</small></div>
        {tree.length ? <Tree checkable blockNode defaultExpandAll treeData={tree} checkedKeys={[...checked]} onCheck={keys => {
          const values = Array.isArray(keys) ? keys : keys.checked;
          const next = values.map(String).filter(id => nodeById.get(id)?.side === side && nodeById.get(id)?.selectable);
          onNodeIds(next);
        }} /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="所选工件没有已保存的 TLR 节点" />}
      </div>
      <div className="tlr-scope-selected"><div className="scope-pane-title"><span>已选节点（{nodeIds.length}）</span>{nodeIds.length > 0 && <Button type="link" size="small" onClick={() => onNodeIds([])}>清空</Button>}</div>
        {nodeIds.length ? nodeIds.map(nodeId => { const node = nodeById.get(nodeId); return node ? <div className="tlr-selected-node" key={nodeId}><span title={node.preview}>{nodeTitle(node)}</span><Button type="text" size="small" aria-label={`移除节点 ${nodeTitle(node)}`} icon={<X size={13} />} onClick={() => removeNode(nodeId)} /></div> : null; }) : <p className="scope-empty">请在中间树中选择节点</p>}
      </div>
    </div>
  </section>;
}

function StepHeader({ analysis, current }: { analysis: boolean; current: number }) {
  return <div className="task-page-heading"><div><h1>{analysis ? "新建一致性分析任务" : "新建追溯任务"}</h1><p>{analysis ? "选择需要分析的工件，并关联已有追溯记录" : "选择源工件与目标工件，确认追溯范围并启动任务"}</p></div>
    <Steps className="task-start-steps" labelPlacement="vertical" current={current} size="small" items={[{ title: "选择工件" }, { title: "确认范围" }, { title: "启动任务" }]} /></div>;
}

function BasicInfo({name, description, projectName, onName, onDescription}: {name: string; description: string; projectName: string; onName: (value: string) => void; onDescription: (value: string) => void}) {
  return <section className="result-card task-basic-info"><div className="result-card-heading"><h2><UserRound size={18} />基本信息</h2></div><div className="task-basic-fields">
    <label>任务名称 <b>*</b><Input aria-label="任务名称" value={name} maxLength={200} onChange={event => onName(event.target.value)} /></label>
    <label>所属项目<Input value={projectName} readOnly aria-label="所属项目" /></label>
    <label className="task-description-field">任务描述<Input.TextArea aria-label="任务描述" value={description} rows={2} maxLength={2000} showCount onChange={event => onDescription(event.target.value)} placeholder="说明本次任务的目的（选填）" /></label>
  </div></section>;
}

function shortcutIds(side: string) {
  const value = new URLSearchParams(window.location.hash.split("?")[1] || "").get(side);
  return value ? [value] : [];
}

function runArtifacts(run: Run | undefined, role: "source" | "target") {
  const ids = run?.config?.[role === "source" ? "source_artifact_ids" : "target_artifact_ids"];
  return Array.isArray(ids) ? ids.filter((value): value is string => typeof value === "string") : [];
}

export function TraceStartPage({ tenant, project }: { tenant: string; project: string }) {
  const access = useMemo(() => resultsApi(tenant, project), [tenant, project]);
  const files = useRead(signal => library.artifacts(tenant, project), [tenant, project]);
  const folders = useRead(signal => library.folders(tenant, project), [tenant, project]);
  const info = useRead(() => library.project(tenant, project), [tenant, project]);
  const [sourceIds, setSourceIds] = useState<string[]>(() => shortcutIds("source")); const [targetIds, setTargetIds] = useState<string[]>(() => shortcutIds("target")); const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  const [name, setName] = useState("需求—设计追溯"); const [description, setDescription] = useState(""); const [confirming, setConfirming] = useState(false);
  async function start() {
    if (!sourceIds.length || !targetIds.length) { setError("请至少选择一份需求说明文档和一份设计说明文档。"); return; }
    setBusy(true); setError("");
    try { const created = await access.createRun(sourceIds, targetIds, name.trim(), description); await access.executeRun(created.id); navigate(`/projects/${part(project)}/trace/${part(created.id)}`); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  }
  const selectedSources = (files.data || []).filter(file => sourceIds.includes(file.id)); const selectedTargets = (files.data || []).filter(file => targetIds.includes(file.id));
  return <ResultShell project={project} name={info.data?.name || ""} active="trace"><div className="task-form"><StepHeader analysis={false} current={busy ? 2 : confirming ? 1 : 0} /><ErrorNotice error={info.error || files.error || folders.error || error} />
    {files.loading || folders.loading ? <Busy /> : <><div className="task-basics-layout"><BasicInfo name={name} description={description} projectName={info.data?.name || ""} onName={setName} onDescription={setDescription} />
      <aside className="task-overview result-card"><div className="result-card-heading"><h2><GitBranch size={18} />任务概览</h2></div><dl><div><dt>源工件</dt><dd>{selectedSources.length} 份</dd></div><div><dt>目标工件</dt><dd>{selectedTargets.length} 份</dd></div><div><dt>分析内容</dt><dd>需求与设计的正式关联</dd></div></dl><p>追溯会按已选工件建立结果，后续页面可查看文档层级与关联证据。</p></aside></div>
      <ArtifactScopePicker role="requirement" files={files.data || []} folders={folders.data || []} value={sourceIds} onChange={setSourceIds} label="源工件" />
      <ArtifactScopePicker role="design" files={files.data || []} folders={folders.data || []} value={targetIds} onChange={setTargetIds} label="目标工件" />
      <div className="task-start-actions"><Button onClick={() => navigate(`/projects/${part(project)}/trace`)}>取消</Button><Button type="primary" icon={<Play size={16} />} loading={busy} onClick={() => setConfirming(true)} disabled={!sourceIds.length || !targetIds.length || !name.trim()}>启动追溯</Button></div>
      <Modal open={confirming} title="确认追溯范围" onCancel={() => setConfirming(false)} confirmLoading={busy} onOk={() => void start()} okText="确认并启动"><p>源工件 {selectedSources.length} 份，目标工件 {selectedTargets.length} 份。</p><p>将为已选工件建立新的追溯记录。</p></Modal></>}</div></ResultShell>;
}

export function AnalysisStartPage({ tenant, project }: { tenant: string; project: string }) {
  const access = useMemo(() => resultsApi(tenant, project), [tenant, project]); const info = useRead(() => library.project(tenant, project), [tenant, project]);
  const files = useRead(signal => library.artifacts(tenant, project), [tenant, project]); const runs = useRead(signal => access.runs(signal), [access]);
  const completed = useMemo(() => (runs.data || []).filter(run => run.status === "completed"), [runs.data]); const [runId, setRunId] = useState(""); const [sourceIds, setSourceIds] = useState<string[]>([]); const [targetIds, setTargetIds] = useState<string[]>([]); const [sourceNodeIds, setSourceNodeIds] = useState<string[]>([]); const [targetNodeIds, setTargetNodeIds] = useState<string[]>([]); const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  const [name, setName] = useState("需求—设计一致性分析"); const [description, setDescription] = useState(""); const [confirming, setConfirming] = useState(false);
  const selectedRun = completed.find(run => run.run_id === runId); const runSourceIds = runArtifacts(selectedRun, "source"); const runTargetIds = runArtifacts(selectedRun, "target");
  const scope = useRead(signal => runId ? access.scope(runId, signal) : Promise.resolve<TlrScope>({run_id: "", artifacts: [], nodes: [], selected_source_node_ids: [], selected_target_node_ids: [], note: ""}), [access, runId]);
  useEffect(() => { if (!runId && completed.length) { const source = shortcutIds("source")[0], target = shortcutIds("target")[0]; const compatible = completed.find(run => (!source || runArtifacts(run, "source").includes(source)) && (!target || runArtifacts(run, "target").includes(target))); setRunId((compatible || completed[0]).run_id); } }, [completed, runId]);
  useEffect(() => {
    if (!scope.data || scope.data.run_id !== selectedRun?.run_id) return;
    const requestedSources = shortcutIds("source");
    const requestedTargets = shortcutIds("target");
    const availableSources = scope.data.artifacts.filter(item => item.side === "source").map(item => item.artifact_id);
    const availableTargets = scope.data.artifacts.filter(item => item.side === "target").map(item => item.artifact_id);
    const nextSources = (requestedSources.length ? requestedSources : availableSources).filter(id => availableSources.includes(id));
    const nextTargets = (requestedTargets.length ? requestedTargets : availableTargets).filter(id => availableTargets.includes(id));
    setSourceIds(nextSources);
    setTargetIds(nextTargets);
    setSourceNodeIds(scope.data.selected_source_node_ids.filter(id => nextSources.includes(scope.data!.nodes.find(node => node.node_id === id)?.artifact_id || "")));
    setTargetNodeIds(scope.data.selected_target_node_ids.filter(id => nextTargets.includes(scope.data!.nodes.find(node => node.node_id === id)?.artifact_id || "")));
  }, [scope.data, selectedRun?.run_id]);
  async function start() {
    if (!runId || !sourceIds.length || !targetIds.length || !sourceNodeIds.length || !targetNodeIds.length) { setError("请选择已完成追溯记录、源/目标工件，并至少勾选双方各一个 TLR 节点。"); return; }
    setBusy(true); setError("");
    try { const batch = await access.createReviewBatch(runId, sourceIds, targetIds, name.trim(), description, sourceNodeIds, targetNodeIds); await access.runReviewAgentsBatch(batch.batch_id); navigate(`/projects/${part(project)}/analysis/batch/${part(batch.batch_id)}`); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  }
  const selectedSources = (files.data || []).filter(file => sourceIds.includes(file.id)); const selectedTargets = (files.data || []).filter(file => targetIds.includes(file.id));
  const excludedCount = sourceIds.filter(id => !runSourceIds.includes(id)).length + targetIds.filter(id => !runTargetIds.includes(id)).length;
  return <ResultShell project={project} name={info.data?.name || ""} active="analysis"><div className="task-form"><StepHeader analysis current={busy ? 2 : confirming ? 1 : 0} /><ErrorNotice error={info.error || files.error || runs.error || scope.error || error} />
    {files.loading || runs.loading || scope.loading ? <Busy /> : !completed.length ? <section className="result-card"><NoData title="还没有可用的已完成追溯记录" detail="请先在追溯任务入口选择工件并完成一次追溯。" /></section> : <>
      <BasicInfo name={name} description={description} projectName={info.data?.name || ""} onName={setName} onDescription={setDescription} />
      <section className="task-run-picker result-card"><div className="result-card-heading"><h2><GitBranch size={18} />关联追溯记录</h2><span>选择本次分析依据的已完成记录</span></div>
        <Table<Run> size="small" rowKey="run_id" dataSource={completed} pagination={false} rowSelection={{type: "radio", selectedRowKeys: [runId], onChange: keys => setRunId(String(keys[0]))}} onRow={run => ({onClick: () => setRunId(run.run_id)})} columns={[{title: "记录名称", render: (_, run) => String(run.config?.task_name || "需求—设计追溯")}, {title: "源工件", render: (_, run) => runArtifacts(run, "source").map(id => (files.data || []).find(file => file.id === id)?.filename || "文件已移除").join("、")}, {title: "目标工件", render: (_, run) => runArtifacts(run, "target").map(id => (files.data || []).find(file => file.id === id)?.filename || "文件已移除").join("、")}, {title: "创建时间", width: 165, render: (_, run) => new Date(run.created_at).toLocaleString("zh-CN")}, {title: "状态", width: 95, render: () => <Status value="completed" />}]} />
        {excludedCount > 0 && <Alert type="warning" showIcon title={`${excludedCount} 份工件未被此追溯记录覆盖，将不参与实际分析`} />}
        <p>选中记录后，下方只展示该记录实际使用过的工件与节点；本次不会重新运行追溯。</p></section>
      {scope.data && <><TlrNodeScopePicker scope={scope.data} side="source" artifactIds={sourceIds} onArtifactIds={setSourceIds} nodeIds={sourceNodeIds} onNodeIds={setSourceNodeIds} /><TlrNodeScopePicker scope={scope.data} side="target" artifactIds={targetIds} onArtifactIds={setTargetIds} nodeIds={targetNodeIds} onNodeIds={setTargetNodeIds} /></>}
      <div className="task-start-actions"><Button onClick={() => navigate(`/projects/${part(project)}/analysis`)}>取消</Button><Button type="primary" icon={<Play size={16} />} loading={busy} onClick={() => setConfirming(true)} disabled={busy || !runId || !sourceNodeIds.length || !targetNodeIds.length || !name.trim()}>启动分析</Button></div>
      <Modal open={confirming} title="确认分析范围" onCancel={() => setConfirming(false)} confirmLoading={busy} onOk={() => void start()} okText="确认并启动"><p>源工件 {selectedSources.length} 份、需求节点 {sourceNodeIds.length} 个；目标工件 {selectedTargets.length} 份、设计节点 {targetNodeIds.length} 个。</p><p>分析只会读取上述 TLR 节点及其保存的追溯事实；每个审核单元独立保存进度与错误。</p></Modal></>}</div></ResultShell>;
}

export default function TaskStartPage({ tenant, project, mode }: { tenant: string; project: string; mode: "trace" | "analysis" }) {
  return mode === "trace" ? <TraceStartPage tenant={tenant} project={project} /> : <AnalysisStartPage tenant={tenant} project={project} />;
}
