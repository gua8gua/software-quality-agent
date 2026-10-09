import { X, AlertCircle, LoaderCircle, FileText } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";

export function Alert({ children }: { children: ReactNode }) { return <div className="qm-alert" role="alert"><AlertCircle size={18} /><span>{children}</span></div>; }
export function Loading() { return <div className="qm-empty" role="status"><LoaderCircle className="qm-spin" size={25} /><p>正在读取项目数据…</p></div>; }
export function Empty({ title, children }: { title: string; children?: ReactNode }) { return <div className="qm-empty"><FileText size={30} /><h3>{title}</h3>{children}</div>; }
export function Modal({ title, close, children }: { title: string; close: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { const dialog = ref.current!; dialog.showModal(); return () => dialog.close(); }, []);
  return <dialog ref={ref} className="qm-modal" onCancel={event => { event.preventDefault(); close(); }}>
    <header><h2>{title}</h2><button type="button" className="qm-icon" aria-label="关闭" onClick={close}><X size={20} /></button></header>
    {children}
  </dialog>;
}
