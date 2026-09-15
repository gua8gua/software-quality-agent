import { useEffect, useMemo, useState } from "react";
import { all, errorText, get, getArtifactContent, type Artifact, type Run } from "./api";
import { Alert, Empty, Loading, Pager } from "./common";
import { buildModel, descendants, originalKey, unitKinds, unitRelations, type ConsistencyModel, type Outcome, type Report, type Unit } from "./consistencyModel";
import "./ConsistencyExplorer.css";
import { ConstructedStructure } from "./ConstructedStructure";

export const consistencyPath = (project: string, id: string) => `#/projects/${encodeURIComponent(project)}/consistency/${encodeURIComponent(id)}`;
const unitHref = (base: string, key: string) => `${base}/units/${encodeURIComponent(key)}`;
const defaults: Record<Outcome, string> = { implemented: "实现", missing_functionality: "缺失功能", conflict: "冲突", judgement_error: "判断出错" };
function statusFor(model: ConsistencyModel, unit: Unit, labels: Record<Outcome, string>) {
  if (unit.outcomes?.length) return unit.outcomes.map(o => labels[o]).join("、");
  const relations = unitRelations(model, unit), outcomes = [...new Set(relations.flatMap(r => r.part?.outcomes || []))];
  return outcomes.length ? outcomes.map(o => labels[o]).join("、") : relations.length ? "已匹配 · 待判断" : "尚无判定记录";
}
function UnitTable({ title, rows, model, labels, base }: { title: string; rows: Unit[]; model: ConsistencyModel; labels: Record<Outcome, string>; base: string }) {
  const [search, setSearch] = useState(""), [page, setPage] = useState(0);
  const filtered = rows.filter(u => `${u.title} ${u.id} ${u.artifact}`.toLowerCase().includes(search.toLowerCase()));
  const current = Math.min(page, Math.max(0, Math.ceil(filtered.length / 15) - 1));
  return <section className="surface qm-unit-list"><div className="qm-inset"><h2>{title} <small>{rows.length} 个单元</small></h2><input aria-label={`搜索${title}`} placeholder="搜索名称或标识…" value={search} onChange={e => { setSearch(e.target.value); setPage(0); }} /></div>
    {!filtered.length ? <Empty title={rows.length ? "没有匹配的单元" : "未保存此层结构"} /> : <><div className="table-wrap"><table className="data-table"><thead><tr><th>单元 / 类型</th><th>所属工件或父单元</th><th>判定情况</th></tr></thead><tbody>{filtered.slice(current * 15, (current + 1) * 15).map(u => <tr key={u.key}>
      <td><a className="qm-unit-title" href={unitHref(base, u.key)}>{u.title}</a><small>{unitKinds[u.type] || u.type}</small></td>
      <td>{u.parent && model.units.has(u.parent) ? <a className="qm-unit-title" href={unitHref(base, u.parent)}>{model.units.get(u.parent)!.title}</a> : u.artifact || "功能分类"}</td>
      <td>{statusFor(model, u, labels)}</td>
    </tr>)}</tbody></table></div><Pager page={current} size={15} total={filtered.length} set={setPage} /></>}
  </section>;
}
function UnitDetail({ unit, model, report, base, tenant, project, labels }: { unit: Unit; model: ConsistencyModel; report: Report; base: string; tenant: string; project: string; labels: Record<Outcome, string> }) {
  const [body, setBody] = useState<string | undefined>(unit.text), [error, setError] = useState("");
  const artifact = model.artifactMap.get(unit.artifact);
  useEffect(() => {
    setBody(unit.text); setError(""); if (unit.text !== undefined || !artifact) return;
    let active = true;
    getArtifactContent(artifact.id, tenant, project).then(a => { if (!active) return; if (!a.available || a.content === null) { setError(a.reason || "当前资料没有可用正文。"); return; } setBody(unit.type === "artifact" ? a.content : Array.from(a.content).slice(unit.start, unit.end).join("")); }).catch(e => { if (active) setError(errorText(e)); });
    return () => { active = false; };
  }, [unit, artifact, tenant, project]);
  const keys = descendants(model, unit);
  const children = [...model.units.values()].filter(u => u.parent === unit.key || (["category", "subcategory"].includes(unit.type) && u.type !== "artifact" && u.groups.includes(unit.key)));
  const relations = unitRelations(model, unit), judged = relations.filter(r => !r.matchingOnly), matched = relations.filter(r => r.matchingOnly);
  const [page, setPage] = useState(0), [matchPage, setMatchPage] = useState(0);
  const current = Math.min(page, Math.max(0, Math.ceil(judged.length / 15) - 1));
  const currentMatch = Math.min(matchPage, Math.max(0, Math.ceil(matched.length / 20) - 1));
  const sourceResult = unit.role === "source" && unit.type === "artifact" ? report.results.requirements[unit.artifact] : undefined;
  return <><a className="qm-back" href={`${base}/${unit.type === "artifact" ? "original" : "structure"}`}>返回{unit.type === "artifact" ? "原始工件" : "构建结构"}</a>
    <div className="qm-heading"><div><p>{unit.role === "source" ? "上层" : "下层"} · {unitKinds[unit.type] || unit.type}</p><h2 className="qm-unit-heading">{unit.title}</h2><p>{unit.id}</p></div></div>
    <section className="surface qm-inset"><h3>单元关系与判定</h3><dl className="qm-unit-meta"><dt>所属原始工件</dt><dd>{unit.artifact ? <a href={unitHref(base, originalKey(unit.role, unit.artifact))}>{model.units.get(originalKey(unit.role, unit.artifact))?.title || unit.artifact}</a> : "跨工件功能分类"}</dd>
      <dt>父单元</dt><dd>{unit.parent && model.units.has(unit.parent) ? <a href={unitHref(base, unit.parent)}>{model.units.get(unit.parent)!.title}</a> : "无父单元"}</dd>
      <dt>所属功能聚类</dt><dd>{unit.groups.length ? unit.groups.map(key => <a key={key} href={unitHref(base, key)}>{model.units.get(key)?.title || key} </a>) : "未保存功能聚类归属"}</dd>
      <dt>局部判定</dt><dd>{statusFor(model, unit, labels)}</dd>
      {unit.start !== undefined && <><dt>原文位置</dt><dd>字符 {unit.start}–{unit.end}（从 0 开始）</dd></>}
    </dl>
      {sourceResult && <><p>工件判定：{sourceResult.outcomes.map(o => labels[o]).join("、")}</p><p>{sourceResult.whole_requirement_implemented ? "静态分析支持本工件要求整体满足" : "尚不能确认本工件要求整体满足"}</p><p>{sourceResult.judgement?.summary}</p>{sourceResult.error && <Alert>{sourceResult.error}</Alert>}{!!sourceResult.analysis_errors?.length && <p>判断限制：{sourceResult.analysis_errors.join("；")}</p>}</>}
      {!!unit.conditions?.length && <p>继承条件：{unit.conditions.join("；")}</p>}
    </section>
    {unit.role === "source" && unit.type === "match" && unit.parent && <p>此匹配片段用于检索定位。<a href={unitHref(base, unit.parent)}>查看所属任务单元的完整判定</a></p>}
    <section className="surface qm-inset"><h3>{unit.artifact ? "单元原文" : "聚类说明"}</h3>{error ? <Alert>{error}</Alert> : body !== undefined ? <pre className="qm-unit-body">{body}</pre> : artifact ? <Loading /> : <p>历史记录未保存可读取的正文。</p>}</section>
    <UnitTable title={unit.type === "category" || unit.type === "subcategory" ? "下属分类与成员单元" : "直接子单元"} rows={children} model={model} labels={labels} base={base} />
    <section className="surface qm-inset"><h3>{unit.role === "source" ? "下层单元对各项任务的完成情况" : "此单元承担的上层任务"}</h3><p className="muted-text">展示本单元及其子单元的已有判定。每条内容记录的多段引文共同构成证据；局部“实现”不等于整条上层需求已完成。</p>
      {!judged.length ? <Empty title="尚无一致性判定记录"><p>{matched.length ? "已有匹配关联，尚不能据此认定任务完成。" : "尚未获得此范围的判定，不能据此认定功能缺失。"}</p></Empty> : <><div className="table-wrap"><table className="data-table"><thead><tr><th>上层任务 / 单元</th><th>下层单元</th><th>完成情况与依据</th></tr></thead><tbody>{judged.slice(current * 15, (current + 1) * 15).map(r => <tr key={r.key}>
        <td><a href={unitHref(base, r.source)}>{model.units.get(r.source)?.title || r.source}</a><blockquote>{r.part?.requirement_quote}</blockquote></td>
        <td>{r.target ? <a href={unitHref(base, r.target)}>{model.units.get(r.target)?.title || r.target}</a> : "未定位有效下层单元"}</td>
        <td><strong>{r.part?.outcomes.map(o => labels[o]).join("、")}</strong><p>{r.part?.implemented_behavior}</p><p>{r.part?.reason}</p>{r.part?.missing_behavior && <p>缺失行为：{r.part.missing_behavior}</p>}
          <details><summary>查看同组证据（{r.citations.length}）</summary>{r.citations.map((c, i) => <div key={i}><p>{c.locator || c.artifact_id} · 第 {c.start_line} 行</p><pre className="qm-unit-body">{c.quote}</pre></div>)}</details>
        </td>
      </tr>)}</tbody></table></div><Pager page={current} size={15} total={judged.length} set={setPage} /></>}
    </section>
    <section className="surface qm-inset"><h3>TLR 已确认匹配关系</h3><p className="muted-text">匹配关系表示相关性，完成情况以一致性判定为准。</p>{!matched.length ? <p>没有保存此单元范围的匹配关系。</p> : <><ul>{matched.slice(currentMatch * 20, (currentMatch + 1) * 20).map(r => <li key={r.key}><a href={unitHref(base, r.source)}>{model.units.get(r.source)?.title}</a> → {r.target && <a href={unitHref(base, r.target)}>{model.units.get(r.target)?.title}</a>}</li>)}</ul><Pager page={currentMatch} size={20} total={matched.length} set={setMatchPage} /></>}</section>
    {unit.role === "source" && unit.type !== "artifact" && !judged.length && report.results.requirements[unit.artifact] && <p>原工件已有结果，但未细化定位到此单元。<a href={unitHref(base, originalKey("source", unit.artifact))}>查看原工件判定</a></p>}
    <p className="muted-text">当前范围包含 {keys.size} 个单元。</p>
  </>;
}

export function ConsistencyExplorer({ report, tenant, project, view, unitId }: { report: Report; tenant: string; project: string; view: string; unitId?: string }) {
  const [artifacts, setArtifacts] = useState<Artifact[]>([]), [tlr, setTlr] = useState<Run | null>(null), [loading, setLoading] = useState(true), [error, setError] = useState("");
  useEffect(() => {
    let active = true; setLoading(true); setError("");
    async function load() {
      const run = await get<Run>(`/runs/${report.snapshot.tlr_run_id}`, tenant, project);
      const rows = await all<Artifact>(`/datasets/${report.snapshot.dataset_id || run.dataset_id}/inventory`, tenant, project);
      if (active) { setTlr(run); setArtifacts(rows); }
    }
    load().catch(e => { if (active) setError(errorText(e)); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [tenant, project, report.snapshot.tlr_run_id, report.snapshot.dataset_id]);
  const model = useMemo(() => buildModel(report, artifacts, tlr), [report, artifacts, tlr]);
  const base = consistencyPath(project, report.id), labels = report.outcome_dictionary || defaults;
  const selected = unitId && model.units.get(unitId);
  const structured = view === "structure";
  return <div className="qm-consistency-explorer"><nav className="qm-tabs" aria-label="一致性分析子页面"><a className={!structured && view !== "units" ? "active" : ""} aria-current={!structured && view !== "units" ? "page" : undefined} href={`${base}/original`}>原始工件</a><a className={structured ? "active" : ""} aria-current={structured ? "page" : undefined} href={`${base}/structure`}>构建结构</a></nav>
    {error ? <Alert>{error}</Alert> : loading ? <Loading /> : view === "units" ? selected ? <UnitDetail key={selected.key} unit={selected} model={model} report={report} base={base} tenant={tenant} project={project} labels={labels} /> : <Empty title="单元不存在或不属于此次分析" /> : <>
      <p className="muted-text">{structured ? "功能聚类、拆分单元、代码语法结构与匹配片段均来自此次分析保存的数据。点击单元查看父子关系及判定。" : "上层为本次分析的源工件，下层为目标工件。点击工件查看正文、拆分结构及双向任务对应。"}</p>
      {structured && !report.snapshot.requirement_structure && <p className="muted-text">历史分析的完整拆分树优先读取其辅助 TLR 保存的结构；未保存的结构不会重新推断。</p>}
      {structured ? <ConstructedStructure model={model} base={base} /> : <div className="qm-unit-columns">{(["source", "target"] as const).map(role => <UnitTable key={`${view}-${role}`} title={role === "source" ? "上层单元" : "下层单元"} rows={[...model.units.values()].filter(u => u.role === role && u.type === "artifact")} model={model} labels={labels} base={base} />)}</div>}
    </>}
  </div>;
}
