import type { ReactNode } from "react";
import { FileText, FolderOpen, GitBranch, ShieldCheck, ListTodo } from "lucide-react";
import { navigate } from "../navigation";
import { part } from "./api";
import "./project-navigation.css";

export type ProjectSection = "library" | "trace" | "analysis" | "reports" | "tasks";
const sections = [
  { id: "library", label: "项目资料库", suffix: "", icon: FolderOpen },
  { id: "trace", label: "追溯任务", suffix: "/trace", icon: GitBranch },
  { id: "analysis", label: "一致性分析", suffix: "/analysis", icon: ShieldCheck },
  { id: "tasks", label: "任务队列", suffix: "/tasks", icon: ListTodo },
  { id: "reports", label: "质量报告", suffix: "/reports", icon: FileText },
] as const;

/** One project navigation shared by library, creation forms, lists and details. */
export default function ProjectLayout({ project, name, active, children, controls }: {
  project: string; name: string; active: ProjectSection; children: ReactNode; controls?: ReactNode;
}) {
  const root = `/projects/${part(project)}`;
  return <section className="project-layout">
    <header className="project-context-header">
      <div><nav className="project-breadcrumb" aria-label="项目位置"><a href="#/projects">项目管理</a><span>/</span><span>{name || "当前项目"}</span></nav>
        <h1>{name || "当前项目"}</h1></div>
      {controls && <div className="project-context-controls">{controls}</div>}
    </header>
    <nav className="project-section-nav" aria-label="项目功能导航">
      {sections.map(({id, label, suffix, icon: Icon}) => <a key={id} href={`#${root}${suffix}`} className={active === id ? "active" : ""} aria-current={active === id ? "page" : undefined}><Icon size={16} />{label}</a>)}
      <button className="project-list-return" onClick={() => navigate("/projects")}>全部项目</button>
    </nav>
    <div className="project-page-content">{children}</div>
  </section>;
}
