import type { Canonical } from "./api";

export function title(n?: Canonical) { return n ? n.title || n.preview || `${n.node_type} · ${n.node_id.slice(0, 8)}` : "节点未加载"; }
export function pathOf(n: Canonical, all: Canonical[]): string[] {
  const byId = new Map(all.map(item => [item.node_id, item])); const seen = new Set<string>(); const path: string[] = [];
  let parent = byId.get(n.parent_id || "");
  while (parent && !seen.has(parent.node_id)) { seen.add(parent.node_id); if (parent.title) path.unshift(parent.title); parent = byId.get(parent.parent_id || ""); }
  return path;
}
