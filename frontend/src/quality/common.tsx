import { X, AlertCircle, LoaderCircle, FileText } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";

export function Alert({ children }: { children: ReactNode }) { return <div className="qm-alert" role="alert"><AlertCircle size={18} /><span>{children}</span></div>; }
export function Loading() { return <div className="qm-empty" role="status"><LoaderCircle className="qm-spin" size={25} /><p>正在读取项目数据…</p></div>; }
export function Empty({ title, children }: { title: string; children?: ReactNode }) { return <div className="qm-empty"><FileText size={30} /><h3>{title}</h3>{children}</div>; }
export function Modal({ title, close, children, wide = false }: { title: string; close: () => void; children: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { const dialog = ref.current!; dialog.showModal(); return () => dialog.close(); }, []);
  return <dialog ref={ref} className={`qm-modal ${wide ? "qm-modal-wide" : ""}`} onCancel={event => { event.preventDefault(); close(); }}>
    <header><h2>{title}</h2><button type="button" className="qm-icon" aria-label="关闭" onClick={close}><X size={20} /></button></header>
    {children}
  </dialog>;
}
export function Pager({ page, total, size, set }: { page: number; total: number; size: number; set: (page: number) => void }) {
  return <div className="qm-pager"><span>共 {total} 条 · 第 {page + 1} / {Math.max(1, Math.ceil(total / size))} 页</span><button disabled={page === 0} onClick={() => set(page - 1)}>上一页</button><button disabled={(page + 1) * size >= total} onClick={() => set(page + 1)}>下一页</button></div>;
}
