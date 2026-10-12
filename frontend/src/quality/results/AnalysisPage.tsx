import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { Alert, Button, Collapse, Drawer, Pagination, Select, Table, Tabs } from "antd";
import { CheckCircle2, Download, FileText, GitBranch, ListChecks, MessageSquareText, RefreshCw, Search, ShieldCheck, TriangleAlert } from "lucide-react";
import { navigate } from "../../navigation";
import { api as library, part } from "../api";
import { resultsApi, type Check, type Checkpoint, type Sentence, type Workspace } from "./api";
import { AssessmentPanel, AssessmentStatusTag } from "./AssessmentPanel";
import { NodeReader } from "./NodeReader";
import { Busy, ErrorNotice, Metrics, NoData, ResultShell, RunSelect, Status, exportJson, label, useRead } from "./shared";
import "./results.css";
const ReviewWorkflow = lazy(() => import("./ReviewWorkflow"));

const category: Record<string, string> = {function_result: "功能 / 结果", condition_constraint: "条件 / 约束"};
function SuggestionCard({sentence, access, review, revision}: {sentence: Sentence; access: ReturnType<typeof resultsApi>; review: string; revision: number}) {
  const saved = useRead(signal => access.checkpoint(review, sentence.sentence_id, signal), [access, review, sentence.sentence_id, revision]);
  const checkpoint = saved.data; const draft = checkpoint?.suggestion_drafts?.at(-1); const output = checkpoint?.latest_output;
  const feedback = checkpoint?.validation_feedback?.at(-1);
  const isFinal = output?.execution_status === "completed" && feedback?.valid === true && feedback.draft_iteration === draft?.iteration;
  return <article className="suggestion-item"><div className="suggestion-number">{sentence.ordinal}</div><div className="suggestion-content"><div className="suggestion-title"><h3>语块 {sentence.ordinal} 的修改意见</h3>{checkpoint && <Status value={isFinal ? "completed" : checkpoint.workflow_status} />}</div>
    <p className="suggestion-source">{sentence.text}</p><ErrorNotice error={saved.error} />
    {saved.loading ? <Busy /> : !checkpoint ? !saved.error && <p className="result-footnote">未保存建议记录。本页不自动调用 Agent 生成意见。</p> : <>
      {output?.error_code && <Alert type="error" title={output.error_code} description={output.error_message} />}
      <h4>{isFinal ? "已通过验证的最终建议" : draft ? `草稿 · 第 ${draft.iteration} 版（不是最终意见）` : "尚未形成建议"}</h4>
      <p>{(isFinal ? output?.problem_summary : draft?.problem_summary) || output?.problem_summary}</p><div className="suggestion-text">{(isFinal ? output?.suggestion_text : draft?.suggestion_text) || "没有已保存的修改文本"}</div>
      {(isFinal ? output?.rationale : draft?.rationale) && <p className="suggestion-rationale">依据：{isFinal ? output?.rationale : draft?.rationale}</p>}
      <div className="suggestion-bindings">关联检查点：{(isFinal ? output?.affected_check_ids : draft?.check_ids)?.join(" · ") || "未绑定"}</div>
      <div className="suggestion-bindings">关联整体问题：{(isFinal ? output?.affected_issue_ids : draft?.issue_ids)?.join(" · ") || "无独立整体问题"}</div>
      {feedback && <div className="validation-feedback"><ShieldCheck size={15} /><span>验证草稿版本 {feedback.draft_iteration} · {feedback.valid ? "通过" : "需修订"}{feedback.required_revision && `：${feedback.required_revision}`}{feedback.issues?.length > 0 && `；${feedback.issues.join("；")}`}</span></div>}
      {(output?.unresolved_questions || draft?.unresolved_questions || []).length > 0 && <p className="result-footnote">待澄清：{(output?.unresolved_questions || draft?.unresolved_questions)?.join("；")}</p>}
      {(checkpoint.suggestion_drafts?.length || 0) > 1 && <Collapse size="small" items={[{key: "history", label: "查看草稿迭代记录", children: checkpoint.suggestion_drafts.map(d => <div key={d.iteration} className="draft-history"><strong>第 {d.iteration} 版</strong><p>{d.suggestion_text}</p></div>)}]} />}
    </>}
  </div></article>;
}
function Summary({workspace}: {workspace: Workspace}) {
  const counts = workspace.checks.reduce<Record<string, number>>((a, c) => ({...a, [c.status]: (a[c.status] || 0) + 1}), {});
  return <section className="result-card analysis-summary"><div className="result-card-heading"><h2><ShieldCheck size={18} />审核状态与事实汇总</h2></div><div className="summary-run"><Status value={workspace.status} /><span>工作区状态不等于需求满足结论</span></div><div className="summary-counts">{["supported", "contradicted", "insufficient", "uncertain", "pending"].map(status => <div key={status}><Status value={status} /><strong>{counts[status] || 0}</strong></div>)}</div><p className="result-footnote">以上只对已保存的检查点计数，不将缺失分析转换为通过。</p><Collapse size="small" items={[{key: "summary", label: "查看后端已保存汇总（原始字段）", children: <pre className="facts-json">{Object.keys(workspace.summary).length ? JSON.stringify(workspace.summary, null, 2) : "尚未保存 summary"}</pre>}]} /></section>;
}
export default function AnalysisPage({tenant, project, initialRun, initialNode}: {tenant: string; project: string; initialRun?: string; initialNode?: string}) {
  const access = useMemo(() => resultsApi(tenant, project), [tenant, project]); const [revision, setRevision] = useState(0);
  const [runId, setRunId] = useState(initialRun || ""); const [requirement, setRequirement] = useState(initialNode || ""); const [reviewId, setReviewId] = useState(() => new URLSearchParams(window.location.hash.split("?")[1] || "").get("review") || "");
  const [sentenceId, setSentenceId] = useState(""); const [status, setStatus] = useState(""); const [checkId, setCheckId] = useState(""); const [node, setNode] = useState(""); const [showExecution, setShowExecution] = useState(false);
  const [pageTab, setPageTab] = useState(() => new URLSearchParams(window.location.hash.split("?")[1] || "").get("view") === "workflow" ? "workflow" : "results");
  const [workflowSentence, setWorkflowSentence] = useState(() => new URLSearchParams(window.location.hash.split("?")[1] || "").get("sentence") || "");
  const info = useRead(() => library.project(tenant, project), [tenant, project]); const runs = useRead(signal => access.runs(signal), [access, revision]);
  useEffect(() => { if (!runId && runs.data?.length) setRunId(runs.data.find(r => r.status === "completed")?.run_id || runs.data[0].run_id); }, [runs.data, runId]);
  const reviews = useRead(signal => runId ? access.reviews(runId, requirement, signal) : Promise.resolve([]), [access, runId, requirement, revision]);
  useEffect(() => { if (reviews.data && !reviews.data.some(r => r.review_id === reviewId)) setReviewId(reviews.data[0]?.review_id || ""); }, [reviews.data, reviewId]);
  const result = useRead(signal => reviewId ? access.workspace(reviewId, signal) : Promise.resolve(null), [access, reviewId, revision]);
  const w = result.data; const selectedReview = reviews.data?.find(r => r.review_id === reviewId);
  const workflowSource = w?.sentences.find(s => s.sentence_id === workflowSentence) || w?.sentences[0];
  useEffect(() => { setSentenceId(""); setStatus(""); setCheckId(""); }, [reviewId]);
  const checks = w?.checks.filter(c => (!sentenceId || c.sentence_id === sentenceId) && (!status || c.status === status)) || [];
  useEffect(() => { if (!checks.some(c => c.check_id === checkId)) setCheckId(checks[0]?.check_id || ""); }, [w, sentenceId, status, checkId]);
  const selectedCheck = w?.checks.find(c => c.check_id === checkId);
  const evidence = w?.evidence.filter(e => e.check_id === checkId) || [];
  const [evidencePage, setEvidencePage] = useState(1);
  useEffect(() => setEvidencePage(1), [reviewId, checkId]);
  const currentEvidencePage = Math.min(evidencePage, Math.max(1, Math.ceil(evidence.length / 2)));
  const failedTasks = w?.tasks.filter(t => ["blocked", "failed"].includes(t.status)) || [];
  const selectedSentences = w?.sentences.filter(s => !sentenceId || s.sentence_id === sentenceId) || [];
  const suggestionSentences = selectedSentences.filter(s => s.assessment?.suggestion_required === true);
  return <ResultShell project={project} name={info.data?.name || ""} active="analysis">
    <div className="result-title"><div><div className="eyebrow">CONSISTENCY REVIEW · 可追查的审核事实</div><h1>一致性分析与修改建议</h1><p>查看需求语块、检查点、原文证据与已经保存的 Agent 建议。</p></div><div className="result-actions"><Button icon={<RefreshCw size={15} />} onClick={() => setRevision(v => v + 1)}>刷新</Button><Button type="primary" icon={<Download size={15} />} disabled={!w} onClick={() => exportJson(`Review-${reviewId}.json`, w)}>导出审核事实</Button></div></div>
    <ErrorNotice error={info.error || runs.error || reviews.error || result.error} />
    <div className="run-bar"><RunSelect runs={runs.data || []} value={runId} onChange={v => {setRunId(v); setReviewId(""); setRequirement("");}} /><Select aria-label="选择审核记录" className="review-select" placeholder="选择已保存审核" value={reviewId || undefined} onChange={setReviewId} options={reviews.data?.map(r => ({value: r.review_id, label: `${r.requirement_preview || r.requirement_node_id} · ${label(r.status)} · ${r.review_id.slice(0, 8)}`}))} />{requirement && <Button type="link" onClick={() => {setRequirement(""); setReviewId("");}}>查看全部需求</Button>}</div>
    <Tabs className="review-page-tabs" activeKey={pageTab} onChange={value => {
      setPageTab(value);
      const query = new URLSearchParams(window.location.hash.split("?")[1] || ""); query.set("review", reviewId); query.set("view", value);
      window.history.replaceState(null, "", `${window.location.hash.split("?")[0]}?${query}`);
    }} items={[{key: "results", label: "评审结果"}, {key: "workflow", label: "LLM 工作过程"}]} />
    {runs.loading || reviews.loading || result.loading ? <Busy /> : !w ? <section className="result-card"><NoData title="没有可展示的审核记录" detail={runId ? "此范围下尚无已保存审核。本页不会自动启动 Agent，也不会将 TLR 链接当作满足评价。" : "项目尚无 TLR 结果。"} /></section> : <>
      {pageTab === "workflow" ? <>
        {w.sentences.length > 1 && <Select aria-label="选择工作流程语段" value={workflowSource?.sentence_id} onChange={setWorkflowSentence} options={w.sentences.map(s => ({value: s.sentence_id, label: `语段 ${s.ordinal} · ${s.text.slice(0, 50)}`}))} />}
        {workflowSource ? <Suspense fallback={<Busy />}><ReviewWorkflow key={`${reviewId}/${workflowSource.sentence_id}`} tenant={tenant} project={project} review={reviewId} sentence={workflowSource.sentence_id} sourceText={workflowSource.text} revision={revision} /></Suspense> : <NoData title="尚无源语段" detail="没有已保存语段可供查询工作流程。" />}
      </> : <>
      <Metrics items={[{title: "检查点", value: w.checks.length, hint: `${w.sentences.length} 个已保存源语块`, icon: <ListChecks />}, {title: "已满足", value: w.checks.filter(c => c.status === "supported").length, hint: "检查点状态为 supported", icon: <CheckCircle2 />, tone: "green"}, {title: "冲突 / 证据待补", value: w.checks.filter(c => ["contradicted", "insufficient", "uncertain"].includes(c.status)).length, hint: "三种语义状态分别展示", icon: <TriangleAlert />, tone: "amber"}, {title: "执行异常", value: failedTasks.length, hint: "blocked / failed，不算语义缺陷", icon: <ShieldCheck />, tone: "red"}]} />
      <section className="result-card requirement-card"><div className="result-card-heading"><h2><FileText size={19} />当前需求 · 原始语块</h2><div><Status value={w.status} /><Button type="link" onClick={() => navigate(`/projects/${part(project)}/trace/${part(w.tlr_run_id)}/${part(w.requirement_node_id)}`)} icon={<GitBranch size={14} />}>返回追溯关系</Button></div></div><NodeReader key={w.requirement_node_id} access={access} node={w.requirement_node_id} project={project} /><div className="requirement-metadata"><span>Review：<code>{reviewId}</code></span><span>TLR：<code>{w.tlr_run_id}</code></span><span>创建时间：{selectedReview && new Date(selectedReview.created_at).toLocaleString("zh-CN")}</span></div></section>
      <AssessmentPanel title="语块总体评价" assessment={w.assessment} onReadNode={setNode} />
      {failedTasks.length > 0 && <Alert type="warning" showIcon title={`${failedTasks.length} 个任务存在执行异常，不能据此判断需求未满足`} action={<Button size="small" onClick={() => setShowExecution(true)}>查看错误</Button>} />}
      <div className="analysis-grid"><section className="result-card"><div className="result-card-heading"><h2><ListChecks size={18} />检查点与完成情况</h2><span>{checks.length} 项</span></div><div className="analysis-filters"><Select aria-label="筛选语块" value={sentenceId} onChange={setSentenceId} options={[{value: "", label: "全部源语块"}, ...w.sentences.map(s => ({value: s.sentence_id, label: `语块 ${s.ordinal} · ${label(s.status)}`}))]} /><Select aria-label="检查点状态" value={status} onChange={setStatus} options={[{value: "", label: "全部状态"}, ...["supported", "contradicted", "insufficient", "uncertain", "pending"].map(v => ({value: v, label: label(v)}))]} /><Button type="text" onClick={() => setShowExecution(true)}>执行记录</Button></div>
        <div className="analysis-check-table"><Table<Check> key={`${reviewId}/${sentenceId}/${status}`} rowKey="check_id" size="middle" dataSource={checks} pagination={{pageSize: 5, showSizeChanger: false}} scroll={{x: 620, y: 440}} onRow={c => ({onClick: () => setCheckId(c.check_id), className: c.check_id === checkId ? "selected-row" : ""})} expandable={{expandedRowRender: c => <div className="check-expanded"><strong>原文验证范围</strong><blockquote>{c.source_quote || "未保存原文 quote"}</blockquote><strong>评价理由</strong><p>{c.note || "尚未保存评价理由"}</p><code>{c.check_id}</code></div>}} columns={[{title: "验证内容", dataIndex: "statement", width: 240}, {title: "类型", render: (_, c) => category[c.category] || c.category, width: 108}, {title: "完成情况", render: (_, c) => <Status value={c.status} />, width: 112}, {title: "理由", render: (_, c) => <span className="table-preview">{c.note || "尚无评价理由"}</span>}, {title: "证据", render: (_, c) => w.evidence.filter(e => e.check_id === c.check_id).length, width: 64}]} /></div>
      </section><section className="result-card evidence-panel"><div className="result-card-heading"><h2><Search size={18} />对应原文证据</h2><span>{evidence.length} 条</span></div>{selectedCheck && <div className="evidence-check"><Status value={selectedCheck.status} /><p>{selectedCheck.statement}</p><small>{selectedCheck.note || "尚无理由"}</small></div>}
        <div className="analysis-evidence-list">{evidence.length ? evidence.slice((currentEvidencePage - 1) * 2, currentEvidencePage * 2).map((e, i) => <article className="evidence-card" key={`${e.evidence_id}/${e.check_id}/${e.relation}`}><div className="evidence-heading"><strong>证据 {(currentEvidencePage - 1) * 2 + i + 1}</strong><span className={`evidence-relation ${e.relation}`}>{e.relation === "supporting" ? "支持" : e.relation === "counter" ? "反证" : "上下文"}</span><Status value={e.validation_status} /></div><blockquote>{e.exact_quote}</blockquote><code>{e.evidence_id}</code><div className="evidence-meta">来源：{e.source} · 原文范围 [{e.start_offset}, {e.end_offset})</div><div className="evidence-meta">Candidate：{e.candidate_id || "非 TLR 绑定的调查证据"}</div><Button type="link" size="small" onClick={() => setNode(e.design_node_id)}>查看设计原文与位置 →</Button></article>) : <NoData title="此检查点没有已保存证据" detail="没有证据不等于存在冲突；以检查点状态和理由为准。" />}
        </div>
        {evidence.length > 0 && <div className="analysis-evidence-pagination"><Pagination size="small" current={currentEvidencePage} total={evidence.length} pageSize={2} showSizeChanger={false} onChange={setEvidencePage} /></div>}
      </section></div>
      <section className="result-card sentence-progress"><div className="result-card-heading"><h2>源句段与调查进度</h2></div>{w.sentences.map(s => <div key={s.sentence_id}><strong>句段 {s.ordinal}</strong><span>执行：<Status value={s.status} /></span><span>结论：<AssessmentStatusTag assessment={s.assessment} /></span><span>检查点集合：{s.checks_finalized ? "已定稿" : "未定稿"} · 原文范围 [{s.start_offset}, {s.end_offset})</span><p>{s.text}</p><AssessmentPanel title={`句段 ${s.ordinal} 总体评价`} assessment={s.assessment} onReadNode={setNode} /></div>)}</section>
      {suggestionSentences.length > 0 && <section className="result-card suggestion-section"><div className="result-card-heading"><h2><MessageSquareText size={18} />修改建议与草稿</h2><span>综合检查点与总体评价，仅针对已审核的业务问题生成</span></div>{suggestionSentences.map(s => <SuggestionCard key={`${reviewId}/${s.sentence_id}`} sentence={s} access={access} review={reviewId} revision={revision} />)}</section>}
      <Summary workspace={w} />
      </>}
    </>}
    <Drawer title="canonical 设计原文" open={!!node} onClose={() => setNode("")} size={560}>{node && <NodeReader key={node} access={access} node={node} project={project} />}</Drawer>
    <Drawer title="已保存的执行记录与错误" open={showExecution} onClose={() => setShowExecution(false)} size={760}>{w && <Tabs items={[{key: "tasks", label: "任务", children: <Table rowKey="task_id" dataSource={w.tasks} pagination={{pageSize: 8}} columns={[{title: "角色", dataIndex: "role"}, {title: "状态", render: (_, t) => <Status value={t.status} />}, {title: "错误", render: (_, t) => <span>{t.error_code}<br />{t.error_message}</span>}]} expandable={{expandedRowRender: t => <><code>{t.task_id}</code><pre className="facts-json">{JSON.stringify(t.output, null, 2)}</pre></>}} />}, {key: "events", label: `事件（${w.events.length}，工作区最多返回 200 条）`, children: <Collapse items={w.events.map(e => ({key: e.event_id, label: `${e.actor_role} · ${e.event_type} · ${e.status}`, children: <pre className="facts-json">{JSON.stringify(e.payload, null, 2)}</pre>}))} />}]} />}</Drawer>
  </ResultShell>;
}
