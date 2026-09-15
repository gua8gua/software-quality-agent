import { useMemo, useState } from "react";
import { Empty, Pager } from "./common";

export interface TreeItem { id: string; parent_id?: string | null; title: string; type: string; href?: string; note?: string }
function Branch({ node, children, trail, searching }: { node: TreeItem; children: Map<string, TreeItem[]>; trail: Set<string>; searching: boolean }) {
  const [open, setOpen] = useState(false);
  if (trail.has(node.id)) return <li>原关系存在循环，停止展开。</li>;
  const next = new Set([...trail, node.id]), rows = children.get(node.id) || [], expanded = searching || open;
  return <li><div className="qm-structure-node"><span>{rows.length ? <button aria-label={`${expanded ? "折叠" : "展开"} ${node.title}`} onClick={() => setOpen(v => !v)} disabled={searching}>{expanded ? "−" : "+"}</button> : "·"}</span>
    {node.href ? <a href={node.href}>{node.title}</a> : <strong>{node.title}</strong>}<span className="qm-type">{node.type}</span>{rows.length > 0 && <small>{rows.length} 个直接子节点</small>}{node.note && <small>{node.note}</small>}
  </div>{expanded && !!rows.length && <ul>{rows.map(child => <Branch key={child.id} node={child} children={children} trail={next} searching={searching} />)}</ul>}</li>;
}
export function HierarchyTree({ nodes, label = "结构节点", empty = "未保存此结构" }: { nodes: TreeItem[]; label?: string; empty?: string }) {
  const [search, setSearch] = useState(""), [page, setPage] = useState(0);
  const { roots, children, count } = useMemo(() => {
    const byId = new Map(nodes.map(n => [n.id, n])), shown = new Set<string>();
    for (const n of nodes) if (!search || `${n.title} ${n.type}`.toLowerCase().includes(search.toLowerCase())) {
      let current: TreeItem | undefined = n;
      while (current && !shown.has(current.id)) { shown.add(current.id); current = byId.get(current.parent_id || ""); }
    }
    const children = new Map<string, TreeItem[]>(), roots: TreeItem[] = [];
    for (const n of nodes) if (shown.has(n.id)) {
      if (!n.parent_id || !shown.has(n.parent_id)) roots.push(n);
      else children.set(n.parent_id, [...(children.get(n.parent_id) || []), n]);
    }
    if (!roots.length && shown.size) roots.push(nodes.find(n => shown.has(n.id))!);
    return { roots, children, count: shown.size };
  }, [nodes, search]);
  const current = Math.min(page, Math.max(0, Math.ceil(roots.length / 50) - 1));
  return <><div className="inline-controls qm-structure-tools"><input aria-label={`搜索${label}`} placeholder="搜索节点名称或类型…" value={search} onChange={e => { setSearch(e.target.value); setPage(0); }} /><span>{count} 个节点</span></div>
    {!roots.length ? <Empty title={search ? "没有匹配的节点" : empty} /> : <ul className="qm-structure-tree">{roots.slice(current * 50, (current + 1) * 50).map(n => <Branch key={n.id} node={n} children={children} trail={new Set()} searching={!!search} />)}</ul>}
    {roots.length > 50 && <Pager page={current} size={50} total={roots.length} set={setPage} />}
  </>;
}
