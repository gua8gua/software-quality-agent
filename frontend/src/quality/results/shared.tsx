import { useEffect, useState, type ReactNode } from "react";
import { Alert, ConfigProvider, Empty, Select, Spin, Tag } from "antd";
import zhCN from "antd/locale/zh_CN";
import ProjectLayout from "../ProjectLayout";
import type { Run } from "./api";

export function useRead<T>(loader: (signal: AbortSignal) => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T>(); const [error, setError] = useState(""); const [loading, setLoading] = useState(true);
  useEffect(() => { const ctrl = new AbortController(); setData(undefined); setError(""); setLoading(true);
    loader(ctrl.signal).then(value => { if (!ctrl.signal.aborted) setData(value); }).catch(e => { if (!ctrl.signal.aborted) setError(String(e)); })
      .finally(() => { if (!ctrl.signal.aborted) setLoading(false); }); return () => ctrl.abort();
  // The caller supplies the complete resource identity; loader closures are intentionally not dependencies.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return {data, error, loading};
}
const labels: Record<string, string> = {direct: "直接追溯", related: "相关", no_link: "无链接", uncertain: "不确定", supported: "已满足", contradicted: "存在冲突", insufficient: "证据不足", pending: "待调查", completed: "执行完成", idle: "无需重复执行", interrupted: "执行中断", open: "未完成", running: "运行中", prepared: "已准备", blocked: "执行阻断", failed: "执行失败", valid: "校验有效", succeeded: "执行成功", unresolved: "未解决", partial: "部分完成", not_required: "无需建议"};
export const label = (value: string) => labels[value] || value;
export function Status({value}: {value: string | null | undefined}) {
  return <Tag color={value && ["supported", "valid", "succeeded", "completed"].includes(value) ? "green" : value && ["contradicted", "failed", "blocked"].includes(value) ? "red" : value && ["uncertain", "insufficient", "unresolved", "partial"].includes(value) ? "gold" : "blue"}>{value ? label(value) : "尚无判断"}</Tag>;
}
export function ErrorNotice({error}: {error: string}) { return error ? <Alert type="error" showIcon title="读取失败" description={error} /> : null; }
export function Busy() { return <div className="result-busy"><Spin tip="读取已保存结果" /></div>; }
export function NoData({title, detail}: {title: string; detail: string}) { return <Empty description={<><strong>{title}</strong><p>{detail}</p></>} />; }
export function ResultShell({project, name, active, children}: {project: string; name: string; active: "trace" | "analysis"; children: ReactNode}) {
  return <ConfigProvider locale={zhCN} theme={{token: {colorPrimary: "#3677ee", borderRadius: 8, fontFamily: '"Segoe UI", "Microsoft YaHei", sans-serif', colorText: "#263751"}}}>
    <ProjectLayout project={project} name={name} active={active}><div className="result-content">{children}</div></ProjectLayout>
  </ConfigProvider>;
}
export function Metrics({items}: {items: {title: string; value: number | string; hint: string; icon: ReactNode; tone?: string}[]}) {
  return <div className="result-metrics">{items.map(item => <article key={item.title} className="metric"><span className={`metric-icon ${item.tone || ""}`}>{item.icon}</span><div><div className="metric-title">{item.title}</div><strong>{item.value}</strong><small>{item.hint}</small></div></article>)}</div>;
}
export function RunSelect({runs, value, onChange}: {runs: Run[]; value: string; onChange: (value: string) => void}) {
  return <Select aria-label="选择 TLR 运行" placeholder="选择已有 TLR 运行" value={value || undefined} onChange={onChange} className="run-select" options={runs.map(r => ({value: r.run_id, label: `${new Date(r.created_at).toLocaleString("zh-CN")} · ${label(r.status)} · ${r.run_id.slice(0, 8)}`}))} />;
}
export function exportJson(name: string, value: unknown) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], {type: "application/json"}));
  const a = document.createElement("a"); a.href = url; a.download = name; a.click(); URL.revokeObjectURL(url);
}
