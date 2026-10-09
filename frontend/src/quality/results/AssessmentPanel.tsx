import { Button, Collapse, Tag } from "antd";
import { ShieldCheck } from "lucide-react";
import type { Assessment, AssessmentStatus } from "./api";

const assessmentLabels: Record<AssessmentStatus, string> = {
  implemented: "已实现", uncovered: "无覆盖", issues: "存在异常", analysis_error: "分析异常", not_analyzed: "未分析",
};
const assessmentColors: Record<AssessmentStatus, string> = {
  implemented: "green", uncovered: "gold", issues: "red", analysis_error: "volcano", not_analyzed: "default",
};

export function AssessmentStatusTag({assessment}: {assessment: Assessment | undefined}) {
  return <Tag color={assessment ? assessmentColors[assessment.status] : "default"}>
    {assessment ? assessmentLabels[assessment.status] : "未分析"}
  </Tag>;
}

function semanticLabel(status: Assessment["semantic_status"]): string {
  return status === "implemented" ? "已保存语义候选：已实现"
    : status === "uncovered" ? "已保存语义候选：无覆盖"
    : status === "issues" ? "已保存语义候选：存在异常" : "已保存语义候选";
}

export function AssessmentPanel({assessment, title, onReadNode}: {
  assessment: Assessment | undefined; title: string; onReadNode: (node: string) => void;
}) {
  return <section className="result-card overall-assessment">
    <div className="result-card-heading"><h2><ShieldCheck size={18} />{title}</h2><div className="assessment-status-pair"><AssessmentStatusTag assessment={assessment} />
      {assessment?.semantic_status && !assessment.semantic_result_final && <Tag color="blue">{semanticLabel(assessment.semantic_status)}</Tag>}
      {assessment?.execution_status && assessment.execution_status !== "completed" && <Tag color="orange">执行：{assessment.execution_status}</Tag>}
    </div></div>
    <div className="overall-assessment-body">
      <p className="overall-evaluation">{assessment?.evaluation_text || "尚未保存总体评价，不将执行完成或检查点计数视为已实现。"}</p>
      <p className="overall-evaluation-note">{assessment?.finalized ? "已保存审核结论；执行进度与此结论分别记录。" : assessment?.semantic_status ? "已保存语义候选，但尚未通过独立校验；执行错误不会被解释为语义缺陷。" : "尚未形成有效的完整结论；已保存的局部事实仍可查看。"}</p>
      {assessment?.source_anchor_status === "incomplete" && <p className="overall-evaluation-note overall-source-anchor-warning">部分检查点没有可验证的唯一原文锚点，不能据此把源语段解释为完整覆盖。</p>}
      {assessment?.execution_error?.message && <p className="overall-execution-error">最近一次执行：{assessment.execution_error.code || "error"} · {assessment.execution_error.message}</p>}
      {(assessment?.issues.length || 0) > 0 && <Collapse items={assessment!.issues.map((issue, index) => ({
        key: issue.issue_id,
        label: `整体问题 ${index + 1} · 查看分析与原文证据`,
        children: <div className="overall-issue">
          <strong>需求原文</strong><blockquote>{issue.source_quote}</blockquote>
          <strong>分析理由</strong><p>{issue.reason}</p>
          {issue.evidence.map((e, i) => <article className="overall-issue-evidence" key={`${e.node_id}/${e.start_offset}/${e.end_offset}/${i}`}>
            <strong>设计证据 {i + 1}</strong><blockquote>{e.exact_quote}</blockquote>
            <div className="evidence-meta">原文范围 [{e.start_offset}, {e.end_offset}){e.candidate_id && ` · Candidate：${e.candidate_id}`}</div>
            <Button type="link" size="small" onClick={() => onReadNode(e.node_id)}>查看设计原文与位置 →</Button>
          </article>)}
        </div>,
      }))} />}
    </div>
  </section>;
}
