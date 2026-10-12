import { useEffect, useMemo, useRef, useState, type ComponentRef } from "react";
import { Input, Pagination, Tree, type TreeDataNode } from "antd";
import { Background, Controls, Handle, Position, ReactFlow, type Node, type NodeProps } from "@xyflow/react";
import { FileText, GitBranch, Search } from "lucide-react";
import type { Canonical, Visualization } from "./api";
import { title, pathOf } from "./canonical";
import { NoData, Status } from "./shared";

type PassageNode = Node<{node: Canonical; path: string; side: "source" | "target"; relation?: string; selected: boolean}, "passage">;

function treeOf(graph: Visualization, query: string, artifact: string) {
  const byId = new Map(graph.nodes.map(node => [node.node_id, node]));
  const leaves = new Set(graph.units.filter(unit => unit.side === "source" && (!artifact || unit.artifact_id === artifact)).map(unit => unit.node_id));
  const kept = new Set<string>();
  for (const id of leaves) {
    let node = byId.get(id); if (!node || query && ![title(node), ...pathOf(node, graph.nodes), id].join(" ").toLowerCase().includes(query.toLowerCase())) continue;
    const seen = new Set<string>(); while (node && !seen.has(node.node_id)) { seen.add(node.node_id); kept.add(node.node_id); node = byId.get(node.parent_id || ""); }
  }
  const children = new Map<string, Canonical[]>();
  for (const node of graph.nodes) if (kept.has(node.node_id)) children.set(node.parent_id || "", [...(children.get(node.parent_id || "") || []), node]);
  const build = (node: Canonical): TreeDataNode => ({key: node.node_id, selectable: leaves.has(node.node_id),
    title: <span className={`trace-tree-row ${leaves.has(node.node_id) ? "leaf" : "branch"}`} data-trace-leaf={leaves.has(node.node_id) ? node.node_id : undefined} title={`${title(node)}\n${node.node_id}`}>
      {leaves.has(node.node_id) ? <i /> : <GitBranch size={12} />}<span>{title(node)}</span></span>,
    children: (children.get(node.node_id) || []).sort((a,b) => a.reading_order - b.reading_order).map(build)});
  return graph.nodes.filter(node => kept.has(node.node_id) && (!node.parent_id || !kept.has(node.parent_id))).sort((a,b) => a.reading_order - b.reading_order).map(build);
}
function ancestorKeys(graph: Visualization, id: string) {
  const byId = new Map(graph.nodes.map(node => [node.node_id, node])); const result: string[] = []; const seen = new Set<string>();
  let parent = byId.get(id)?.parent_id;
  while (parent && !seen.has(parent)) { seen.add(parent); result.push(parent); parent = byId.get(parent)?.parent_id; }
  return result;
}

function Passage({data}: NodeProps<PassageNode>) {
  return <div className={`trace-passage ${data.side === "source" ? "is-source" : "is-target"} ${data.selected ? "selected" : ""}`}>
    {data.side === "target" && <Handle type="target" position={Position.Left} isConnectable={false} />}
    <div className="passage-heading"><FileText size={14} /><span>{data.side === "source" ? "需求语块" : "设计语块"}</span>{data.relation && <Status value={data.relation} />}</div>
    <div className="passage-path" title={data.path}>{data.path || "文档根级"}</div><div className="passage-preview">{title(data.node)}</div>
    {data.side === "source" && <Handle type="source" position={Position.Right} isConnectable={false} />}
  </div>;
}
const nodeTypes = {passage: Passage};

export function TraceHierarchy({graph, source, selected, artifact, targetArtifact, query, relation, onSource, onTarget, onQuery}: {
  graph: Visualization; source: string; selected: string; artifact: string; targetArtifact: string; query: string; relation: string;
  onSource: (id: string) => void; onTarget: (id: string) => void; onQuery: (query: string) => void;
}) {
  const treeRef = useRef<ComponentRef<typeof Tree>>(null);
  const tree = useMemo(() => treeOf(graph, query, artifact), [graph, query, artifact]);
  const [expanded, setExpanded] = useState<string[]>([]);
  useEffect(() => { setExpanded(ancestorKeys(graph, source)); const timer = window.setTimeout(() => treeRef.current?.scrollTo({key: source, align: "top"}), 50); return () => window.clearTimeout(timer); }, [graph, source, artifact, query]);
  const links = useMemo(() => graph.links.filter(link => (!relation || link.relation === relation) &&
    (!artifact || graph.units.some(unit => unit.node_id === link.source_node_id && unit.artifact_id === artifact)) &&
    (!targetArtifact || graph.units.some(unit => unit.node_id === link.target_node_id && unit.artifact_id === targetArtifact))), [graph, artifact, targetArtifact, relation]);
  const all = links.filter(link => link.source_node_id === source);
  const [page, setPage] = useState(1);
  useEffect(() => setPage(1), [source, relation, artifact, targetArtifact]);
  const rows = all.slice((page - 1) * 3, page * 3);
  const byId = new Map(graph.nodes.map(node => [node.node_id, node]));
  const sourceNode = byId.get(source);
  const nodes: PassageNode[] = sourceNode ? [{id: source, type: "passage", position: {x: 30, y: Math.max(45, (rows.length - 1) * 67)}, data: {node: sourceNode, path: pathOf(sourceNode, graph.nodes).join(" / "), side: "source", selected: false}}, ...rows.flatMap((link, index) => {
    const node = byId.get(link.target_node_id); return node ? [{id: `${link.id}:target`, type: "passage" as const, position: {x: 490, y: index * 140}, data: {node, path: pathOf(node, graph.nodes).join(" / "), side: "target" as const, relation: link.relation, selected: link.target_node_id === selected}}] : [];
  })] : [];
  const edges = rows.map(link => ({id: link.id, source, target: `${link.id}:target`, type: "default", style: {stroke: link.target_node_id === selected ? "#1677ff" : link.relation === "direct" ? "#75a6f5" : "#c0ccdc", strokeWidth: link.target_node_id === selected ? 2.8 : 1.6}}));
  return <div className="trace-visual-reference">
    <div className="trace-tree-reference"><div className="tree-heading">需求文档层级</div><Input aria-label="查找需求" placeholder="查找原文、章节或节点 ID" prefix={<Search size={14} />} value={query} onChange={event => onQuery(event.target.value)} allowClear />
      {tree.length ? <Tree ref={treeRef} blockNode showLine height={426} expandedKeys={expanded} onExpand={keys => setExpanded(keys.map(String))} selectedKeys={[source]} onSelect={keys => { if (keys[0]) onSource(String(keys[0])); }} treeData={tree} /> : <NoData title="无匹配需求" detail="调整文档或搜索条件。" />}</div>
    <div className="trace-canvas-reference"><div className="tree-heading">{all.length} 条关联设计 · 连线可点击</div>{!sourceNode || !all.length ? <div className="graph-no-links"><NoData title={sourceNode ? "此需求没有符合筛选的正式链接" : "请选择需求语块"} detail="可切换文档或关系筛选；正式链接不会被自动生成。" /></div> : <><div className="link-graph"><ReactFlow key={`${source}/${page}/${relation}`} nodes={nodes} edges={edges} nodeTypes={nodeTypes} nodesDraggable={false} nodesConnectable={false} elementsSelectable={false} deleteKeyCode={null} fitView fitViewOptions={{padding: .08, maxZoom: 1}} minZoom={.25} maxZoom={1.6} onNodeClick={(_, node) => {const link = rows.find(item => `${item.id}:target` === node.id); if (link) onTarget(link.target_node_id);}} onEdgeClick={(_, edge) => {const link = rows.find(item => item.id === edge.id); if (link) { onSource(link.source_node_id); onTarget(link.target_node_id); }}}><Background color="#e5edf7" gap={22} /><Controls showInteractive={false} /></ReactFlow></div><div className="graph-paging"><span>蓝：直接追溯 · 灰：相关 · 每页 3 条</span><Pagination size="small" current={page} pageSize={3} total={all.length} showSizeChanger={false} onChange={setPage} /></div></>}</div>
  </div>;
}
