import { lazy, Suspense, useEffect, useState, type ReactNode } from "react";
import { Plus, RefreshCw, Search, Trash2 } from "lucide-react";
import { navigate } from "../navigation";
import { api, part, type Project } from "./api";
import { Alert, Empty, Loading } from "./common";
import { NewProjectDialog } from "./Dialogs";
import ProjectLayout from "./ProjectLayout";
const ProjectLibrary = lazy(() => import("./ProjectLibrary"));
const TracePage = lazy(() => import("./results/TracePage"));
const AnalysisPage = lazy(() => import("./results/AnalysisPage"));
const TaskStartPage = lazy(() => import("./results/TaskStartPage"));
const TaskListPage = lazy(() => import("./results/TaskListPage"));
const AnalysisBatchPage = lazy(() => import("./results/AnalysisBatchPage"));
const TaskBoard = lazy(() => import("./TaskBoard"));

const projectPath = (id: string) => `/projects/${part(id)}`;

export default function ProjectsPanel({ route, tenant, workspaceControl, reportContent }: { route: string[]; tenant: string; workspaceControl?: ReactNode; reportContent?: ReactNode }) {
  if (route[0] === "projects" && route.length === 3 && route[2] === "tasks") {
    return <Suspense fallback={<Loading />}><TaskBoard tenant={tenant} project={route[1]}/></Suspense>;
  }
  if (route[0] === "projects" && route.length === 3 && route[2] === "reports") {
    return <ProjectReports tenant={tenant} project={route[1]}>{reportContent}</ProjectReports>;
  }
  if (route[0] === "projects" && route.length >= 3 && route.length <= 5 && ["trace", "analysis"].includes(route[2])) {
    if (route.length === 3) {
      return <Suspense fallback={<Loading />}><TaskListPage key={`${tenant}/${route.join("/")}`} tenant={tenant} project={route[1]} mode={route[2] as "trace" | "analysis"} /></Suspense>;
    }
    if (route[3] === "start") {
      return <Suspense fallback={<Loading />}><TaskStartPage key={`${tenant}/${route.join("/")}`} tenant={tenant} project={route[1]} mode={route[2] as "trace" | "analysis"} /></Suspense>;
    }
    if (route[2] === "analysis" && route[3] === "batch" && route[4]) {
      return <Suspense fallback={<Loading />}><AnalysisBatchPage key={`${tenant}/${route[4]}`} tenant={tenant} project={route[1]} batchId={route[4]} /></Suspense>;
    }
    const Page = route[2] === "trace" ? TracePage : AnalysisPage;
    return <Suspense fallback={<Loading />}><Page key={`${tenant}/${route.join("/")}/${window.location.hash.split("?")[1] || ""}`} tenant={tenant} project={route[1]} initialRun={route[3]} initialNode={route[4]} /></Suspense>;
  }
  const home = !route.length || (route.length === 1 && route[0] === "projects");
  const projectRoute = route[0] === "projects" && (route.length === 2 || (route.length === 4 && route[2] === "files"));
  return <div className={home ? "project-area" : "project-library-area"}>
    {home ? <ProjectList tenant={tenant} /> : projectRoute ?
      <Suspense fallback={<Loading />}><ProjectLibrary key={`${tenant}/${route[1]}`} tenant={tenant} id={route[1]} selectedFile={route[3]} workspaceControl={workspaceControl} /></Suspense> :
      <Empty title="页面不存在"><button onClick={() => navigate("/projects")}>返回项目列表</button></Empty>}
  </div>;
}

function ProjectReports({tenant, project, children}: {tenant: string; project: string; children: ReactNode}) {
  const [name, setName] = useState(""); const [error, setError] = useState("");
  useEffect(() => { let active = true; api.project(tenant, project).then(p => {if (active) setName(p.name);}).catch(e => {if (active) setError(String(e));}); return () => {active = false;}; }, [tenant, project]);
  return <ProjectLayout project={project} name={name} active="reports">{error && <Alert>{error}</Alert>}{children}</ProjectLayout>;
}

function ProjectList({ tenant }: { tenant: string }) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [create, setCreate] = useState(false);
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const [search, setSearch] = useState("");
  useEffect(() => {
    let active = true; setLoading(true); setError("");
    api.projects(tenant).then(items => { if (active) setProjects(items); })
      .catch(error => { if (active) setError(String(error)); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [tenant, revision]);
  async function remove(project: Project) {
    if (busy || !confirm(`删除项目“${project.name}”及全部文件和关联数据？此操作不可撤销。`)) return;
    setBusy(true);
    try { await api.deleteProject(tenant, project.id); setRevision(value => value + 1); }
    catch (error) { setError(String(error)); } finally { setBusy(false); }
  }
  return <section className="page">
    <div className="toolbar"><div><h1>项目</h1><p className="muted">用文件夹组织需求、设计文档与代码。</p></div>
      <button className="primary" onClick={() => setCreate(true)}><Plus size={16} />新建项目</button></div>
    <div className="inline-controls"><label className="project-search"><Search size={16} /><input aria-label="搜索项目" placeholder="搜索项目名称、标识或说明" value={search} onChange={event => setSearch(event.target.value)} /></label><button disabled={loading} onClick={() => setRevision(value => value + 1)}><RefreshCw size={16} />刷新</button></div>
    {error && <Alert>{error}</Alert>}
    {loading ? <Loading /> : !projects.length ? <Empty title="暂无项目" /> : <div className="project-grid">
      {projects.filter(project => `${project.name} ${project.id} ${project.description}`.toLowerCase().includes(search.toLowerCase())).map(project => <article className="project-card" key={project.id}>
        <button className="project-name" onClick={() => navigate(projectPath(project.id))}>{project.name}</button>
        <code>{project.id}</code><p>{project.description || "暂无说明"}</p>
        <footer><button onClick={() => navigate(projectPath(project.id))}>打开项目</button>
          <button className="danger" disabled={busy} onClick={() => void remove(project)}><Trash2 size={15} />删除</button></footer>
      </article>)}
    </div>}
    {create && <NewProjectDialog tenant={tenant} close={() => setCreate(false)} done={project => navigate(projectPath(project.id))} />}
  </section>;
}
