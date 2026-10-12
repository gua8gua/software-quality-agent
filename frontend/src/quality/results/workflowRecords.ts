/** Public checkpoint projection. Never reconstruct hidden reasoning or missing tool results. */
export type JsonRecord = Record<string, any>;
export type WorkflowStep = {
  id: string; nodeId: string; ordinal: number; kind: "model" | "tool" | "note" | "error";
  agent: string; title: string; summary: string; at: string; status: string;
  durationMs: number | null; tool?: string; callId?: string; input: unknown; output: unknown;
  timeBasis: "model_request" | "tool_record" | "event";
};
export type WorkflowNode = {
  id: string; agent: string; role: string; title: string; purpose: string; status: string;
  phase: string; tools: string[]; stepIds: string[]; startedAt: string;
};
export type WorkflowAttempt = {number: number; status: string; modelCount: number; startedAt: string};
export type WorkflowView = {
  attempt: number; attempts: WorkflowAttempt[]; status: string; startedAt: string; finishedAt: string;
  nodes: WorkflowNode[]; edges: {id: string; source: string; target: string}[];
  steps: Omit<WorkflowStep, "input" | "output">[]; error: {code: string; message: string} | null;
};

const roles: Record<string, {role: string; title: string; purpose: string}> = {
  "review manager agent": {role: "manager", title: "Manager", purpose: "管理编排 · 调度评审与复核"},
  "review analysis agent": {role: "analysis", title: "Review Analysis", purpose: "评审分析 · 检查点与整体评价"},
  "evidence investigator agent": {role: "evidence", title: "Evidence Investigator", purpose: "证据调查 · 查阅设计原文"},
  "web research agent": {role: "web", title: "Web Research", purpose: "外部资料 · 标准与背景调查"},
  "suggestion agent": {role: "suggestion", title: "Suggestion", purpose: "修改建议 · 根据审核事实拟稿"},
  "review and suggestion validator agent": {role: "validator", title: "Validator", purpose: "独立复核 · 评价与建议验证"},
};
export function roleInfo(agent: string) {
  return roles[agent] || {role: "other", title: agent || "未记录角色", purpose: "公开工作记录"};
}
const toolNames: Record<string, string> = {
  get_review_segment: "读取源语段与检查点", get_review_progress: "查看审核进度",
  get_review_investigation: "查看资料调查范围", create_review_check: "建立检查点",
  finalize_review_checks: "确认检查点集合", read_review_passage: "读取设计资料",
  assess_review_check: "保存检查点评价", finalize_review_passage: "汇总资料覆盖",
  complete_review_analysis: "提交检查点结论", propose_review_assessment: "提交整体评价",
  validate_review_assessment: "审核整体评价", get_mandatory_tlr_nodes: "查询追溯候选",
  get_canonical_node: "查看原文节点", get_node_structure: "查看文档结构",
  get_node_path: "查看标题层级", get_node_neighborhood: "查询相邻内容",
  get_saved_tool_result: "读取已保存工具结果", record_passage_execution_error: "记录资料执行错误",
  run_review_analysis: "委派评审分析", investigate_review_material: "委派证据调查",
  validate_segment_assessment: "委派整体评价复核", draft_modification_suggestion: "委派修改建议",
  validate_modification_suggestion: "委派建议复核", search_artifact: "检索设计资料（BM25）",
  search_external_web: "网络检索", read_external_web_page: "阅读外部资料",
  research_external_context: "委派外部资料调查", research_suggestion_context: "调查建议参考资料",
  research_web_context: "委派外部资料调查", save_suggestion_draft: "保存建议草稿",
  save_suggestion_validation: "保存建议审核反馈", get_suggestion_workspace: "查看建议工作区",
  record_work_note: "保存工作说明", get_work_notes: "查看工作说明",
};
export const toolLabel = (name: string) => toolNames[name] || name;
const stageAgents: Record<string, string> = {manager: "review manager agent", review_analysis: "review analysis agent",
  evidence: "evidence investigator agent", web_research: "web research agent", suggestion: "suggestion agent",
  assessment_validator: "review and suggestion validator agent", suggestion_validator: "review and suggestion validator agent"};
function parsed(value: unknown): unknown {
  if (typeof value !== "string") return value;
  try {return JSON.parse(value);} catch {return value;}
}
function duration(record: JsonRecord) {
  if (typeof record.duration_ms === "number") return record.duration_ms;
  const start = Date.parse(record.at || record.started_at), end = Date.parse(record.finished_at || record.ended_at);
  return Number.isFinite(start) && Number.isFinite(end) && end >= start ? end - start : null;
}
function short(value: unknown, max = 110): string {
  return (typeof value === "string" ? value : JSON.stringify(value) || "").replace(/\s+/g, " ").slice(0, max);
}

/**
 * A provider output that ends with `length` is continued by the transport as
 * another model call.  Those calls are one public model step: keep the first
 * request as the input and the last public response as the output.  The
 * checkpoint keeps the original provider request/response, so this projection
 * does not reconstruct a prompt or manufacture an intermediate result.
 */
function mergeContinuationCalls(calls: JsonRecord[]): {call: JsonRecord; firstIndex: number; lastIndex: number}[] {
  const merged: {call: JsonRecord; firstIndex: number; lastIndex: number}[] = [];
  calls.forEach((call, index) => {
    const previous = merged.at(-1);
    const continuationOf = Number(call.continuation_of);
    if (previous && call.continuation_of != null && Number.isInteger(continuationOf)
      && continuationOf === previous.lastIndex && call.agent === previous.call.agent
      && calls[previous.lastIndex].provider_response?.finish_reasons?.[0] === "length") {
      previous.call = {
        ...previous.call,
        // The original first provider request is intentionally retained.
        output: call.output,
        status: call.status,
        finished_at: call.finished_at,
        error_code: call.error_code,
        error_message: call.error_message,
        provider_response: call.provider_response,
        usage: call.usage,
        response_id: call.response_id,
        continuation_count: (previous.call.continuation_count || 1) + 1,
      };
      previous.lastIndex = index;
      return;
    }
    merged.push({call: {...call}, firstIndex: index, lastIndex: index});
  });
  return merged;
}

export function projectWorkflow(checkpoint: JsonRecord, requested?: number) {
  const current = {...checkpoint, attempt: Number(checkpoint.attempts || checkpoint.latest_output?.attempt || 1)};
  const all: JsonRecord[] = [...(checkpoint.attempt_history || []), current];
  const number = requested ?? current.attempt;
  const raw = all.find(a => Number(a.attempt) === number);
  if (!raw) throw new Error("所选执行尝试没有保存记录");
  const nodes: WorkflowNode[] = [], steps: WorkflowStep[] = [];
  const calls: JsonRecord[] = raw.model_calls || [];
  const logicalCalls = mergeContinuationCalls(calls);
  const sdk: JsonRecord = raw.sdk_tool_results || {};
  const consumed = new Set<number>();
  const rawTools: JsonRecord[] = raw.tool_calls || [];
  let currentNode: WorkflowNode | undefined;
  logicalCalls.forEach(({call, lastIndex}, index) => {
    if (!currentNode || currentNode.agent !== (call.agent || "")) {
      const info = roleInfo(call.agent || "");
      currentNode = {id: `a${number}-node-${nodes.length + 1}`, agent: call.agent || "", ...info,
        status: "completed", phase: "模型调用", tools: [], stepIds: [], startedAt: call.at || ""};
      nodes.push(currentNode);
    }
    const node = currentNode;
    const output = (call.output || []).filter((item: JsonRecord) => item.type !== "reasoning");
    const text = output.filter((item: JsonRecord) => item.type === "message").flatMap((item: JsonRecord) =>
      (item.content || []).filter((p: JsonRecord) => p.type === "output_text" || p.type === "text").map((p: JsonRecord) => p.text)).join("\n");
    const functions = output.filter((item: JsonRecord) => item.type === "function_call");
    const originalInput = call.provider_request?.messages ?? call.input;
    const modelStep: WorkflowStep = {id: `a${number}-model-${index}`, nodeId: node.id, ordinal: 0, kind: "model",
      agent: node.agent, title: call.status === "running" ? "模型请求 · 等待输出" : "模型公开输出",
      summary: short(text || (functions.length ? `决定调用：${functions.map((f: JsonRecord) => toolLabel(f.name)).join("、")}` : call.error_message || "未保存公开文本")),
      at: call.at || "", status: call.status || "not_recorded", durationMs: duration(call),
      timeBasis: "model_request",
      input: originalInput ?? null,
      output: call.provider_response?.choices?.map((choice: JsonRecord) => choice.message)
        ?? (output.length ? output : (call.error_message ? {错误: call.error_message} : []))};
    steps.push(modelStep); node.stepIds.push(modelStep.id);
    node.phase = call.status === "running" ? "思考 · 等待模型输出" : "模型输出";
    if (call.status === "blocked" || call.status === "failed") node.status = "blocked";
    else if (call.status === "running") node.status = raw.workflow_status === "blocked" ? "blocked" : "running";
    functions.forEach((f: JsonRecord) => {
      // SDK call IDs are authoritative. Manual wrappers are only secondary public records.
      const sdkRecord = sdk[f.call_id];
      const toolIndex = rawTools.findIndex((t, i) => !consumed.has(i) && t.name === f.name &&
        t.at >= call.at && (lastIndex + 1 >= calls.length || t.at <= calls[lastIndex + 1].at));
      if (toolIndex >= 0) consumed.add(toolIndex);
      const tool = toolIndex >= 0 ? rawTools[toolIndex] : undefined;
      const actual = sdkRecord ? parsed(sdkRecord.output) : tool?.output;
      const isError = typeof actual === "object" && actual !== null && (
        ["blocked", "failed", "error"].includes((actual as JsonRecord).execution_status) ||
        ["blocked", "failed", "error"].includes((actual as JsonRecord).status));
      const status = isError ? "blocked" : sdkRecord || tool?.succeeded ? "completed" :
        raw.workflow_status === "running" ? "running" : "not_recorded";
      const step: WorkflowStep = {id: `a${number}-tool-${f.call_id || index + '-' + f.name}`, nodeId: node.id,
        ordinal: 0, agent: node.agent, kind: "tool", tool: f.name, callId: f.call_id,
        title: `工具调用 · ${toolLabel(f.name)}`, summary: toolLabel(f.name), at: tool?.at || call.at || "",
        timeBasis: tool?.at ? "tool_record" : "model_request",
        status, durationMs: tool ? duration(tool) : null, input: parsed(f.arguments),
        output: actual === undefined ? {说明: "未保存此调用的结果，不能据此认定工具成功。"} : actual};
      steps.push(step); node.stepIds.push(step.id);
      if (!node.tools.includes(f.name)) node.tools.push(f.name);
      node.phase = `${status === "running" ? "等待工具结果" : "调用工具"} · ${toolLabel(f.name)}`;
      if (isError) node.status = "blocked";
      else if (node.status !== "blocked" && status !== "completed") node.status = status;
    });
  });
  // Preserve wrapper-only records too (including tools which failed before SDK on_tool_end).
  rawTools.forEach((tool, index) => {
    if (consumed.has(index)) return;
    // A timestamp alone cannot prove which Agent invoked an unpaired wrapper.
    const node = tool.agent ? [...nodes].reverse().find(n => n.agent === tool.agent && n.startedAt <= tool.at) : undefined;
    const error = (raw.tool_errors || []).find((e: JsonRecord) => e.name === tool.name && e.at >= tool.at &&
      (!rawTools[index + 1]?.at || e.at <= rawTools[index + 1].at));
    const step: WorkflowStep = {id: `a${number}-wrapper-${index}`, nodeId: node?.id || "", ordinal: 0,
      agent: tool.agent || "", kind: "tool", tool: tool.name, title: `工具调用 · ${toolLabel(tool.name)}`,
      summary: toolLabel(tool.name), at: tool.at || "", timeBasis: "tool_record",
      status: tool.succeeded ? "completed" : error ? "blocked" : "not_recorded", durationMs: duration(tool),
      input: tool.arguments || parsed(tool.arguments_json),
      output: tool.output ?? (error || {说明: "工具包装层未保存结果；不推测返回内容。"})};
    steps.push(step); node?.stepIds.push(step.id);
    if (node && !node.tools.includes(tool.name)) node.tools.push(tool.name);
  });
  // Public errors/notes are distinct from LLM output. No speculative 'reasoning' is inserted.
  for (const [kind, records] of [["error", raw.errors || []], ["error", raw.tool_errors || []],
    ["note", number === current.attempt ? checkpoint.work_notes || [] : []]] as const) {
    for (const record of records as JsonRecord[]) {
      if (raw.last_started_at && record.at < raw.last_started_at) continue;
      const agent = record.agent || stageAgents[record.stage] || "";
      const node = agent ? [...nodes].reverse().find(n => n.agent === agent && (!record.at || n.startedAt <= record.at)) : undefined;
      const step: WorkflowStep = {id: `a${number}-${kind}-${steps.length}`, nodeId: node?.id || "", ordinal: 0,
        kind, agent, title: kind === "error" ? "执行错误记录" : "公开工作说明",
        summary: short(record.message || record.text || record.error_message), at: record.at || "",
        timeBasis: "event",
        status: kind === "error" ? "blocked" : "completed", durationMs: null, input: null, output: record};
      steps.push(step); node?.stepIds.push(step.id);
    }
  }
  steps.sort((a, b) => a.at.localeCompare(b.at)); steps.forEach((s, i) => {s.ordinal = i + 1;});
  if (nodes.length && ["blocked", "failed"].includes(raw.workflow_status)) nodes.at(-1)!.status = "blocked";
  const view: WorkflowView = {
    attempt: number, attempts: all.map(a => ({number: Number(a.attempt), status: a.workflow_status || "not_recorded",
      modelCount: (a.model_calls || []).length, startedAt: a.last_started_at || a.model_calls?.[0]?.at || ""})).reverse(),
    status: raw.workflow_status || "not_recorded", startedAt: raw.last_started_at || calls[0]?.at || "",
    finishedAt: raw.last_finished_at || "", nodes,
    // These edges describe observed execution order, not invented concurrency or dependencies.
    edges: nodes.slice(1).map((n, i) => ({id: `${nodes[i].id}-${n.id}`, source: nodes[i].id, target: n.id})),
    steps: steps.map(({input: _input, output: _output, ...rest}) => rest),
    error: raw.latest_output?.error_code ? {code: raw.latest_output.error_code, message: raw.latest_output.error_message || ""} : null,
  };
  return {view, details: new Map(steps.map(s => [s.id, s]))};
}
