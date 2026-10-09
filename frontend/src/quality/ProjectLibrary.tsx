import { lazy, Suspense, useEffect, useMemo, useState, type ReactNode } from "react";
import { Button, ConfigProvider, Dropdown, Input, Select, Table, Tag, Tooltip, Tree, type TableColumnsType, type TreeDataNode } from "antd";
import zhCN from "antd/locale/zh_CN";
import { ChevronRight, Clock3, Code2, Download, Eye, FileText, Folder as FolderIcon, FolderOpen, GitBranch, MoreHorizontal, Plus, RefreshCw, Search, ShieldCheck, Trash2, Upload, X } from "lucide-react";
import { navigate } from "../navigation";
import { api, part, projectUrl, typeLabel, type Artifact, type DocumentRole, type Folder, type Modality, type Project } from "./api";
import { Alert, Loading } from "./common";
import { NewFolderDialog, UploadDialog } from "./Dialogs";
import { LibrarySplit } from "./LibrarySplit";
import ProjectLayout from "./ProjectLayout";
import "./project-library.css";

const OriginalFilePreview = lazy(() => import("./OriginalFilePreview").then(module => ({default: module.OriginalFilePreview})));
const ROOT = "$root";
const path = (id: string) => `/projects/${part(id)}`;
type Row = { key: string; kind: "folder"; folder: Folder } | { key: string; kind: "file"; file: Artifact };

function trail(folders: Folder[], id: string | null): Folder[] {
  const byId = new Map(folders.map(item => [item.id, item]));
  const result: Folder[] = [], visited = new Set<string>();
  let current = id ? byId.get(id) : undefined;
  while (current && !visited.has(current.id)) {
    visited.add(current.id); result.unshift(current);
    current = current.parent_id ? byId.get(current.parent_id) : undefined;
  }
  return result;
}

function folderTree(folders: Folder[]): TreeDataNode[] {
  const root: TreeDataNode = {key: ROOT, title: "根目录", icon: <FolderOpen size={18} />, children: []};
  const nodes = new Map(folders.map(folder => [folder.id, {
    key: folder.id, title: folder.name, icon: <FolderIcon size={18} />, children: [],
  } as TreeDataNode]));
  for (const folder of [...folders].sort((a, b) => a.name.localeCompare(b.name, "zh-CN"))) {
    const parent = folder.parent_id ? nodes.get(folder.parent_id) : root;
    parent?.children?.push(nodes.get(folder.id)!);
  }
  return [root];
}

export function fileSize(value: number | null): string {
  if (value == null) return "—";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}
function date(value: string | null): string {
  if (!value || !Number.isFinite(Date.parse(value))) return "—";
  return new Intl.DateTimeFormat("zh-CN", {timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false}).format(new Date(value));
}
function format(file: Artifact): string {
  const mime = file.media_type.split(";")[0].trim().toLowerCase();
  if (mime === "application/pdf") return "PDF";
  if (mime === "application/vnd.openxmlformats-officedocument.wordprocessingml.document") return "DOCX";
  if (mime === "application/msword") return "DOC";
  return file.file_format.toUpperCase() || "未知";
}
function FileIcon({file, large = false}: {file: Artifact; large?: boolean}) {
  const type = format(file);
  return <span className={`library-file-icon ${large ? "large" : ""} ${type === "PDF" ? "pdf" : file.modality === "code" ? "code" : ""}`} aria-hidden="true">
    {type === "DOCX" || type === "DOC" ? <span className="word-glyph">W</span> : file.modality === "code" ? <Code2 size={large ? 28 : 21} /> : <FileText size={large ? 28 : 21} />}
  </span>;
}
function FileTags({file}: {file: Artifact}) {
  return <><Tag color={format(file) === "PDF" ? "red" : "blue"}>{format(file)}</Tag><Tag color={file.engineering_role === "requirement" ? "green" : "blue"}>{typeLabel(file)}</Tag></>;
}

export default function ProjectLibrary({tenant, id, selectedFile, workspaceControl}: {
  tenant: string; id: string; selectedFile?: string; workspaceControl?: ReactNode;
}) {
  const [project, setProject] = useState<Project>();
  const [folders, setFolders] = useState<Folder[]>([]);
  const [files, setFiles] = useState<Artifact[]>([]);
  const [folder, setFolder] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string[]>([ROOT]);
  const [modality, setModality] = useState<Modality>("text");
  const [role, setRole] = useState<DocumentRole | "all">("all");
  const [query, setQuery] = useState("");
  const [fileFormat, setFileFormat] = useState("all");
  const [sort, setSort] = useState("recent");
  const [focused, setFocused] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [dialog, setDialog] = useState<"folder" | "upload" | null>(null);
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true; setLoading(true); setError("");
    Promise.all([api.project(tenant, id), api.folders(tenant, id), api.artifacts(tenant, id)]).then(([project, folders, files]) => {
      if (active) { setProject(project); setFolders(folders); setFiles(files); }
    }).catch(error => { if (active) setError(String(error)); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [tenant, id, revision]);

  const routeFile = files.find(file => file.id === selectedFile);
  useEffect(() => {
    if (!routeFile) return;
    setFolder(routeFile.folder_id); setModality(routeFile.modality); setFocused(routeFile.id);
    setRole("all"); setQuery(""); setFileFormat("all");
    setExpanded(keys => [...new Set([...keys, ROOT, ...trail(folders, routeFile.folder_id).map(item => item.id)])]);
  }, [routeFile?.id, routeFile?.folder_id, routeFile?.modality, folders]);

  const tree = useMemo(() => folderTree(folders), [folders]);
  const currentTrail = trail(folders, folder);
  const directoryFiles = files.filter(file => file.folder_id === folder && file.modality === modality);
  const formats = [...new Set(files.filter(file => file.modality === modality).map(format))].sort();
  const textCount = files.filter(file => file.modality === "text").length;
  const latest = files.map(file => file.uploaded_at).filter((value): value is string => !!value).sort((a, b) => Date.parse(b) - Date.parse(a))[0] || null;
  const selected = selectedFile ? routeFile : files.find(file => file.id === focused);
  const selectedPath = selected ? "/" + [...trail(folders, selected.folder_id).map(item => item.name), selected.filename].join("/") : "";
  const download = (file: Artifact) => projectUrl(tenant, `/${part(id)}/artifacts/${part(file.id)}/download`);
  const rows: Row[] = [
    ...folders.filter(item => item.parent_id === folder && item.name.toLowerCase().includes(query.toLowerCase())).map(item => ({key: "folder:" + item.id, kind: "folder" as const, folder: item})),
    ...directoryFiles.filter(file => (role === "all" || file.engineering_role === role) && (fileFormat === "all" || format(file) === fileFormat) && file.filename.toLowerCase().includes(query.toLowerCase()))
      .sort((a, b) => sort === "name" ? a.filename.localeCompare(b.filename, "zh-CN") : sort === "size" ? (b.size_bytes ?? -1) - (a.size_bytes ?? -1) : (Date.parse(b.uploaded_at || "") || 0) - (Date.parse(a.uploaded_at || "") || 0))
      .map(file => ({key: "file:" + file.id, kind: "file" as const, file})),
  ];

  function openFolder(next: string | null) {
    setFolder(next); setFocused(null); setQuery("");
    setExpanded(keys => [...new Set([...keys, ROOT, ...trail(folders, next).map(item => item.id)])]);
    navigate(path(id));
  }
  function switchModality(next: Modality) {
    setModality(next); setRole("all"); setFileFormat("all"); setFocused(null); setQuery("");
    navigate(path(id));
  }
  function clearSelection() { setFocused(null); navigate(path(id)); }
  function selectFile(file: Artifact) { setFocused(file.id); if (selectedFile) navigate(path(id)); }
  function preview(file: Artifact) { navigate(`${path(id)}/files/${part(file.id)}`); }
  async function removeFile(file: Artifact) {
    if (busy || !confirm(`删除“${file.filename}”？同时清除本项目基于旧文件产生的关联分析数据。此操作不可撤销。`)) return;
    setBusy(true); setError("");
    try { await api.deleteFile(tenant, id, file.id); if (focused === file.id) clearSelection(); setRevision(value => value + 1); }
    catch (error) { setError(String(error)); } finally { setBusy(false); }
  }
  async function removeFolder(item: Folder) {
    if (busy || !confirm(`删除空文件夹“${item.name}”？`)) return;
    setBusy(true); setError("");
    try { await api.deleteFolder(tenant, id, item.id); setRevision(value => value + 1); }
    catch (error) { setError(String(error)); } finally { setBusy(false); }
  }
  function changed() { setDialog(null); setRevision(value => value + 1); }

  const columns: TableColumnsType<Row> = [
    {title: "名称", key: "name", width: 340, render: (_, row) => <button className="library-filename" title={row.kind === "file" ? row.file.filename : row.folder.name} onClick={event => {event.stopPropagation(); row.kind === "folder" ? openFolder(row.folder.id) : selectFile(row.file);}}>
      {row.kind === "folder" ? <span className="library-file-icon"><FolderIcon size={22} /></span> : <FileIcon file={row.file} />}
      <span>{row.kind === "folder" ? row.folder.name : row.file.filename}</span>
    </button>},
    {title: "格式", key: "format", width: 85, render: (_, row) => row.kind === "folder" ? <span className="library-muted">文件夹</span> : <Tag color={format(row.file) === "PDF" ? "red" : "blue"}>{format(row.file)}</Tag>},
    {title: "所属分类", key: "role", width: 125, render: (_, row) => row.kind === "folder" ? "—" : <Tag color={row.file.engineering_role === "requirement" ? "green" : "blue"}>{typeLabel(row.file)}</Tag>},
    {title: "上传时间", key: "date", width: 150, render: (_, row) => row.kind === "folder" ? "—" : date(row.file.uploaded_at)},
    {title: "大小", key: "size", width: 85, render: (_, row) => row.kind === "folder" ? "—" : fileSize(row.file.size_bytes)},
    {title: "操作", key: "actions", width: 142, render: (_, row) => <div className="library-row-actions" onClick={event => event.stopPropagation()}>
      {row.kind === "file" && <><Tooltip title="查看原文件"><Button type="text" aria-label={`查看原文件 ${row.file.filename}`} icon={<Eye size={16} />} onClick={() => preview(row.file)} /></Tooltip>
        <Tooltip title="下载原文件"><Button type="text" href={download(row.file)} aria-label={`下载 ${row.file.filename}`} icon={<Download size={16} />} /></Tooltip></>}
      {row.kind === "file" && row.file.modality === "text" && <Dropdown menu={{items: [{key: "trace", label: row.file.engineering_role === "requirement" ? "设为源工件 · 新建追溯" : "设为目标工件 · 新建追溯"}, {key: "analysis", label: "基于此工件新建一致性分析"}], onClick: ({key}) => navigate(path(id) + `/${key}/start?${row.file.engineering_role === "requirement" ? "source" : "target"}=${part(row.file.id)}`)}} trigger={["click"]}><Button type="text" aria-label={`工件任务操作 ${row.file.filename}`} icon={<MoreHorizontal size={16} />} /></Dropdown>}
      <Tooltip title={row.kind === "file" ? "删除文件及其关联分析数据" : "仅可删除空文件夹"}><Button danger type="text" disabled={busy} aria-label={row.kind === "file" ? `删除文件 ${row.file.filename}` : `删除文件夹 ${row.folder.name}`} icon={<Trash2 size={16} />} onClick={() => void (row.kind === "file" ? removeFile(row.file) : removeFolder(row.folder))} /></Tooltip>
    </div>},
  ];

  if (!project && loading) return <Loading />;
  if (!project) return <Alert>{error || "项目不存在"}</Alert>;
  return <ConfigProvider locale={zhCN} theme={{token: {colorPrimary: "#2b69f1", borderRadius: 7, colorBorder: "#e2e8f1", fontSize: 14, colorText: "#172843", fontFamily: "Inter, Segoe UI, Microsoft YaHei, sans-serif"}, components: {Table: {headerBg: "#f8fafd", rowSelectedBg: "#edf3ff", cellPaddingBlock: 12}, Tree: {nodeSelectedBg: "#eaf1ff", titleHeight: 36}}}}>
    <ProjectLayout project={id} name={project.name} active="library" controls={workspaceControl}><section className="project-library" aria-label="项目数据查看">
      <header className="library-hero">
        <div><nav className="library-project-crumb" aria-label="项目位置"><button onClick={() => navigate("/projects")}>项目列表</button><span>/</span><span>{project.name}</span><span>/</span><strong>项目资料库</strong></nav>
          <h1>项目资料库</h1><p>集中管理项目中的文本资料、代码资料与目录结构</p></div>
        <div className="library-workspace">{workspaceControl}</div>
      </header>
      <section className="library-stats" aria-label="项目统计">
        {[{label: "文本资料", value: textCount, icon: <FileText size={27} />}, {label: "代码文件", value: files.length - textCount, icon: <Code2 size={29} />}, {label: "文件夹", value: folders.length, icon: <FolderIcon size={28} />}, {label: "最近上传", value: latest ? date(latest) : "暂无上传", icon: <Clock3 size={27} />}].map(item => <div className="library-stat" key={item.label}><span>{item.icon}</span><div><small>{item.label}</small><strong>{item.value}</strong></div></div>)}
      </section>
      <section className="library-surface">
        <header className="library-project-heading"><h2><span><FolderOpen size={25} /></span>项目资料库</h2></header>
        {project.description && <p className="library-description">{project.description}</p>}
        <nav className="library-modality" aria-label="数据类型"><Button type={modality === "text" ? "primary" : "default"} icon={<FileText size={18} />} onClick={() => switchModality("text")}>文本</Button><Button type={modality === "code" ? "primary" : "default"} icon={<Code2 size={20} />} onClick={() => switchModality("code")}>代码</Button></nav>
        {error && <Alert>{error}</Alert>}
        {modality === "text" && <nav className="library-subtypes" aria-label="文本子类">{([{value: "all", label: "全部"}, {value: "requirement", label: "需求说明文档"}, {value: "design", label: "设计说明文档"}] as const).map(item => <Button key={item.value} className={role === item.value ? "active" : ""} onClick={() => {setRole(item.value); clearSelection();}}>{item.label}（{directoryFiles.filter(file => item.value === "all" || file.engineering_role === item.value).length}）</Button>)}<small>当前目录</small></nav>}
        <LibrarySplit storageKey={`library-width:${tenant}:${id}`}>
          <aside className="library-directory"><header><h3>目录结构</h3><Tooltip title="在当前目录新建文件夹"><Button aria-label="新建文件夹" icon={<Plus size={16} />} onClick={() => setDialog("folder")} /></Tooltip></header>
            <Tree blockNode showIcon selectedKeys={[folder || ROOT]} expandedKeys={expanded} onExpand={keys => setExpanded(keys.map(String))} treeData={tree} onSelect={keys => {if (keys.length) openFolder(keys[0] === ROOT ? null : String(keys[0]));}} />
            <p>按目录组织文件，文本与代码共享目录结构。</p>
          </aside>
          <div className="library-content">
            <section className="library-table-card">
              <header className="library-file-toolbar"><div><h3>文件列表</h3><nav className="library-directory-crumb" aria-label="当前目录"><button onClick={() => openFolder(null)}>根目录</button>{currentTrail.map(item => <span key={item.id}><ChevronRight size={12} /><button onClick={() => openFolder(item.id)}>{item.name}</button></span>)}</nav></div>
                <div className="library-controls"><Input aria-label="搜索文件名" allowClear prefix={<Search size={15} />} placeholder="搜索文件名…" value={query} onChange={event => setQuery(event.target.value)} />
                  <Select aria-label="筛选文件格式" value={fileFormat} onChange={setFileFormat} options={[{value: "all", label: "格式：全部"}, ...formats.map(value => ({value, label: value}))]} />
                  <Select aria-label="文件排序" value={sort} onChange={setSort} options={[{value: "recent", label: "最近上传"}, {value: "name", label: "名称排序"}, {value: "size", label: "大小排序"}]} />
                  <Tooltip title="刷新文件列表"><Button aria-label="刷新文件列表" loading={loading} icon={<RefreshCw size={16} />} onClick={() => setRevision(value => value + 1)} /></Tooltip>
                  <Button type="primary" icon={<GitBranch size={16} />} onClick={() => navigate(path(id) + "/trace/start")}>新建追溯</Button><Button type="primary" icon={<ShieldCheck size={16} />} onClick={() => navigate(path(id) + "/analysis/start")}>新建一致性分析</Button>
                  <Button icon={<FolderIcon size={16} />} onClick={() => setDialog("folder")}>新建文件夹</Button><Button type="primary" icon={<Upload size={16} />} onClick={() => setDialog("upload")}>上传文件</Button>
                </div>
              </header>
              <Table<Row> className="library-table" rowKey="key" columns={columns} dataSource={rows} loading={loading} scroll={{x: 930}} pagination={{pageSize: 12, hideOnSinglePage: true, showSizeChanger: false}} rowClassName={row => row.kind === "file" && row.file.id === focused ? "library-selected-row" : ""}
                onRow={row => ({onClick: () => row.kind === "folder" ? openFolder(row.folder.id) : selectFile(row.file), onDoubleClick: () => row.kind === "file" && preview(row.file)})} locale={{emptyText: <div className="library-empty"><FolderOpen size={32} /><strong>{query || role !== "all" || fileFormat !== "all" ? "没有匹配的文件" : `当前目录暂无${modality === "text" ? "文本资料" : "代码文件"}`}</strong><span>可切换目录、调整筛选，或上传新文件。</span></div>}} />
            </section>
            {selected && <article className="library-file-detail" aria-label="选中文件详情"><header><FileIcon file={selected} large /><div className="library-detail-title"><h3>{selected.filename}</h3><FileTags file={selected} /></div><div className="library-detail-actions"><Button icon={<Eye size={17} />} onClick={() => preview(selected)}>查看原文件</Button><Button type="primary" href={download(selected)} icon={<Download size={17} />}>下载</Button><Button type="text" aria-label="关闭文件详情" icon={<X size={17} />} onClick={clearSelection} /></div></header>
              <dl>{[{label: "文件大小", value: fileSize(selected.size_bytes)}, {label: "文件格式", value: format(selected)}, {label: "所属分类", value: typeLabel(selected)}, {label: "上传时间", value: date(selected.uploaded_at)}, {label: "版本", value: selected.revision}, {label: "资料路径", value: selectedPath}].map(item => <div key={item.label}><dt>{item.label}</dt><dd title={item.value}>{item.value}</dd></div>)}</dl>
              <p className="library-mime">MIME：{selected.media_type}</p>
            </article>}
            {selectedFile && (routeFile ? <div className="library-original-preview"><Suspense fallback={<Loading />}><OriginalFilePreview key={routeFile.id} tenant={tenant} project={id} file={routeFile} close={() => navigate(path(id))} /></Suspense></div> : !loading && <Alert>文件不存在。</Alert>)}
          </div>
        </LibrarySplit>
      </section>
      {dialog === "folder" && <NewFolderDialog tenant={tenant} project={id} parent={folder} close={() => setDialog(null)} done={changed} />}
      {dialog === "upload" && <UploadDialog tenant={tenant} project={id} folder={folder} modality={modality} close={() => {setDialog(null); setRevision(value => value + 1);}} done={changed} />}
    </section></ProjectLayout>
  </ConfigProvider>;
}
