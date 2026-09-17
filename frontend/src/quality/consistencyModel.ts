import type { Artifact, Run } from "./api";

export type Outcome = "implemented" | "missing_functionality" | "conflict" | "judgement_error";
export interface Part { requirement_quote: string; implemented_behavior: string; outcomes: Outcome[]; reason: string; unit_id?: string; missing_behavior?: string }
export interface Citation { artifact_id: string; locator: string; start_line: number; quote: string; artifact_start?: number }
export interface Result { outcomes: Outcome[]; whole_requirement_implemented: boolean; implementations: { citations: Citation[]; parts: Part[] }[]; analysis_errors?: string[]; error?: string; judgement?: { summary: string; missing_context: string[] } }
interface Membership { category: string; subcategory?: string; title: string; summary?: string }
interface StructureNode { id: string; parent_id?: string | null; kind?: string; title?: string; name?: string; normalized?: string; text?: string; start?: number; end?: number; categories?: Membership[]; children?: string[]; conditions?: string[]; state?: string }
interface Packet { requirement: { text: string; locator?: string }; requirement_units?: StructureNode[]; semantic_categories?: { categories?: { key: string; title: string; summary?: string; subcategories: { key: string; title: string; summary?: string }[] }[] } }
interface TlrElement { id: string; artifact_id: string; role: "source" | "target"; start: number; end: number; content: string; processing?: { unit_id?: string } }
export interface Report {
  analysis_kind?: "code" | "document"; document_relation?: string; outcome_dictionary?: Record<Outcome, string>;
  id: string; status: string; created_at: string;
  request?: { requirement_ids?: string[]; source_ids?: string[]; target_ids?: string[] };
  snapshot: {
    dataset_id?: string; tlr_run_id: string; tlr_partial?: boolean; target_ids?: string[];
    packets?: Record<string, Packet>; requirement_structure?: Record<string, { nodes: StructureNode[] }>;
    code_structure?: Record<string, { nodes: StructureNode[]; warnings?: string[] }>;
    document_structure?: Record<string, StructureNode[]>; tlr_elements?: TlrElement[];
    links?: { requirement_id: string; artifact_id: string; source_unit_id?: string; source_element_id?: string; element_id?: string; target_start?: number; target_end?: number }[];
  };
  results: { requirements: Record<string, Result>; error?: string };
  metrics: { selected_requirements: number; processed_requirements: number; outcome_counts: Partial<Record<Outcome, number>> };
}
export type Role = "source" | "target";
export interface Unit { key: string; id: string; role: Role; artifact: string; type: string; title: string; text?: string; parent?: string; groups: string[]; start?: number; end?: number; conditions?: string[]; state?: string; outcomes?: Outcome[]; family?: "semantic" | "syntax" | "sections" | "match" | "groups" }
export interface Relation { key: string; source: string; target?: string; part?: Part; citations: Citation[]; matchingOnly: boolean }
export const unitKey = (role: Role, type: string, artifact: string, id: string) => JSON.stringify([role, type, artifact, id]);
export const originalKey = (role: Role, id: string) => unitKey(role, "artifact", id, id);
export const unitKinds: Record<string, string> = { artifact: "原始工件", category: "功能聚类", subcategory: "功能子类", requirement: "需求根单元", section: "章节单元", document_section: "文档章节", unit: "拆分单元", residual: "未拆分片段", function: "函数 / 方法", constructor: "构造方法", class: "类", interface: "接口", file: "文件结构", match: "匹配片段" };

// Display projection of persisted LiSSA/TLR and consistency structures; no inferred obligations.
export function buildModel(report: Report, artifacts: Artifact[], tlr?: Run | null) {
  const units = new Map<string, Unit>(), relations: Relation[] = [];
  const sources = Object.keys(report.snapshot.packets || {});
  if (!sources.length) sources.push(...(report.request?.source_ids || report.request?.requirement_ids || Object.keys(report.results.requirements)));
  const targets = report.snapshot.target_ids || report.request?.target_ids || tlr?.config.target_ids || [];
  const artifactMap = new Map(artifacts.map(a => [a.external_id, a]));
  const savedHierarchy = tlr?.manifest.requirement_hierarchy as { requirements?: Record<string, { nodes: StructureNode[] }> } | undefined;
  const put = (unit: Unit) => { units.set(unit.key, unit); return unit.key; };
  const lookup = (role: Role, artifact: string, id?: string) => id ? [...units.values()].find(u => u.role === role && u.artifact === artifact && u.id === id && u.type !== "artifact")?.key : undefined;
  function group(m: Membership, sub = false) {
    const id = sub ? JSON.stringify([m.category, m.subcategory]) : m.category;
    const type = sub ? "subcategory" : "category", key = unitKey("source", type, "", id);
    if (!units.has(key)) put({ key, id, role: "source", artifact: "", type, family: "groups", title: sub ? m.title : m.category, text: m.summary, parent: sub ? group(m) : undefined, groups: [] });
    return key;
  }
  for (const role of ["source", "target"] as const) for (const id of role === "source" ? sources : targets) {
    const artifact = artifactMap.get(id), packet = report.snapshot.packets?.[id];
    const root = originalKey(role, id);
    put({ key: root, id, role, artifact: id, type: "artifact", title: artifact?.structure?.title || artifact?.structure?.original_id || id, text: role === "source" ? packet?.requirement.text : undefined, groups: [], outcomes: role === "source" ? report.results.requirements[id]?.outcomes : undefined });
    if (role === "source") for (const cat of packet?.semantic_categories?.categories || []) {
      const key = group({ category: cat.key, title: cat.title, summary: cat.summary }); units.get(key)!.title = cat.title;
      for (const sub of cat.subcategories) group({ category: cat.key, subcategory: sub.key, title: sub.title, summary: sub.summary }, true);
    }
    const semantic = role === "source" ? report.snapshot.requirement_structure?.[id]?.nodes || savedHierarchy?.requirements?.[id]?.nodes || packet?.requirement_units : undefined;
    const structures = [
      { family: "semantic" as const, nodes: semantic || [] },
      { family: "syntax" as const, nodes: report.snapshot.code_structure?.[id]?.nodes || [] },
      { family: "sections" as const, nodes: report.snapshot.document_structure?.[id] || [] },
    ].filter(s => s.nodes.length);
    structures.forEach(({ family, nodes }, index) => {
      const nodeKeys = new Map(nodes.map(n => [n.id, unitKey(role, index === 0 ? "structure" : family, id, n.id)]));
      for (const n of nodes) {
        const groups = (n.categories || []).map(m => group(m, !!m.subcategory));
        put({ key: nodeKeys.get(n.id)!, id: n.id, role, artifact: id, family, type: n.kind || "unit", title: n.title || n.name || n.normalized || n.text || n.id, text: n.text, start: n.start, end: n.end, parent: nodeKeys.get(n.parent_id || "") || root, groups, conditions: n.conditions, state: n.state });
        units.get(root)!.groups.push(...groups);
      }
    });
    units.get(root)!.groups = [...new Set(units.get(root)!.groups)];
  }
  function containing(role: Role, artifact: string, start?: number, end?: number) {
    if (start === undefined || end === undefined) return originalKey(role, artifact);
    const depth = (u: Unit) => { const seen = new Set<string>(); let parent = u.parent; while (parent && !seen.has(parent)) { seen.add(parent); parent = units.get(parent)?.parent; } return seen.size; };
    return [...units.values()].filter(u => u.role === role && u.artifact === artifact && u.type !== "match" && u.start !== undefined && u.end !== undefined && u.start <= start && u.end >= end).sort((a, b) => (a.end! - a.start!) - (b.end! - b.start!) || depth(b) - depth(a))[0]?.key || originalKey(role, artifact);
  }
  for (const e of report.snapshot.tlr_elements || []) {
    const root = originalKey(e.role, e.artifact_id); if (!units.has(root)) continue;
    const parent = lookup(e.role, e.artifact_id, e.processing?.unit_id) || containing(e.role, e.artifact_id, e.start, e.end);
    put({ key: unitKey(e.role, "match", e.artifact_id, e.id), id: e.id, role: e.role, artifact: e.artifact_id, type: "match", family: "match", title: `匹配片段 · 字符 ${e.start}–${e.end}`, text: e.content, start: e.start, end: e.end, parent, groups: units.get(parent)?.groups || [] });
  }
  for (const [sourceId, result] of Object.entries(report.results.requirements)) {
    result.implementations.forEach((record, ri) => record.parts.forEach((part, pi) => {
      const source = lookup("source", sourceId, part.unit_id) || originalKey("source", sourceId);
      const targetCitations = record.citations.filter(c => targets.includes(c.artifact_id));
      if (!targetCitations.length) relations.push({ key: `${sourceId}:${ri}:${pi}`, source, part, citations: record.citations, matchingOnly: false });
      targetCitations.forEach((citation, ci) => {
        const start = citation.artifact_start;
        relations.push({ key: `${sourceId}:${ri}:${pi}:${ci}`, source, target: containing("target", citation.artifact_id, start, start === undefined ? undefined : start + [...citation.quote].length), part, citations: record.citations, matchingOnly: false });
      });
    }));
  }
  (report.snapshot.links || []).forEach((link, i) => {
    const source = lookup("source", link.requirement_id, link.source_unit_id) || lookup("source", link.requirement_id, link.source_element_id) || originalKey("source", link.requirement_id);
    const target = lookup("target", link.artifact_id, link.element_id) || containing("target", link.artifact_id, link.target_start, link.target_end);
    if (units.has(source) && units.has(target)) relations.push({ key: `tlr:${i}`, source, target, citations: [], matchingOnly: true });
  });
  return { units, relations, sources, targets, artifactMap };
}
export type ConsistencyModel = ReturnType<typeof buildModel>;
export function descendants(model: ConsistencyModel, unit: Unit) {
  const keys = new Set([unit.key]);
  if (["category", "subcategory"].includes(unit.type)) {
    const groups = new Set([unit.key]);
    for (const u of model.units.values()) if (u.parent === unit.key) groups.add(u.key);
    for (const u of model.units.values()) if (u.type !== "artifact" && u.groups.some(g => groups.has(g))) keys.add(u.key);
  }
  let added = true;
  while (added) { added = false; for (const u of model.units.values()) if (u.parent && keys.has(u.parent) && !keys.has(u.key)) { keys.add(u.key); added = true; } }
  return keys;
}
export function unitRelations(model: ConsistencyModel, unit: Unit) {
  const keys = descendants(model, unit);
  return model.relations.filter(r => keys.has(unit.role === "source" ? r.source : r.target || "") || (unit.role === "target" && unit.type === "match" && r.citations.some(c => c.artifact_id === unit.artifact && c.artifact_start !== undefined && unit.start! < c.artifact_start + [...c.quote].length && c.artifact_start < unit.end!)));
}
