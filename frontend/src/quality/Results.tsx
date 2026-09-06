import cytoscape from "cytoscape";
import { useEffect, useMemo, useRef, useState } from "react";
import { Expand, Minus, Plus, Download } from "lucide-react";
import { type Artifact, type Candidate, type Evidence, type Run, type Visualization, decisionLabel, get, errorText } from "./api";
import { Alert, Empty, Loading, Modal, Pager } from "./common";

function Graph({ run, data, artifacts, onCandidate, onArtifact }: { run: Run; data: Visualization; artifacts: Artifact[]; onCandidate: (id: string) => void; onArtifact: (id: string) => void }) {
  const container = useRef<HTMLDivElement>(null), graph = useRef<cytoscape.Core | null>(null);
  const callbacks = useRef({ onCandidate, onArtifact }); callbacks.current = { onCandidate, onArtifact };
  const visible = useMemo(() => artifacts.filter(a => run.config.source_ids.includes(a.external_id) || run.config.target_ids.includes(a.external_id)).slice(0, 200), [artifacts, run.config]);
  const visibleIds = useMemo(() => new Set(visible.map(a => a.id)), [visible]);
  useEffect(() => {
    let sourceIndex = 0, targetIndex = 0;
    const cy = cytoscape({ container: container.current!, elements: [
      ...visible.map(a => { const source = run.config.source_ids.includes(a.external_id); return { data: { id: a.id, label: a.external_id, role: source ? "source" : "target" }, position: { x: source ? 100 : 580, y: 60 * (source ? sourceIndex++ : targetIndex++) } }; }),
      ...data.links.filter(link => visibleIds.has(link.source_artifact_id) && visibleIds.has(link.target_artifact_id)).map(link => ({ data: { id: link.id, source: link.source_artifact_id, target: link.target_artifact_id, candidate: link.evidence_candidate_ids[0] } })),
    ], layout: { name: "preset", padding: 38 }, minZoom: 0.04, maxZoom: 3, wheelSensitivity: 0.2,
      style: [
        { selector: "node", style: { label: "data(label)", "background-color": "#e2eaf9", "border-width": 1, "border-color": "#bdcdeb", color: "#213b66", shape: "round-rectangle", width: 150, height: 34, "font-size": 11, "text-valign": "center", "text-halign": "center", "text-max-width": "140px", "text-wrap": "ellipsis" } },
        { selector: 'node[role="target"]', style: { "background-color": "#e3f3ed", "border-color": "#b8dace", color: "#205b49" } },
        { selector: "edge", style: { "curve-style": "bezier", "target-arrow-shape": "triangle", width: 1.4, "line-color": "#91a5bc", "target-arrow-color": "#91a5bc", opacity: 0.65 } },
        { selector: ":selected", style: { "border-width": 3, "border-color": "#2563eb", "line-color": "#2563eb", "target-arrow-color": "#2563eb", opacity: 1 } },
      ],
    });
    graph.current = cy;
    cy.on("tap", "edge", event => { const id = event.target.data("candidate"); if (id) callbacks.current.onCandidate(id); });
    cy.on("tap", "node", event => callbacks.current.onArtifact(event.target.id()));
    const observer = new ResizeObserver(() => { cy.resize(); }); observer.observe(container.current!);
    return () => { observer.disconnect(); cy.destroy(); graph.current = null; };
  }, [visible, visibleIds, data.links, run.config]);
  return <div className="qm-graph-wrap"><div className="qm-graph-tools"><span><i className="qm-dot source" />源资料 <i className="qm-dot target" />目标资料</span><button onClick={() => graph.current?.fit(undefined, 35)} title="适应画布" aria-label="适应画布"><Expand size={16} /></button><button onClick={() => { const cy = graph.current; if (cy) cy.zoom(cy.zoom() * 1.3); }} aria-label="放大"><Plus size={16} /></button><button onClick={() => { const cy = graph.current; if (cy) cy.zoom(cy.zoom() / 1.3); }} aria-label="缩小"><Minus size={16} /></button></div><div className="qm-graph" ref={container} aria-label="TLR 制品关系图；也可通过矩阵和候选列表查看" />
    <div className="qm-graph-note">点击制品查看原文，点击连线查看证据。连线仅表示已聚合的正向链接。{run.config.source_ids.length + run.config.target_ids.length > 200 && " 图中仅显示前 200 个制品，完整数据请查看矩阵或导出。"}</div></div>;
}

export function Results({ tenant, project, run, data, artifacts, onArtifact }: { tenant: string; project: string; run: Run; data: Visualization; artifacts: Artifact[]; onArtifact: (id: string) => void }) {
  const [tab, setTab] = useState("graph"), [candidateId, setCandidateId] = useState("");
  const [decision, setDecision] = useState("all"), [search, setSearch] = useState("");
  const [page, setPage] = useState(0), [sourcePage, setSourcePage] = useState(0), [targetPage, setTargetPage] = useState(0);
  const elements = useMemo(() => new Map(data.elements.map(e => [e.id, e])), [data.elements]);
  const pairs = useMemo(() => {
    const values = new Map<string, Candidate[]>();
    for (const candidate of data.candidates) {
      const s = elements.get(candidate.source_element_id), t = elements.get(candidate.target_element_id); if (!s || !t) continue;
      const key = `${s.artifact_id}|${t.artifact_id}`; const rows = values.get(key) || []; rows.push(candidate); values.set(key, rows);
    } return values;
  }, [data.candidates, elements]);
  const links = useMemo(() => new Set(data.links.map(link => `${link.source_artifact_id}|${link.target_artifact_id}`)), [data.links]);
  const sources = artifacts.filter(a => run.config.source_ids.includes(a.external_id));
  const targets = artifacts.filter(a => run.config.target_ids.includes(a.external_id));
  const filtered = data.candidates.filter(candidate => (decision === "all" || candidate.decision === decision) && `${elements.get(candidate.source_element_id)?.external_id} ${elements.get(candidate.target_element_id)?.external_id}`.toLowerCase().includes(search.toLowerCase()));
  function exportResults() {
    const blob = new Blob([JSON.stringify({ run, artifacts, ...data }, null, 2)], { type: "application/json" }); const href = URL.createObjectURL(blob); const a = document.createElement("a"); a.href = href; a.download = `tlr-${run.id}.json`; a.click(); setTimeout(() => URL.revokeObjectURL(href), 1000);
  }
  return <section className="qm-panel"><div className="qm-panel-head"><div className="qm-tabs" role="tablist" aria-label="TLR 结果展示"><button role="tab" aria-selected={tab === "graph"} onClick={() => setTab("graph")}>关系图</button><button role="tab" aria-selected={tab === "matrix"} onClick={() => setTab("matrix")}>追踪矩阵</button><button role="tab" aria-selected={tab === "candidates"} onClick={() => setTab("candidates")}>候选与判定 <span>{data.candidates.length}</span></button></div><button onClick={exportResults}><Download size={15} />导出结果 JSON</button></div>
    {tab === "graph" && (artifacts.length ? <Graph run={run} data={data} artifacts={artifacts} onCandidate={setCandidateId} onArtifact={onArtifact} /> : <Empty title="暂无可展示的制品" />)}
    {tab === "matrix" && <><div className="qm-matrix-legend"><span className="positive">● 最终链接</span><span>○ 无关联判定</span><span>… 尚未完成 / 未汇总</span><span>— 未进入候选集合</span></div><div className="qm-table-wrap"><table className="qm-matrix"><thead><tr><th>源资料 ↓ / 目标 →</th>{targets.slice(targetPage * 12, (targetPage + 1) * 12).map(t => <th key={t.id}><button onClick={() => onArtifact(t.id)}>{t.external_id}</button></th>)}</tr></thead><tbody>{sources.slice(sourcePage * 15, (sourcePage + 1) * 15).map(s => <tr key={s.id}><th><button onClick={() => onArtifact(s.id)}>{s.external_id}</button></th>{targets.slice(targetPage * 12, (targetPage + 1) * 12).map(t => {
      const key = `${s.id}|${t.id}`, candidates = pairs.get(key) || [], positive = links.has(key);
      const pending = candidates.some(c => c.decision !== "unrelated");
      const label = positive ? "最终链接" : !candidates.length ? "未进入候选集合" : pending ? "尚未完成或尚未汇总" : "候选全部判定无关联";
      return <td key={t.id} className={positive ? "positive" : ""}><button disabled={!candidates.length} title={`${s.external_id} → ${t.external_id}：${label}`} aria-label={`${s.external_id} → ${t.external_id}：${label}`} onClick={() => setCandidateId((candidates.find(c => c.decision === "related") || candidates[0]).id)}>{positive ? "●" : !candidates.length ? "—" : pending ? "…" : "○"}</button></td>;
    })}</tr>)}</tbody></table></div><div className="qm-matrix-pages"><div><strong>源资料</strong><Pager page={sourcePage} total={sources.length} size={15} set={setSourcePage} /></div><div><strong>目标资料</strong><Pager page={targetPage} total={targets.length} size={12} set={setTargetPage} /></div></div></>}
    {tab === "candidates" && <><div className="qm-toolbar qm-inset"><input aria-label="搜索候选制品" value={search} placeholder="搜索源或目标制品…" onChange={e => { setSearch(e.target.value); setPage(0); }} /><select aria-label="筛选判定" value={decision} onChange={e => { setDecision(e.target.value); setPage(0); }}><option value="all">全部判定</option>{Object.entries(decisionLabel).map(([id, label]) => <option value={id} key={id}>{label}</option>)}</select></div><div className="qm-table-wrap"><table><thead><tr><th>源制品</th><th>目标制品</th><th>候选排名</th><th>余弦相似度</th><th>判定</th><th /></tr></thead><tbody>{filtered.slice(page * 20, (page + 1) * 20).map(c => <tr key={c.id}><td>{elements.get(c.source_element_id)?.external_id}</td><td>{elements.get(c.target_element_id)?.external_id}</td><td>{c.rank}</td><td className="qm-mono">{c.similarity.toFixed(4)}</td><td><span className={`qm-badge ${c.decision}`}>{decisionLabel[c.decision]}</span></td><td><button onClick={() => setCandidateId(c.id)}>查看证据</button></td></tr>)}</tbody></table></div>{!filtered.length && <Empty title="没有匹配的候选记录" />}<Pager page={page} total={filtered.length} size={20} set={setPage} /></>}
    <p className="qm-footnote">追踪关系不等于功能正确或测试已覆盖；余弦相似度不是链接置信概率。</p>
    {candidateId && <EvidenceDialog tenant={tenant} project={project} run={run.id} id={candidateId} close={() => setCandidateId("")} onArtifact={onArtifact} />}
  </section>;
}

function EvidenceDialog({ tenant, project, run, id, close, onArtifact }: { tenant: string; project: string; run: string; id: string; close: () => void; onArtifact: (id: string) => void }) {
  const [data, setData] = useState<Evidence | null>(null), [error, setError] = useState("");
  useEffect(() => { let active = true; get<Evidence>(`/runs/${run}/candidates/${id}`, tenant, project).then(result => { if (active) setData(result); }).catch(e => { if (active) setError(errorText(e)); }); return () => { active = false; }; }, [tenant, project, run, id]);
  return <Modal title="候选判定与原文证据" close={close} wide>{error ? <Alert>{error}</Alert> : !data ? <Loading /> : <><div className="qm-toolbar qm-inset"><span className={`qm-badge ${data.candidate.decision}`}>{decisionLabel[data.candidate.decision]}</span><span>余弦相似度 {data.candidate.similarity.toFixed(4)}</span></div><p className="qm-evidence-summary">{data.candidate.evidence?.evidence || (data.candidate.evidence?.validation_status === "invalid" ? "模型返回格式或引文校验失败，未形成有效判定。" : "尚未取得有效判定证据。")}</p><div className="qm-evidence-grid">{(["source", "target"] as const).map(role => <section key={role}><h3>{role === "source" ? "源资料" : "目标资料"} · {data[role].external_id}</h3><small>{data[role].processing?.derived ? "派生模型特征；区间指向整个模型" : "原文字符区间"} [{data[role].start}, {data[role].end}) · 策略：{String(data[role].processing?.strategy || "legacy")}</small><blockquote>{data.candidate.evidence?.[role === "source" ? "source_quote" : "target_quote"] || "无引用"}</blockquote><pre>{data[role].content}</pre><details><summary>单元处理元数据</summary><pre>{JSON.stringify(data[role].processing || {}, null, 2)}</pre></details><button onClick={() => onArtifact(data[role].artifact_id)}>查看完整制品</button></section>)}</div></>}</Modal>;
}
