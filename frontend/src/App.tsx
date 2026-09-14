import {
  Database,
  FileText,
  FileUp,
  MessageSquareText,
  RefreshCw,
  Send,
  ShieldCheck,
  Sparkles,
  Table2,
} from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import {
  generateReport,
  listChatHistory,
  listProjects,
  listReports,
  loadSchema,
  readDatabase,
  sendChat,
  extractRequirements,
  writeDatabase,
} from "./api";
import { mockMessages } from "./mock";
import type {
  ChatMessage,
  DatabaseReadResponse,
  DatabaseSchema,
  DatabaseScope,
  ProjectSummary,
  ReportSummary,
  ReportType,
  RequirementExtractionResponse,
  ViewId,
  WriteOperation,
} from "./types";

const views: Array<{ id: ViewId; label: string; icon: ReactNode }> = [
  { id: "quality", label: "项目资料库", icon: <Database size={18} /> },
  { id: "chat", label: "对话", icon: <MessageSquareText size={18} /> },
  { id: "report", label: "报告生成", icon: <FileText size={18} /> },
  { id: "requirements", label: "需求拆分", icon: <FileUp size={18} /> },
  { id: "database", label: "数据库读写", icon: <Database size={18} /> },
];

const reportTypes: Array<{ id: ReportType; label: string; hint: string }> = [
  { id: "quality_overview", label: "质量总览", hint: "整体质量态势" },
  { id: "traceability", label: "追踪分析", hint: "需求-设计-代码-测试" },
  { id: "coverage", label: "覆盖分析", hint: "测试与需求覆盖" },
  { id: "custom", label: "专题报告", hint: "可自定义关注点" },
];

const readScopes: Array<{ id: DatabaseScope; label: string }> = [
  { id: "projects", label: "项目" },
  { id: "artifacts", label: "资产" },
  { id: "trace_links", label: "追踪关系" },
  { id: "reports", label: "报告" },
  { id: "audit_events", label: "审计事件" },
];

const writeOperations: Array<{ id: WriteOperation; label: string }> = [
  { id: "add_project", label: "新增项目" },
  { id: "add_artifact", label: "新增资产" },
  { id: "add_trace_link", label: "新增追踪关系" },
  { id: "append_chat", label: "追加对话" },
  { id: "save_report", label: "保存报告" },
  { id: "log_event", label: "记录事件" },
];

const qualityModes = [
  { id: "quality", label: "质量判断" },
  { id: "traceability", label: "追踪关系" },
  { id: "summary", label: "简要摘要" },
] as const;

const reportFocusOptions = ["requirements", "design", "code", "tests", "traceability", "risks"];
const sourceKinds = ["requirement", "design", "code", "test", "analysis", "trace"];

function defaultWritePayload(operation: WriteOperation, projectId: string): string {
  const payloadByOperation: Record<WriteOperation, Record<string, unknown>> = {
    add_project: {
      name: "New Quality Project",
      description: "待分析的软件质量项目",
      owner: "quality-team",
      status: "active",
    },
    add_artifact: {
      project_id: projectId,
      kind: "requirement",
      name: "requirements.md",
      path: "docs/requirements.md",
      version: "v1.0",
      content: "系统应支持质量分析、报告生成和数据库读写。",
      meta: { source: "lifecycle" },
    },
    add_trace_link: {
      project_id: projectId,
      source_artifact_id: "source-id",
      target_artifact_id: "target-id",
      relation_type: "implements",
      confidence: 0.9,
      evidence: "需求映射到代码实现",
    },
    append_chat: {
      project_id: projectId,
      role: "user",
      content: "请总结当前项目的质量风险。",
      evidence: [],
    },
    save_report: {
      project_id: projectId,
      report_type: "quality_overview",
      title: "项目质量总览报告",
      focus: ["requirements", "tests", "traceability"],
      markdown: "# 项目质量总览报告\n\n## 概览\n- 待填写",
      highlights: ["资产数：0"],
      risks: ["请补充 trace link"],
    },
    log_event: {
      operation: "manual_note",
      note: "质量检查记录",
    },
  };
  return JSON.stringify(payloadByOperation[operation], null, 2);
}

function App() {
  const [activeView, setActiveView] = useState<ViewId>(() => /^#\/?(projects|models)(\/|$)/.test(window.location.hash) ? "quality" : "chat");
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [schema, setSchema] = useState<DatabaseSchema | null>(null);
  const [chatMode, setChatMode] = useState<(typeof qualityModes)[number]["id"]>("quality");
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatDraft, setChatDraft] = useState("");
  const [reportType, setReportType] = useState<ReportType>("quality_overview");
  const [reportFocus, setReportFocus] = useState<string[]>(["requirements", "code", "tests"]);
  const [reportSourceKinds, setReportSourceKinds] = useState<string[]>(["requirement", "design", "code", "test"]);
  const [reportPreview, setReportPreview] = useState("");
  const [reportHistory, setReportHistory] = useState<ReportSummary[]>([]);
  const [requirementResult, setRequirementResult] = useState<RequirementExtractionResponse | null>(null);
  const [requirementFile, setRequirementFile] = useState<File | null>(null);
  const [requirementError, setRequirementError] = useState("");
  const [readScope, setReadScope] = useState<DatabaseScope>("artifacts");
  const [readKeyword, setReadKeyword] = useState("");
  const [readLimit, setReadLimit] = useState(20);
  const [readResult, setReadResult] = useState<DatabaseReadResponse | null>(null);
  const [writeOperation, setWriteOperation] = useState<WriteOperation>("log_event");
  const [writePayload, setWritePayload] = useState(defaultWritePayload("log_event", ""));
  const [writeFeedback, setWriteFeedback] = useState("");
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState("");

  const selectedProject = useMemo(
    () => projects.find((project) => project.id === selectedProjectId) ?? projects[0],
    [projects, selectedProjectId],
  );

  useEffect(() => {
    void bootstrap();
  }, []);

  useEffect(() => {
    if (!selectedProjectId) return;
    void refreshProjectScopedData(selectedProjectId);
    setWritePayload((current) => {
      const currentText = current.trim();
      if (!currentText) {
        return defaultWritePayload(writeOperation, selectedProjectId);
      }
      try {
        const parsed = JSON.parse(currentText) as Record<string, unknown>;
        if (typeof parsed.project_id === "string" || writeOperation === "add_project" || writeOperation === "log_event") {
          return current;
        }
      } catch {
        return current;
      }
      return current;
    });
  }, [selectedProjectId]);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(""), 2200);
    return () => window.clearTimeout(timer);
  }, [toast]);

  async function bootstrap() {
    const [projectRows, schemaRows] = await Promise.all([listProjects(), loadSchema()]);
    setProjects(projectRows);
    setSchema(schemaRows);
    const firstProject = projectRows[0];
    if (firstProject) {
      setSelectedProjectId((current) => current || firstProject.id);
      const [history, reports] = await Promise.all([
        listChatHistory(firstProject.id),
        listReports(firstProject.id),
      ]);
      setChatMessages(history.length ? history : mockMessages);
      setReportHistory(reports);
      setWritePayload(defaultWritePayload(writeOperation, firstProject.id));
    }
  }

  async function refreshProjectScopedData(projectId: string) {
    const [history, reports] = await Promise.all([listChatHistory(projectId), listReports(projectId)]);
    setChatMessages(history.length ? history : mockMessages);
    setReportHistory(reports);
  }

  function notify(message: string) {
    setToast(message);
  }

  function toggleFocus(item: string) {
    setReportFocus((current) =>
      current.includes(item) ? current.filter((value) => value !== item) : [...current, item],
    );
  }

  function toggleSourceKind(item: string) {
    setReportSourceKinds((current) =>
      current.includes(item) ? current.filter((value) => value !== item) : [...current, item],
    );
  }

  function formatValue(value: unknown): string {
    if (value === null || value === undefined) return "-";
    if (typeof value === "string") return value;
    if (typeof value === "number" || typeof value === "boolean") return String(value);
    return JSON.stringify(value);
  }

  async function handleSendChat(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedProjectId || !chatDraft.trim()) return;
    setBusy(true);
    const userMessage: ChatMessage = { role: "user", content: chatDraft.trim() };
    const nextHistory = [...chatMessages, userMessage];
    setChatMessages((current) => [...current, userMessage]);
    setChatDraft("");
    try {
      const response = await sendChat({
        project_id: selectedProjectId,
        message: userMessage.content,
        mode: chatMode,
        history: nextHistory,
      });
      setChatMessages((current) => [
        ...current,
        {
          role: "assistant",
          content: response.answer,
          evidence: response.evidence,
        },
      ]);
      notify("对话已发送");
    } finally {
      setBusy(false);
    }
  }

  async function handleGenerateReport() {
    if (!selectedProjectId) return;
    setBusy(true);
    try {
      const response = await generateReport({
        project_id: selectedProjectId,
        report_type: reportType,
        focus: reportFocus,
        source_kinds: reportSourceKinds,
      });
      setReportPreview(response.markdown);
      setReportHistory((current) => [
        {
          id: response.report_id,
          project_id: response.project_id,
          report_type: response.report_type,
          title: response.title,
          focus: reportFocus,
          created_at: new Date().toISOString(),
        },
        ...current,
      ]);
      notify("报告已生成");
    } finally {
      setBusy(false);
    }

  }

  async function handleExtractRequirements() {
    if (!requirementFile) {
      setRequirementError("请先选择一个 PDF 文件");
      return;
    }
    setBusy(true);
    setRequirementError("");
    try {
      const response = await extractRequirements(requirementFile);
      setRequirementResult(response);
      notify(`已拆分 ${response.requirements.length} 条需求`);
    } catch (error) {
      setRequirementError(error instanceof Error ? error.message : "PDF 解析失败");
    } finally {
      setBusy(false);
    }
  }

  async function handleReadDatabase() {
    setBusy(true);
    try {
      const response = await readDatabase({
        scope: readScope,
        project_id: selectedProjectId || undefined,
        keyword: readKeyword || undefined,
        limit: readLimit,
      });
      setReadResult(response);
      notify("数据库已读取");
    } finally {
      setBusy(false);
    }
  }

  async function handleWriteDatabase() {
    setBusy(true);
    try {
      const payload = JSON.parse(writePayload) as Record<string, unknown>;
      const response = await writeDatabase({
        operation: writeOperation,
        payload,
      });
      setWriteFeedback(`${response.message} (${response.record_id})`);
      notify("数据库已写入");
      if (selectedProjectId) {
        await refreshProjectScopedData(selectedProjectId);
      }
    } catch (error) {
      setWriteFeedback(error instanceof Error ? error.message : "写入失败");
    } finally {
      setBusy(false);
    }
  }

  function handleOperationChange(operation: WriteOperation) {
    setWriteOperation(operation);
    setWritePayload(defaultWritePayload(operation, selectedProjectId));
  }

  function renderChatView() {
    return (
      <section className="workspace-grid two-up">
        <article className="surface panel-primary">
          <div className="panel-header">
            <div>
              <span className="eyebrow">对话</span>
              <h3>项目质量问答</h3>
            </div>
            <div className="inline-controls">
              <label className="field compact">
                <span>模式</span>
                <select value={chatMode} onChange={(event) => setChatMode(event.target.value as typeof chatMode)}>
                  {qualityModes.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </label>
              <button className="ghost-button" type="button" onClick={() => setChatMessages(mockMessages)}>
                <RefreshCw size={16} />
                <span>重置</span>
              </button>
            </div>
          </div>

          <div className="message-list">
            {chatMessages.map((message, index) => (
              <div key={`${message.role}-${index}`} className={`message-row ${message.role}`}>
                <div className="avatar">{message.role === "user" ? "U" : "A"}</div>
                <div className="message-bubble">
                  <p>{message.content}</p>
                  {message.evidence?.length ? (
                    <div className="pill-row">
                      {message.evidence.map((item) => (
                        <span key={item} className="mini-pill">
                          {item}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </div>
              </div>
            ))}
          </div>

          <form className="composer" onSubmit={handleSendChat}>
            <textarea
              value={chatDraft}
              onChange={(event) => setChatDraft(event.target.value)}
              placeholder="输入质量问题、追踪关系分析、覆盖分析或报告要求"
              rows={4}
            />
            <div className="composer-footer">
              <div className="pill-row">
                {[
                  "当前项目还有哪些质量缺口？",
                  "生成一份项目质量总览",
                  "测试覆盖是否支持当前需求？",
                ].map((prompt) => (
                  <button key={prompt} type="button" className="chip-button" onClick={() => setChatDraft(prompt)}>
                    {prompt}
                  </button>
                ))}
              </div>
              <button className="primary-button" type="submit" disabled={busy}>
                <Send size={16} />
                <span>发送</span>
              </button>
            </div>
          </form>
        </article>

        <aside className="side-stack">
          <section className="surface">
            <div className="panel-header compact">
              <div>
                <span className="eyebrow">概览</span>
                <h3>当前项目</h3>
              </div>
            </div>
            <div className="metric-grid">
              <div>
                <span>资产</span>
                <strong>{selectedProject?.artifact_count ?? 0}</strong>
              </div>
              <div>
                <span>追踪</span>
                <strong>{selectedProject?.trace_link_count ?? 0}</strong>
              </div>
              <div>
                <span>报告</span>
                <strong>{reportHistory.length}</strong>
              </div>
            </div>
          </section>

          <section className="surface">
            <div className="panel-header compact">
              <div>
                <span className="eyebrow">建议</span>
                <h3>下一步动作</h3>
              </div>
            </div>
            <ul className="bullet-list">
              {(selectedProject?.artifact_count ?? 0) < 4 ? (
                <li>补齐需求、设计、代码和测试的 trace link。</li>
              ) : (
                <li>继续检查高风险需求的测试覆盖。</li>
              )}
              <li>把手工评审结论写回数据库，形成审计轨迹。</li>
              <li>生成项目质量总览报告，用于阶段汇报。</li>
            </ul>
          </section>
        </aside>
      </section>
    );
  }

  function renderReportView() {
    return (
      <section className="workspace-grid report-grid">
        <article className="surface panel-primary">
          <div className="panel-header">
            <div>
              <span className="eyebrow">报告</span>
              <h3>指定项目报告生成</h3>
            </div>
            <button className="primary-button" type="button" onClick={handleGenerateReport} disabled={busy}>
              <Sparkles size={16} />
              <span>生成报告</span>
            </button>
          </div>

          <div className="field-grid">
            <label className="field">
              <span>报告类型</span>
              <select value={reportType} onChange={(event) => setReportType(event.target.value as ReportType)}>
                {reportTypes.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.label} - {item.hint}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>项目</span>
              <input value={selectedProject?.name ?? ""} readOnly />
            </label>
          </div>

          <div className="group-block">
            <span className="group-title">关注点</span>
            <div className="pill-row">
              {reportFocusOptions.map((item) => (
                <button
                  key={item}
                  type="button"
                  className={`chip-button ${reportFocus.includes(item) ? "active" : ""}`}
                  onClick={() => toggleFocus(item)}
                >
                  {item}
                </button>
              ))}
            </div>
          </div>

          <div className="group-block">
            <span className="group-title">来源类型</span>
            <div className="pill-row">
              {sourceKinds.map((item) => (
                <button
                  key={item}
                  type="button"
                  className={`chip-button ${reportSourceKinds.includes(item) ? "active" : ""}`}
                  onClick={() => toggleSourceKind(item)}
                >
                  {item}
                </button>
              ))}
            </div>
          </div>

          <div className="surface inset">
            <div className="panel-header compact">
              <div>
                <span className="eyebrow">预览</span>
                <h3>Markdown</h3>
              </div>
            </div>
            <pre className="code-block">{reportPreview || "点击生成报告后这里显示 Markdown 预览"}</pre>
          </div>
        </article>

        <aside className="side-stack">
          <section className="surface">
            <div className="panel-header compact">
              <div>
                <span className="eyebrow">历史</span>
                <h3>最近报告</h3>
              </div>
            </div>
            <div className="report-list">
              {reportHistory.length ? (
                reportHistory.map((item) => (
                  <div key={item.id} className="list-row">
                    <div>
                      <strong>{item.title}</strong>
                      <p>{item.report_type}</p>
                    </div>
                    <small>{item.created_at ? new Date(item.created_at).toLocaleString() : "-"}</small>
                  </div>
                ))
              ) : (
                <p className="muted-text">暂无报告记录</p>
              )}
            </div>
          </section>

          <section className="surface">
            <div className="panel-header compact">
              <div>
                <span className="eyebrow">结果</span>
                <h3>报告摘要</h3>
              </div>
            </div>
            <div className="pill-row wrap">
              {(reportPreview ? ["预览已更新"] : ["等待生成"]).map((item) => (
                <span key={item} className="mini-pill">
                  {item}
                </span>
              ))}
            </div>
          </section>
        </aside>
      </section>
    );
  }

  function renderDatabaseView() {
    return (
      <section className="workspace-grid database-grid">
        <article className="surface panel-primary">
          <div className="panel-header">
            <div>
              <span className="eyebrow">数据库</span>
              <h3>受控读写</h3>
            </div>
            <button className="ghost-button" type="button" onClick={handleReadDatabase}>
              <RefreshCw size={16} />
              <span>读取</span>
            </button>
          </div>

          <div className="field-grid three">
            <label className="field">
              <span>范围</span>
              <select value={readScope} onChange={(event) => setReadScope(event.target.value as DatabaseScope)}>
                {readScopes.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>关键字</span>
              <input value={readKeyword} onChange={(event) => setReadKeyword(event.target.value)} />
            </label>
            <label className="field">
              <span>数量上限</span>
              <input type="number" min={1} max={200} value={readLimit} onChange={(event) => setReadLimit(Number(event.target.value))} />
            </label>
          </div>

          <div className="surface inset">
            <div className="panel-header compact">
              <div>
                <span className="eyebrow">结果</span>
                <h3>读取明细</h3>
              </div>
            </div>
            {readResult?.rows?.length ? (
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      {Object.keys(readResult.rows[0] || {}).map((key) => (
                        <th key={key}>{key}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {readResult.rows.map((row, index) => (
                      <tr key={index}>
                        {Object.values(row).map((value, cellIndex) => (
                          <td key={cellIndex}>{formatValue(value)}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="muted-text">点击读取后显示数据库行数据</p>
            )}
          </div>
        </article>

        <aside className="side-stack">
          <section className="surface">
            <div className="panel-header compact">
              <div>
                <span className="eyebrow">写入</span>
                <h3>受控操作</h3>
              </div>
            </div>
            <div className="field-grid">
              <label className="field">
                <span>操作</span>
                <select value={writeOperation} onChange={(event) => handleOperationChange(event.target.value as WriteOperation)}>
                  {writeOperations.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </label>
              <div className="inline-controls">
                <button className="ghost-button" type="button" onClick={() => setWritePayload(defaultWritePayload(writeOperation, selectedProjectId))}>
                  <Table2 size={16} />
                  <span>载入模板</span>
                </button>
                <button className="ghost-button" type="button" onClick={() => setWritePayload("")}>
                  <Database size={16} />
                  <span>清空</span>
                </button>
              </div>
            </div>
            <label className="field">
              <span>Payload</span>
              <textarea value={writePayload} onChange={(event) => setWritePayload(event.target.value)} rows={14} />
            </label>
            <button className="primary-button full-width" type="button" onClick={handleWriteDatabase} disabled={busy}>
              <Send size={16} />
              <span>提交写入</span>
            </button>
            <p className="feedback">{writeFeedback || "通过受控接口写入项目、资产、追踪关系、对话和报告。"} </p>
          </section>

          <section className="surface">
            <div className="panel-header compact">
              <div>
                <span className="eyebrow">结构</span>
                <h3>数据库模式</h3>
              </div>
            </div>
            <div className="schema-list">
              {schema ? (
                Object.entries(schema.tables).map(([table, columns]) => (
                  <div key={table} className="list-row">
                    <div>
                      <strong>{table}</strong>
                      <p>{columns.join(" · ")}</p>
                    </div>
                  </div>
                ))
              ) : (
                <p className="muted-text">模式加载中</p>
              )}
            </div>
          </section>
        </aside>
      </section>
    );
  }

  function renderRequirementsView() {
    return (
      <section className="workspace-grid report-grid">
        <article className="surface panel-primary">
          <div className="panel-header">
            <div>
              <span className="eyebrow">需求工程</span>
              <h3>上传项目 PDF，自动拆分需求</h3>
            </div>
            <FileText size={22} />
          </div>
          <p className="lead">
            系统会提取 PDF 文本，调用需求分析 Agent，将项目内容拆分为可实现、可验证、可追踪的需求点。
          </p>
          <label className="upload-dropzone">
            <FileUp size={28} />
            <strong>{requirementFile?.name ?? "选择项目 PDF 文件"}</strong>
            <span>仅支持 PDF，建议上传包含文本层的项目说明书</span>
            <input
              type="file"
              accept="application/pdf,.pdf"
              onChange={(event) => {
                setRequirementFile(event.target.files?.[0] ?? null);
                setRequirementError("");
              }}
            />
          </label>
          <button
            className="primary-button"
            type="button"
            onClick={handleExtractRequirements}
            disabled={busy || !requirementFile}
          >
            <Sparkles size={16} />
            <span>{busy ? "解析中..." : "开始拆分需求"}</span>
          </button>
          {requirementError ? <p className="feedback error-text">{requirementError}</p> : null}
          {requirementResult ? (
            <div className="surface inset">
              <div className="panel-header compact">
                <div>
                  <span className="eyebrow">项目理解</span>
                  <h3>{requirementResult.source_filename}</h3>
                </div>
                <span className="mini-pill">{requirementResult.page_count} 页</span>
              </div>
              <p className="lead">{requirementResult.project_summary}</p>
              {requirementResult.warnings.length ? (
                <ul className="bullet-list warning-list">
                  {requirementResult.warnings.map((warning) => <li key={warning}>{warning}</li>)}
                </ul>
              ) : null}
            </div>
          ) : null}
        </article>

        <aside className="side-stack">
          <section className="surface">
            <div className="panel-header compact">
              <div>
                <span className="eyebrow">结构化结果</span>
                <h3>需求列表</h3>
              </div>
              <span className="mini-pill">{requirementResult?.requirements.length ?? 0} 条</span>
            </div>
            {requirementResult?.requirements.length ? (
              <div className="requirement-list">
                {requirementResult.requirements.map((requirement) => (
                  <article className="requirement-card" key={requirement.requirement_id}>
                    <strong>{requirement.requirement_id}</strong>
                    <p>{requirement.statement}</p>
                  </article>
                ))}
              </div>
            ) : (
              <p className="muted-text">上传 PDF 并开始拆分后，这里会显示结构化需求。</p>
            )}
          </section>
        </aside>
      </section>
    );
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">SQM</div>
          <div>
            <h1>Software Quality Console</h1>
            <p>Chat / Report / DB</p>
          </div>
        </div>

        <nav className="nav-list">
          {views.map((view) => (
            <button
              key={view.id}
              className={`nav-item ${activeView === view.id ? "active" : ""}`}
              onClick={() => setActiveView(view.id)}
              type="button"
            >
              {view.icon}
              <span>{view.label}</span>
            </button>
          ))}
        </nav>

        <section className="surface sidebar-block">
          <span className="eyebrow">项目</span>
          <div className="project-list">
            {projects.map((project) => (
              <button
                key={project.id}
                className={`project-item ${selectedProjectId === project.id ? "active" : ""}`}
                onClick={() => setSelectedProjectId(project.id)}
                type="button"
              >
                <strong>{project.name}</strong>
                <small>
                  {project.status} · {project.artifact_count} assets
                </small>
              </button>
            ))}
          </div>
        </section>

        <section className="surface sidebar-block">
          <div className="side-header">
            <ShieldCheck size={16} />
            <span>连接状态</span>
          </div>
          <strong>{selectedProject?.name ?? "未选择项目"}</strong>
          <p>{selectedProject?.description ?? "等待项目加载"}</p>
        </section>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <div>
            <span className="eyebrow">Software Quality Agent</span>
            <h2>{selectedProject?.name ?? "质量工作台"}</h2>
            <p className="lead">{selectedProject?.description ?? "请选择一个项目开始分析"}</p>
          </div>
          <div className="status-strip">
            <span className="status-pill">
              <Sparkles size={14} />
              {selectedProject?.artifact_count ?? 0} 资产
            </span>
            <span className="status-pill">
              <Table2 size={14} />
              {schema ? Object.keys(schema.tables).length : 0} 张表
            </span>
            <span className="status-pill ok">
              <ShieldCheck size={14} />
              Local API ready
            </span>
          </div>
        </header>

        <section hidden={activeView !== "quality"} aria-label="项目资料库工作台">
          <iframe className="quality-workspace-frame" title="项目资料库工作台" src={`./quality.html${window.location.hash || "#/projects"}`} />
        </section>
        {activeView === "chat" ? renderChatView() : null}
        {activeView === "report" ? renderReportView() : null}
        {activeView === "requirements" ? renderRequirementsView() : null}
        {activeView === "database" ? renderDatabaseView() : null}
      </main>

      {toast ? <div className="toast">{toast}</div> : null}
    </div>
  );
}

export default App;
