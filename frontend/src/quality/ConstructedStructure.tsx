import { useMemo, useState } from "react";
import { HierarchyTree, type TreeItem } from "./HierarchyTree";
import { originalKey, unitKinds, type ConsistencyModel, type Role, type Unit } from "./consistencyModel";

const kinds = { semantic: "文档语义树", groups: "功能聚类结构", sections: "文档章节结构", project: "代码项目结构", syntax: "代码语法结构", match: "匹配分割结构" };
type StructureKind = keyof typeof kinds;
export function ConstructedStructure({ model, base }: { model: ConsistencyModel; base: string }) {
  const [role, setRole] = useState<Role>("source"), [selected, setSelected] = useState<StructureKind>("semantic");
  const units = [...model.units.values()].filter(u => u.role === role);
  const codeArtifacts = units.filter(u => u.type === "artifact" && ["code", "test_code"].includes(model.artifactMap.get(u.artifact)?.kind || ""));
  const available = (Object.keys(kinds) as StructureKind[]).filter(k => k === "project" ? codeArtifacts.length > 0 : units.some(u => u.family === k));
  const kind = available.includes(selected) ? selected : available[0];
  const nodes = useMemo(() => {
    const nodes = new Map<string, TreeItem>();
    const toNode = (u: Unit, parent = u.parent): TreeItem => ({ id: u.key, parent_id: parent, title: u.title, type: unitKinds[u.type] || u.type, href: `${base}/units/${encodeURIComponent(u.key)}` });
    const putRoot = (u: Unit) => { const root = model.units.get(originalKey(role, u.artifact)); if (root) nodes.set(root.key, toNode(root)); return root?.key; };
    if (kind === "project") {
      for (const u of codeArtifacts) {
        const a = model.artifactMap.get(u.artifact)!;
        // Only paths explicitly carried by the imported artifact are projected as folders.
        const path = a.structure?.path || a.locator;
        const valid = path && !path.includes("://") && !path.includes("#") && !path.includes("\\n");
        const parts = valid ? path.replace(/\\/g, "/").split("/").filter(Boolean) : [];
        let parent: string | undefined;
        for (let i = 0; i < parts.length - 1; i++) {
          const id = JSON.stringify([role, "directory", ...parts.slice(0, i + 1)]);
          nodes.set(id, { id, parent_id: parent, title: parts[i], type: "目录" }); parent = id;
        }
        nodes.set(u.key, { ...toNode(u, parent), note: parts.length ? path : "未提供可用项目路径" });
      }
    } else if (kind === "groups") {
      for (const u of units.filter(u => u.family === "groups")) nodes.set(u.key, toNode(u));
      for (const u of units.filter(u => u.family === "semantic")) for (const group of u.groups) {
        if (nodes.has(group)) { const node = toNode(u, group); node.id = JSON.stringify([group, u.key]); nodes.set(node.id, node); }
      }
    } else {
      const selectedUnits = units.filter(u => u.family === kind);
      const ids = new Set(selectedUnits.map(u => u.key));
      for (const u of selectedUnits) {
        const root = putRoot(u);
        nodes.set(u.key, toNode(u, u.parent && ids.has(u.parent) ? u.parent : root));
      }
    }
    return [...nodes.values()];
  }, [model, role, kind, base]);
  return <section className="qm-panel qm-inset"><div className="qm-toolbar">
    <label>展示层<select aria-label="构建结构展示层" value={role} onChange={e => setRole(e.target.value as Role)}><option value="source">上层（源工件）</option><option value="target">下层（目标工件）</option></select></label>
    <label>结构类型<select aria-label="构建结构类型" value={kind || ""} onChange={e => setSelected(e.target.value as StructureKind)}>{!available.length && <option value="">此层未保存结构</option>}{available.map(k => <option key={k} value={k}>{kinds[k]}</option>)}</select></label>
  </div><p className="qm-muted">一次展示一层的一种结构。{kind === "project" ? "代码项目结构按已导入路径展示目录与文件；函数和类请切换到代码语法结构。" : kind === "groups" ? "分类与成员归属来自已保存的功能聚类，同一单元可属于多个分类。" : "节点与父子关系来自已保存的对应结构，点击单元可查看详情。"}</p>
    <HierarchyTree key={role + kind} nodes={nodes} label="构建结构节点" empty="此层未保存可展示的结构" />
  </section>;
}
