import { useEffect, useMemo, useRef, useState } from "react";
import { Input, Select } from "antd";
import { Background, Handle, Position, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import { ChevronDown, ChevronRight, FileText, Search } from "lucide-react";
import type { Canonical, Link, Visualization } from "./api";
import { title, pathOf } from "./canonical";
import { NoData } from "./shared";

type Side = "source" | "target";
export type TraceExpansion = Record<Side, Set<string>>;
type HierarchyData = {
  node?: Canonical;
  side: Side;
  depth?: number;
  expanded?: boolean;
  hasChildren?: boolean;
  selected?: boolean;
  header?: boolean;
  label?: string;
  count?: number;
  onToggle?: (id: string) => void;
};
type HierarchyNode = Node<HierarchyData, "hierarchyRow">;

type Row = Canonical & { depth: number; hasChildren: boolean; expanded: boolean };
type SideModel = {
  rows: Row[];
  visible: Set<string>;
  representative: Map<string, string>;
  nodeIds: Set<string>;
  roots: Canonical[];
};

function orderedChildren(nodes: Canonical[]) {
  const children = new Map<string, Canonical[]>();
  for (const node of nodes) {
    const key = node.parent_id || "";
    children.set(key, [...(children.get(key) || []), node]);
  }
  for (const list of children.values()) list.sort((a, b) => a.reading_order - b.reading_order || ((a as Canonical & {sibling_ordinal?: number}).sibling_ordinal || 0) - ((b as Canonical & {sibling_ordinal?: number}).sibling_ordinal || 0));
  return children;
}

function nodesForSide(graph: Visualization, side: Side, artifact = "") {
  const artifactIds = new Set(graph.units.filter(unit => unit.side === side && (!artifact || unit.artifact_id === artifact)).map(unit => unit.artifact_id));
  return graph.nodes.filter(node => artifactIds.has(node.artifact_id));
}

function levelsOf(nodes: Canonical[]) {
  const byId = new Map(nodes.map(node => [node.node_id, node]));
  const children = orderedChildren(nodes);
  const levels = new Map<string, number>();
  const walk = (node: Canonical, level: number) => {
    if (levels.has(node.node_id)) return;
    levels.set(node.node_id, level);
    (children.get(node.node_id) || []).forEach(child => walk(child, level + 1));
  };
  nodes.filter(node => !node.parent_id || !byId.has(node.parent_id)).forEach(node => walk(node, 1));
  return {levels, branches: new Set(nodes.filter(node => children.has(node.node_id)).map(node => node.node_id)), max: Math.max(1, ...levels.values())};
}

function initialExpansion(graph: Visualization, source: string, selected: string): TraceExpansion {
  const result: TraceExpansion = {source: new Set(), target: new Set()};
  const initialSource = source || graph.units.find(unit => unit.side === "source")?.node_id || "";
  const focus = {source: [initialSource], target: [selected, ...graph.links.filter(link => link.source_node_id === initialSource).map(link => link.target_node_id)]};
  for (const side of ["source", "target"] as const) {
    const nodes = nodesForSide(graph, side);
    const byId = new Map(nodes.map(node => [node.node_id, node]));
    for (const node of nodes) if (!node.parent_id || !byId.has(node.parent_id)) result[side].add(node.node_id);
    for (const id of focus[side]) {
      let parent = byId.get(id)?.parent_id;
      const seen = new Set<string>();
      while (parent && byId.has(parent) && !seen.has(parent)) {
        seen.add(parent); result[side].add(parent); parent = byId.get(parent)?.parent_id;
      }
    }
  }
  return result;
}

function keepForQuery(nodes: Canonical[], all: Canonical[], query: string, focus: Set<string>) {
  const byId = new Map(all.map(node => [node.node_id, node]));
  const kept = new Set<string>(focus);
  const q = query.trim().toLowerCase();
  if (!q) nodes.forEach(node => kept.add(node.node_id));
  else for (const node of nodes) {
    const haystack = [title(node), node.node_id, ...pathOf(node, all)].join(" ").toLowerCase();
    if (haystack.includes(q)) kept.add(node.node_id);
  }
  for (const id of [...kept]) {
    let node = byId.get(id);
    const seen = new Set<string>();
    while (node?.parent_id && !seen.has(node.parent_id)) {
      seen.add(node.parent_id); kept.add(node.parent_id); node = byId.get(node.parent_id);
    }
  }
  return kept;
}

function sideModel(graph: Visualization, side: Side, artifact: string, query: string, expanded: Set<string>, focusIds: Set<string>): SideModel {
  const nodes = nodesForSide(graph, side, artifact);
  const byId = new Map(nodes.map(node => [node.node_id, node]));
  const children = orderedChildren(nodes);
  const roots = nodes.filter(node => !node.parent_id || !byId.has(node.parent_id));
  const keep = keepForQuery(nodes, graph.nodes, side === "source" ? query : "", focusIds);
  const visible = new Set<string>();
  const rows: Row[] = [];
  const walk = (node: Canonical, depth: number) => {
    if (!keep.has(node.node_id) || visible.has(node.node_id)) return;
    const childNodes = (children.get(node.node_id) || []).filter(child => keep.has(child.node_id));
    const isExpanded = expanded.has(node.node_id);
    visible.add(node.node_id);
    rows.push({...node, depth, hasChildren: childNodes.length > 0, expanded: isExpanded});
    if (isExpanded) childNodes.forEach(child => walk(child, depth + 1));
  };
  roots.forEach(root => walk(root, 0));
  const representative = new Map<string, string>();
  for (const node of nodes) {
    let current: Canonical | undefined = node;
    const seen = new Set<string>();
    while (current && !visible.has(current.node_id) && !seen.has(current.node_id)) {
      seen.add(current.node_id); current = current.parent_id ? byId.get(current.parent_id) : undefined;
    }
    if (current && visible.has(current.node_id)) representative.set(node.node_id, current.node_id);
  }
  return {rows, visible, representative, nodeIds: new Set(nodes.map(node => node.node_id)), roots};
}

function HierarchyRow({ data }: NodeProps<HierarchyNode>) {
  if (!data.node) return null;
  const node = data.node;
  const isBranch = data.hasChildren;
  return <div className={`trace-hierarchy-row ${data.side} ${data.selected ? "selected" : ""} ${isBranch ? "branch" : "leaf"}`} data-trace-node-id={node.node_id} data-trace-level={(data.depth || 0) + 1} title={`${title(node)}\n${node.node_id}`}>
    {data.side === "target" && <Handle type="target" position={Position.Left} isConnectable={false} />}
    <div className="trace-hierarchy-row-inner" style={{paddingLeft: 8 + (data.depth || 0) * 17, ["--trace-depth" as string]: data.depth || 0}}>
      {isBranch ? <button className="trace-hierarchy-toggle nodrag" type="button" aria-label={data.expanded ? "折叠" : "展开"} aria-expanded={data.expanded} onClick={event => {event.stopPropagation(); data.onToggle?.(node.node_id);}}>{data.expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}</button> : <i className="trace-hierarchy-dot" />}
      <span className="trace-hierarchy-kind"><FileText size={12} /></span><span className="trace-hierarchy-title">{title(node)}</span>
    </div>
    {data.side === "source" && <Handle type="source" position={Position.Right} isConnectable={false} />}
  </div>;
}
const nodeTypes = {hierarchyRow: HierarchyRow};

type LinkGroup = {source: string; target: string; relation: string; links: Link[]};
function projectLinks(graph: Visualization, sourceModel: SideModel, targetModel: SideModel, relation: string, targetArtifact: string) {
  const targetUnitArtifacts = new Map(graph.units.map(unit => [unit.node_id, unit.artifact_id]));
  const groups = new Map<string, LinkGroup>();
  for (const link of graph.links) {
    if (relation && link.relation !== relation) continue;
    if (targetArtifact && targetUnitArtifacts.get(link.target_node_id) !== targetArtifact) continue;
    const source = sourceModel.representative.get(link.source_node_id);
    const target = targetModel.representative.get(link.target_node_id);
    if (!source || !target) continue;
    const key = `${source}|${target}|${link.relation}`;
    const existing = groups.get(key);
    if (existing) existing.links.push(link);
    else groups.set(key, {source, target, relation: link.relation, links: [link]});
  }
  return [...groups.values()];
}

export function TraceDocumentHierarchy({graph, source, selected, artifact, targetArtifact, query, relation, expansion, onExpansion, onSource, onTarget, onQuery}: {
  graph: Visualization; source: string; selected: string; artifact: string; targetArtifact: string; query: string; relation: string;
  expansion?: TraceExpansion; onExpansion: (value: TraceExpansion) => void;
  onSource: (id: string) => void; onTarget: (id: string) => void; onQuery: (query: string) => void;
}) {
  const flowRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(960);
  const initial = useMemo(() => initialExpansion(graph, source, selected), [graph, source, selected]);
  const expanded = expansion || initial;
  // Selection only changes highlighting. Expansion belongs to the run in TracePage,
  // so filters, evidence reads and graph refreshes cannot overwrite the user's tree.
  useEffect(() => { if (!expansion) onExpansion(initial); }, [expansion, initial, onExpansion]);
  useEffect(() => {
    if (!flowRef.current) return;
    const observer = new ResizeObserver(entries => setWidth(Math.round(entries[0]?.contentRect.width || 960)));
    observer.observe(flowRef.current); return () => observer.disconnect();
  }, []);
  const linksBySource = useMemo(() => {
    const result = new Map<string, string[]>();
    for (const link of graph.links) result.set(link.source_node_id, [...(result.get(link.source_node_id) || []), link.target_node_id]);
    return result;
  }, [graph.links]);
  const focusSource = useMemo(() => new Set([source]), [source]);
  const focusTarget = useMemo(() => new Set((linksBySource.get(source) || []).concat(selected ? [selected] : [])), [linksBySource, source, selected]);
  const sourceNodes = useMemo(() => nodesForSide(graph, "source", artifact), [graph, artifact]);
  const targetNodes = useMemo(() => nodesForSide(graph, "target", targetArtifact), [graph, targetArtifact]);
  const levels = useMemo(() => ({source: levelsOf(sourceNodes), target: levelsOf(targetNodes)}), [sourceNodes, targetNodes]);
  const sourceModel = useMemo(() => sideModel(graph, "source", artifact, query, expanded.source, focusSource), [graph, artifact, query, expanded.source, focusSource]);
  const targetModel = useMemo(() => sideModel(graph, "target", targetArtifact, "", expanded.target, focusTarget), [graph, targetArtifact, expanded.target, focusTarget]);
  const projectedLinks = useMemo(() => projectLinks(graph, sourceModel, targetModel, relation, targetArtifact), [graph, sourceModel, targetModel, relation, targetArtifact]);
  const canvasWidth = Math.max(width, 760);
  const columnWidth = Math.max(270, Math.min(390, Math.floor((canvasWidth - 112) / 2)));
  const rowHeight = 34;
  const flowHeight = Math.max(300, Math.max(sourceModel.rows.length, targetModel.rows.length) * rowHeight + 40);
  const toggle = (side: Side, id: string) => {
    const next = new Set(expanded[side]);
    if (next.has(id)) next.delete(id); else next.add(id);
    onExpansion({...expanded, [side]: next});
  };
  const expandTo = (side: Side, level: number) => {
    const next = new Set(expanded[side]);
    for (const id of levels[side].levels.keys()) next.delete(id);
    for (const id of levels[side].branches) if ((levels[side].levels.get(id) || 1) < level) next.add(id);
    onExpansion({...expanded, [side]: next});
  };
  const levelControl = (side: Side) => {
    const {branches, levels: depths, max} = levels[side];
    const current = Array.from({length: max}, (_, i) => i + 1).find(level => [...branches].every(id => expanded[side].has(id) === ((depths.get(id) || 1) < level)));
    const label = side === "source" ? "需求" : "设计";
    return <div className="trace-level-control" role="group" aria-label={`${label}侧层级快捷键`} tabIndex={0} aria-keyshortcuts={Array.from({length: Math.min(max, 9)}, (_, i) => `Alt+${i + 1}`).join(" ")} title="焦点位于此侧工具区时，Alt + 1–9 展开至对应层；文档根为第 1 层" onKeyDown={event => {
      const target = event.target;
      if (!event.altKey || event.ctrlKey || event.metaKey || !/^[1-9]$/.test(event.key) || (target instanceof HTMLElement && target.closest("input, textarea, [contenteditable=true]"))) return;
      const level = Number(event.key);
      if (level > max) return;
      event.preventDefault(); expandTo(side, level);
    }}><span>{label}侧</span><Select aria-label={`${label}侧展开层级`} value={current || "custom"} onChange={value => { if (typeof value === "number") expandTo(side, value); }} options={[{value: "custom", label: "自定义展开", disabled: true}, ...Array.from({length: max}, (_, i) => ({value: i + 1, label: i === 0 ? "仅文档（第 1 层）" : i + 1 === max ? `全部展开（${max} 层）` : `展开至第 ${i + 1} 层`}))]} /></div>;
  };
  const nodes: HierarchyNode[] = [
    ...sourceModel.rows.map((node, index) => ({id: `source:${node.node_id}`, type: "hierarchyRow" as const, position: {x: 28, y: 18 + index * rowHeight}, style: {width: columnWidth}, data: {node, side: "source" as const, depth: node.depth, expanded: node.expanded, hasChildren: node.hasChildren, selected: node.node_id === source, onToggle: (id: string) => toggle("source", id)}})),
    ...targetModel.rows.map((node, index) => ({id: `target:${node.node_id}`, type: "hierarchyRow" as const, position: {x: canvasWidth - columnWidth - 28, y: 18 + index * rowHeight}, style: {width: columnWidth}, data: {node, side: "target" as const, depth: node.depth, expanded: node.expanded, hasChildren: node.hasChildren, selected: node.node_id === selected, onToggle: (id: string) => toggle("target", id)}})),
  ];
  const edges: Edge[] = projectedLinks.map((group, index) => {
    const active = group.links.some(link => link.source_node_id === source || link.target_node_id === selected);
    return {id: `projected:${index}:${group.source}:${group.target}`, source: `source:${group.source}`, target: `target:${group.target}`, type: "default", label: group.links.length > 1 ? `×${group.links.length}` : undefined, labelStyle: {fontSize: 10, fill: active ? "#3177e9" : "#9badc3"}, labelBgStyle: {fill: "#fff", fillOpacity: .9}, style: {stroke: active ? "#3d80ee" : "#aab8c9", strokeWidth: active ? 2.2 : 1.2, opacity: active || !source ? 1 : .22}};
  });
  const sourceArtifact = graph.artifacts.find(item => item.artifact_id === artifact) || graph.artifacts.find(item => sourceNodes[0]?.artifact_id === item.artifact_id);
  const targetArtifactItem = graph.artifacts.find(item => item.artifact_id === targetArtifact) || graph.artifacts.find(item => targetNodes[0]?.artifact_id === item.artifact_id);
  return <div className="trace-document-hierarchy" data-trace-visible-link-count={projectedLinks.reduce((sum, group) => sum + group.links.length, 0)} data-trace-aggregate-count={projectedLinks.length}>
    <div className="trace-hierarchy-headings"><div><FileText size={15} /><strong>{sourceArtifact?.filename || "需求文档"}</strong><span>{sourceModel.rows.length} 个可见层级节点</span></div><div><FileText size={15} /><strong>{targetArtifactItem?.filename || "设计文档"}</strong><span>{targetModel.rows.length} 个可见层级节点</span></div></div>
    <div className="trace-depth-toolbar">{levelControl("source")}<span className="trace-level-hint">文档根为第 1 层 · 焦点在该侧：Alt + 1–9</span>{levelControl("target")}</div>
    <div className="trace-hierarchy-toolbar"><Input aria-label="查找需求层级" placeholder="查找原文、章节或节点 ID" prefix={<Search size={14} />} value={query} onChange={event => onQuery(event.target.value)} allowClear /><span>{projectedLinks.reduce((sum, group) => sum + group.links.length, 0)} 条正式链接 · {projectedLinks.length} 个可见端点组</span></div>
    {!sourceModel.rows.length || !targetModel.rows.length ? <div className="graph-no-links"><NoData title="没有可显示的文档层级" detail="调整文档筛选或搜索条件后重试。" /></div> : <div ref={flowRef} className="trace-document-flow" style={{height: flowHeight}}><ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} nodesDraggable={false} nodesConnectable={false} elementsSelectable={false} panOnDrag={false} zoomOnScroll={false} zoomOnPinch={false} zoomOnDoubleClick={false} minZoom={1} maxZoom={1} defaultViewport={{x: 0, y: 0, zoom: 1}} onNodeClick={(_, node) => {const id = String(node.id).split(":").slice(1).join(":"); const side = String(node.id).startsWith("source:") ? "source" : "target"; if (side === "source") onSource(id); else onTarget(id);}} onEdgeClick={(_, edge) => {const group = projectedLinks.find((_, index) => edge.id === `projected:${index}:${_.source}:${_.target}`); const link = group?.links[0]; if (link) {onSource(link.source_node_id); onTarget(link.target_node_id);}}}><Background color="#e4ecf7" gap={22} size={1} /></ReactFlow></div>}
    <div className="hierarchy-legend"><span><i className="source-dot" />需求文档层级　<i className="target-dot" />设计文档层级</span><span>折叠后的链接连接到最近可见父节点；未选中需求的连线已淡化</span></div>
  </div>;
}
