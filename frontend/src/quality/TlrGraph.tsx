import cytoscape, { type Core, type ElementDefinition, type Layouts } from "cytoscape";
import elk from "cytoscape-elk";
import { Expand, Minus, Plus, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type MutableRefObject } from "react";

import {
  type HierarchyNode,
  type Link,
  type ProjectionLink,
  type ProjectionNode,
  type Run,
  type Visualization,
} from "./api";
import "./TlrGraph.css";

cytoscape.use(elk);

type Side = "source" | "target";
type Viewport = { zoom: number; pan: { x: number; y: number } };
type Collapsed = Record<Side, Set<string>>;

const MIN_ZOOM = 0.25;
const MAX_ZOOM = 1.8;
const INITIAL_MIN_ZOOM = 0.58;

function browserProjection(data: Visualization, collapsed: Collapsed): Visualization["projection"] {
  const rows = new Map(data.hierarchy.map((node) => [node.id, node]));
  const children = new Map<string | null, HierarchyNode[]>();
  const artifactNodes = new Map<string, HierarchyNode>();
  for (const node of data.hierarchy) {
    const siblings = children.get(node.parent_id) || [];
    siblings.push(node);
    children.set(node.parent_id, siblings);
    if (node.artifact_id && !artifactNodes.has(node.artifact_id)) {
      artifactNodes.set(node.artifact_id, node);
    }
  }
  for (const siblings of children.values()) {
    siblings.sort((a, b) => a.ordinal - b.ordinal || a.node_key.localeCompare(b.node_key));
  }
  const selected: Record<Side, Set<string>> = { source: new Set(), target: new Set() };
  for (const node of data.projection.nodes) {
    if (node.artifact_id) selected[node.role].add(node.artifact_id);
  }
  const projectedNodes: ProjectionNode[] = [];
  const endpoint = new Map<string, string>();

  for (const role of ["source", "target"] as Side[]) {
    const included = new Set<string>();
    const canonical = new Map<string, string>();
    for (const artifactId of selected[role]) {
      const leaf = artifactNodes.get(artifactId);
      if (!leaf) continue;
      canonical.set(artifactId, leaf.id);
      let current: HierarchyNode | undefined = leaf;
      const seen = new Set<string>();
      while (current && !seen.has(current.id)) {
        seen.add(current.id);
        included.add(current.id);
        current = current.parent_id ? rows.get(current.parent_id) : undefined;
      }
    }
    const visible = new Set<string>();
    for (const identifier of included) {
      let current = rows.get(identifier)?.parent_id || null;
      const seen = new Set<string>();
      let hidden = false;
      while (current && !seen.has(current)) {
        seen.add(current);
        if (collapsed[role].has(current)) {
          hidden = true;
          break;
        }
        current = rows.get(current)?.parent_id || null;
      }
      if (!hidden) visible.add(identifier);
    }
    const descendants = new Map<string, Set<string>>();
    for (const [artifactId, identifier] of canonical) {
      let current: string | null = identifier;
      const seen = new Set<string>();
      while (current && included.has(current) && !seen.has(current)) {
        seen.add(current);
        const values = descendants.get(current) || new Set<string>();
        values.add(artifactId);
        descendants.set(current, values);
        current = rows.get(current)?.parent_id || null;
      }
      current = identifier;
      seen.clear();
      while (current && !seen.has(current)) {
        seen.add(current);
        if (visible.has(current)) {
          endpoint.set(`${role}:${artifactId}`, `${role}:${current}`);
          break;
        }
        current = rows.get(current)?.parent_id || null;
      }
    }
    const ordered = [...visible]
      .map((identifier) => rows.get(identifier)!)
      .sort((a, b) => a.ordinal - b.ordinal || a.node_key.localeCompare(b.node_key));
    for (const node of ordered) {
      projectedNodes.push({
        ...node,
        id: `${role}:${node.id}`,
        hierarchy_node_id: node.id,
        parent_id:
          node.parent_id && visible.has(node.parent_id) ? `${role}:${node.parent_id}` : null,
        role,
        pure_structure: !node.artifact_id,
        collapsed: collapsed[role].has(node.id),
        has_children: (children.get(node.id) || []).some((child) => included.has(child.id)),
        descendant_artifact_count: descendants.get(node.id)?.size || 0,
        related_link_count: 0,
      });
    }
  }

  const groups = new Map<string, { source: string; target: string; links: Link[] }>();
  for (const link of data.links) {
    const source = endpoint.get(`source:${link.source_artifact_id}`);
    const target = endpoint.get(`target:${link.target_artifact_id}`);
    if (!source || !target) continue;
    const key = `${source}|${target}`;
    const group = groups.get(key) || { source, target, links: [] };
    group.links.push(link);
    groups.set(key, group);
  }
  const counts = new Map<string, number>();
  const projectedLinks: ProjectionLink[] = [...groups.values()].map((group) => {
    counts.set(group.source, (counts.get(group.source) || 0) + group.links.length);
    counts.set(group.target, (counts.get(group.target) || 0) + group.links.length);
    return {
      id: `projected:${group.source}:${group.target}`,
      source: group.source,
      target: group.target,
      count: group.links.length,
      underlying_link_ids: group.links.map((link) => link.id),
      links: group.links,
    };
  });
  for (const node of projectedNodes) node.related_link_count = counts.get(node.id) || 0;
  return { nodes: projectedNodes, links: projectedLinks };
}

function nodeWidth(node: ProjectionNode) {
  const suffix = node.collapsed ? " · 999 制品 / 999 关系" : "";
  return Math.max(168, Math.min(280, 36 + (node.title.length + suffix.length) * 11));
}

function elementsFor(projection: Visualization["projection"]): ElementDefinition[] {
  const nodes: ElementDefinition[] = projection.nodes.map((node) => ({
    classes: `graph-node${node.pure_structure ? " pure-structure" : ""}${
      node.has_children ? " collapsible" : ""
    }`,
    data: {
      ...node,
      label: `${node.collapsed ? "＋ " : ""}${node.title}${
        node.pure_structure ? "〔结构〕" : ""
      }${
        node.collapsed
          ? ` · ${node.descendant_artifact_count} 制品 / ${node.related_link_count} 关系`
          : ""
      }`,
      node_width: nodeWidth(node),
    },
  }));
  const hierarchyEdges: ElementDefinition[] = projection.nodes
    .filter((node) => node.parent_id)
    .map((node) => ({
      data: {
        id: `tree:${node.id}`,
        source: node.parent_id!,
        target: node.id,
        kind: "hierarchy",
        role: node.role,
      },
    }));
  const anchors: ElementDefinition[] = (["source", "target"] as Side[]).flatMap((role) => {
    const roots = projection.nodes.filter((node) => node.role === role && !node.parent_id);
    if (!roots.length) return [];
    return [
      { classes: "layout-anchor", data: { id: `layout-anchor:${role}`, role, layout_only: true, label: "" } },
      ...roots.map((root) => ({
        classes: "layout-anchor",
        data: {
          id: `layout-anchor-edge:${role}:${root.id}`,
          source: `layout-anchor:${role}`,
          target: root.id,
          kind: "layout-anchor",
          role,
        },
      })),
    ];
  });
  const links: ElementDefinition[] = projection.links.map((edge) => ({
    data: {
      ...edge,
      kind: "tlr",
      label: edge.count > 1 ? `${edge.count} 条关系` : "",
    },
  }));
  return [...nodes, ...hierarchyEdges, ...anchors, ...links];
}

function syncElements(cy: Core, desired: ElementDefinition[]) {
  const desiredIds = new Set(desired.map((element) => String(element.data.id)));
  cy.batch(() => {
    cy.elements().forEach((element) => {
      if (!desiredIds.has(element.id())) element.remove();
    });
    for (const definition of desired) {
      const existing = cy.getElementById(String(definition.data.id));
      if (existing.length) existing.data(definition.data);
      else cy.add(definition);
    }
  });
}

function runElk(cy: Core, role: Side, layouts: MutableRefObject<Layouts[]>) {
  const collection = cy.$(
    `node[role = "${role}"], edge[role = "${role}"][kind != "tlr"]`,
  );
  if (!collection.nodes().length) return Promise.resolve();
  return new Promise<void>((resolve) => {
    const layout = collection.layout({
      name: "elk",
      fit: false,
      animate: false,
      nodeDimensionsIncludeLabels: true,
      elk: {
        algorithm: "layered",
        "elk.direction": role === "source" ? "RIGHT" : "LEFT",
        "elk.edgeRouting": "ORTHOGONAL",
        "elk.spacing.nodeNode": "34",
        "elk.layered.spacing.nodeNodeBetweenLayers": "92",
        "elk.layered.spacing.edgeNodeBetweenLayers": "28",
        "elk.layered.crossingMinimization.strategy": "LAYER_SWEEP",
        "elk.layered.nodePlacement.strategy": "NETWORK_SIMPLEX",
        "elk.layered.nodePlacement.favorStraightEdges": "true",
        "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
      },
      stop: resolve,
    } as unknown as cytoscape.LayoutOptions);
    layouts.current.push(layout);
    layout.run();
  });
}

function placePartitions(cy: Core, containerWidth: number) {
  const source = cy.nodes('node.graph-node[role = "source"]');
  const target = cy.nodes('node.graph-node[role = "target"]');
  if (!source.length || !target.length) return;
  const sourceBox = source.boundingBox({ includeLabels: true, includeOverlays: false });
  const targetBox = target.boundingBox({ includeLabels: true, includeOverlays: false });
  const height = Math.max(sourceBox.h, targetBox.h);
  const gutter = Math.max(320, Math.min(520, containerWidth * 0.34));
  source.shift({ x: -sourceBox.x1, y: (height - sourceBox.h) / 2 - sourceBox.y1 });
  target.shift({
    x: sourceBox.w + gutter - targetBox.x1,
    y: (height - targetBox.h) / 2 - targetBox.y1,
  });
}

function initialViewport(cy: Core) {
  const visible = cy.nodes("node.graph-node");
  if (!visible.length) return;
  cy.fit(visible, 52);
  const fitted = cy.zoom();
  const level = Math.min(1, Math.max(INITIAL_MIN_ZOOM, fitted));
  if (level !== fitted) {
    const box = visible.boundingBox({ includeLabels: true, includeOverlays: false });
    cy.zoom({ level, position: { x: box.x1 + box.w / 2, y: box.y1 + box.h / 2 } });
  }
}

function constrainPan(cy: Core, container: HTMLElement) {
  const nodes = cy.nodes("node.graph-node");
  if (!nodes.length) return;
  const box = nodes.boundingBox({ includeLabels: true, includeOverlays: false });
  const zoom = cy.zoom();
  const margin = 72;
  const current = cy.pan();
  const minX = container.clientWidth - margin - box.x2 * zoom;
  const maxX = margin - box.x1 * zoom;
  const minY = container.clientHeight - margin - box.y2 * zoom;
  const maxY = margin - box.y1 * zoom;
  cy.pan({
    x: Math.max(Math.min(minX, maxX), Math.min(Math.max(minX, maxX), current.x)),
    y: Math.max(Math.min(minY, maxY), Math.min(Math.max(minY, maxY), current.y)),
  });
}

interface Props {
  run: Run;
  data: Visualization;
  onCandidate: (id: string) => void;
  onArtifact: (id: string) => void;
  onLinks: (edge: ProjectionLink) => void;
}

export function TlrGraph({
  run,
  data,
  onCandidate,
  onArtifact,
  onLinks,
}: Props) {
  const container = useRef<HTMLDivElement>(null);
  const graph = useRef<Core | null>(null);
  const layouts = useRef<Layouts[]>([]);
  const layoutGeneration = useRef(0);
  const layoutTask = useRef<Promise<void> | null>(null);
  const initialViewportSet = useRef(false);
  const runId = useRef(run.id);
  const collapsed = useRef<Record<Side, Set<string>>>({
    source: new Set(),
    target: new Set(),
  });
  const projectionRef = useRef(data.projection);
  const callbacks = useRef({ onCandidate, onArtifact, onLinks });
  const toggleRef = useRef<(role: Side, id: string) => void>(() => undefined);
  const [projection, setProjection] = useState(() => browserProjection(data, collapsed.current));

  callbacks.current = { onCandidate, onArtifact, onLinks };
  projectionRef.current = projection;

  const toggle = useCallback(
    (role: Side, id: string) => {
      const next = new Set(collapsed.current[role]);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      collapsed.current = { ...collapsed.current, [role]: next };
      setProjection(browserProjection(data, collapsed.current));
    },
    [data],
  );
  toggleRef.current = (role, id) => void toggle(role, id);

  useEffect(() => {
    if (runId.current !== run.id) {
      runId.current = run.id;
      collapsed.current = { source: new Set(), target: new Set() };
      initialViewportSet.current = false;
      setProjection(browserProjection(data, collapsed.current));
      return;
    }
    setProjection(browserProjection(data, collapsed.current));
  }, [data.projection, run.id]);

  useEffect(() => {
    if (!container.current) return;
    const cy = cytoscape({
      container: container.current,
      elements: [],
      layout: { name: "preset", fit: false },
      minZoom: MIN_ZOOM,
      maxZoom: MAX_ZOOM,
      userZoomingEnabled: false,
      userPanningEnabled: true,
      boxSelectionEnabled: false,
      autoungrabify: true,
      autounselectify: true,
      style: [
        {
          selector: "node.graph-node",
          style: {
            label: "data(label)",
            width: "data(node_width)",
            height: 42,
            "background-color": "#e2eaf9",
            "border-width": 1,
            "border-color": "#9eb6dc",
            color: "#213b66",
            shape: "round-rectangle",
            "font-size": 11,
            "text-valign": "center",
            "text-halign": "center",
            "text-max-width": "260px",
            "text-wrap": "ellipsis",
          },
        },
        {
          selector: 'node.graph-node[role = "target"]',
          style: {
            "background-color": "#e3f3ed",
            "border-color": "#91c3b1",
            color: "#205b49",
          },
        },
        {
          selector: "node.pure-structure",
          style: { "border-style": "dashed", "background-color": "#f4f6f8" },
        },
        {
          selector: "node.collapsible",
          style: { "border-width": 2 },
        },
        {
          selector: ".layout-anchor",
          style: { opacity: 0, width: 1, height: 1 },
        },
        {
          selector: 'edge[kind = "hierarchy"]',
          style: {
            "curve-style": "taxi",
            width: 1,
            "line-color": "#cbd5e1",
            "target-arrow-shape": "none",
            opacity: 0.72,
          },
        },
        {
          selector: 'edge[kind = "hierarchy"][role = "source"]',
          style: { "taxi-direction": "rightward" },
        },
        {
          selector: 'edge[kind = "hierarchy"][role = "target"]',
          style: { "taxi-direction": "leftward" },
        },
        {
          selector: 'edge[kind = "tlr"]',
          style: {
            label: "data(label)",
            "font-size": 10,
            "text-background-color": "#fff",
            "text-background-opacity": 0.92,
            "text-background-padding": "3px",
            "curve-style": "bezier",
            "target-arrow-shape": "triangle",
            width: 2.2,
            "line-color": "#506f98",
            "target-arrow-color": "#506f98",
            opacity: 0.82,
          },
        },
      ],
    });
    graph.current = cy;
    cy.on("tap", 'edge[kind = "tlr"]', (event) => {
      const edge = projectionRef.current.links.find((item) => item.id === event.target.id());
      if (!edge) return;
      const candidate = edge.links[0]?.evidence_candidate_ids[0];
      if (edge.count === 1 && candidate) callbacks.current.onCandidate(candidate);
      else callbacks.current.onLinks(edge);
    });
    cy.on("tap", "node.graph-node", (event) => {
      const node = projectionRef.current.nodes.find((item) => item.id === event.target.id());
      if (!node) return;
      if (node.has_children) toggleRef.current(node.role, node.hierarchy_node_id);
    });
    cy.on("cxttap", "node[artifact_id]", (event) => {
      const artifactId = event.target.data("artifact_id");
      if (artifactId) callbacks.current.onArtifact(artifactId);
    });
    let constrainingViewport = false;
    cy.on("pan zoom", () => {
      if (constrainingViewport || !container.current) return;
      constrainingViewport = true;
      constrainPan(cy, container.current);
      constrainingViewport = false;
    });
    const observer = new ResizeObserver(() => cy.resize());
    observer.observe(container.current);
    return () => {
      observer.disconnect();
      ++layoutGeneration.current;
      cy.removeAllListeners();
      cy.unmount();
      const pending = layoutTask.current;
      if (pending) {
        // ELK uses an async worker. Keep its renderer detached until the worker settles so
        // destroying an old StrictMode instance cannot clear the new instance's container.
        cy.mount(document.createElement("div"));
        void pending.finally(() => cy.destroy());
      }
      else cy.destroy();
      graph.current = null;
    };
  }, []);

  useEffect(() => {
    const cy = graph.current;
    if (!cy) return;
    const generation = ++layoutGeneration.current;
    layouts.current.forEach((layout) => layout.stop());
    layouts.current = [];
    const viewport: Viewport = { zoom: cy.zoom(), pan: { ...cy.pan() } };
    syncElements(cy, elementsFor(projection));
    // Nodes are locked against user movement after each layout. Temporarily unlock them so
    // ELK can recompute every remaining node after an expand/collapse projection change.
    cy.nodes().unlock();
    if (container.current) container.current.dataset.layoutReady = "false";
    const task = (async () => {
      await runElk(cy, "source", layouts);
      if (generation !== layoutGeneration.current) return;
      await runElk(cy, "target", layouts);
      if (generation !== layoutGeneration.current) return;
      placePartitions(cy, container.current?.clientWidth || 1000);
      cy.nodes().lock();
      if (!initialViewportSet.current) {
        initialViewport(cy);
        initialViewportSet.current = true;
      } else {
        cy.viewport(viewport);
      }
      if (container.current) constrainPan(cy, container.current);
      if (container.current) container.current.dataset.layoutReady = "true";
    })();
    layoutTask.current = task;
  }, [projection]);

  const zoomBy = (factor: number) => {
    const cy = graph.current;
    if (!cy) return;
    cy.zoom(Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, cy.zoom() * factor)));
  };
  const reset = () => {
    const cy = graph.current;
    if (!cy) return;
    cy.zoom(1);
    cy.center(cy.nodes("node.graph-node"));
  };
  const fit = () => {
    const cy = graph.current;
    if (cy) cy.fit(cy.nodes("node.graph-node"), 45);
  };

  return (
    <div className="qm-graph-wrap">
      <div className="qm-graph-tools">
        <span>
          <i className="qm-dot source" />源层级
          <i className="qm-dot target" />目标层级
          <em>中央为 TLR Link 区域</em>
        </span>
        <button type="button" onClick={fit} title="适应视图" aria-label="适应视图">
          <Expand size={16} />
        </button>
        <button type="button" onClick={() => zoomBy(1.2)} aria-label="放大">
          <Plus size={16} />
        </button>
        <button type="button" onClick={() => zoomBy(1 / 1.2)} aria-label="缩小">
          <Minus size={16} />
        </button>
        <button type="button" onClick={reset} title="重置为 100%" aria-label="重置为 100%">
          <RotateCcw size={15} />100%
        </button>
      </div>
      <div className="qm-graph" ref={container} aria-label="分层的双侧 TLR Artifact 关系图" />
      <div className="qm-graph-note">
        左键仅用于展开/折叠有子节点的节点；右键或长按有正文节点进入详情。投影、聚合和剩余节点重排均在浏览器内完成。
      </div>
    </div>
  );
}
