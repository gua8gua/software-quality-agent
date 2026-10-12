import { useEffect, useRef, useState } from "react";
import { getDocument, GlobalWorkerOptions } from "pdfjs-dist";
import { EventBus, PDFLinkService, PDFViewer } from "pdfjs-dist/web/pdf_viewer.mjs";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import "pdfjs-dist/web/pdf_viewer.css";
import { renderAsync } from "docx-preview";
import { originalUrl, part, projectUrl, type Artifact } from "./api";
import { Alert, Loading } from "./common";

GlobalWorkerOptions.workerSrc = workerUrl;
const DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

// Official PDFViewer example: mozilla/pdf.js/examples/components/simpleviewer.mjs.
function PdfPreview({ bytes }: { bytes: ArrayBuffer }) {
  const container = useRef<HTMLDivElement>(null);
  const viewerElement = useRef<HTMLDivElement>(null);
  const [error, setError] = useState("");
  const [pages, setPages] = useState(0);
  const [renderedPage, setRenderedPage] = useState(0);
  useEffect(() => {
    let active = true;
    const eventBus = new EventBus();
    const links = new PDFLinkService({ eventBus });
    const assets = new URL(`${import.meta.env.BASE_URL}pdfjs/`, window.location.href).href;
    const viewer = new PDFViewer({ container: container.current!, viewer: viewerElement.current!, eventBus, linkService: links, imageResourcesPath: `${assets}images/` });
    links.setViewer(viewer);
    eventBus.on("pagesinit", () => { if (active) viewer.currentScaleValue = "page-width"; });
    eventBus.on("pagerendered", (event: { error?: Error; pageNumber: number }) => {
      if (!active) return;
      if (event.error) setError(String(event.error)); else setRenderedPage(event.pageNumber);
    });
    const task = getDocument({ data: new Uint8Array(bytes.slice(0)), cMapUrl: `${assets}cmaps/`, cMapPacked: true,
      standardFontDataUrl: `${assets}standard_fonts/`, wasmUrl: `${assets}wasm/` });
    task.promise.then(document => {
      if (!active) return;
      setPages(document.numPages); viewer.setDocument(document); links.setDocument(document);
    }).catch(error => { if (active) setError(String(error)); });
    // The published 6.3 type omits null, but its official setDocument source
    // explicitly supports null to cancel rendering, reset pages and detach.
    return () => { active = false; Reflect.apply(viewer.setDocument, viewer, [null]); links.setDocument(null); void task.destroy(); };
  }, [bytes]);
  return <>{error && <Alert>{error}</Alert>}<p className="muted">PDF.js 原始文件预览{pages ? ` · ${pages} 页` : " · 正在加载"}</p>
    <div className="pdf-frame" data-renderer="pdfjs" data-rendered-page={renderedPage}><div className="pdf-scroll" ref={container}><div className="pdfViewer" ref={viewerElement} /></div></div></>;
}

function DocxPreview({ bytes }: { bytes: ArrayBuffer }) {
  const iframe = useRef<HTMLIFrameElement>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const [rendered, setRendered] = useState(false);
  useEffect(() => {
    if (!ready) return;
    let active = true;
    const document = iframe.current?.contentDocument;
    if (!document) { setError("无法访问隔离的 DOCX 预览容器"); return; }
    const host = document.createElement("div"); document.body.replaceChildren(host);
    // Only the library's stable renderAsync API; no text/JSON intermediate.
    renderAsync(bytes.slice(0), host, host, { breakPages: true, ignoreLastRenderedPageBreak: false,
      ignoreWidth: false, ignoreHeight: false, ignoreFonts: false, renderHeaders: true, renderFooters: true,
      renderFootnotes: true, renderEndnotes: true, renderAltChunks: false, useBase64URL: true })
      .then(() => { if (active) setRendered(true); }).catch(error => { if (active) setError(String(error)); });
    return () => { active = false; host.remove(); };
  }, [bytes, ready]);
  return <>{error && <Alert>{error}</Alert>}<p className="muted">docx-preview 原始文件预览 · {rendered ? "已渲染" : "正在渲染"}。分页依赖文件已有分页信息，不保证与 Word 完全一致。</p>
    <iframe ref={iframe} title="DOCX 原文件预览" className="docx-frame" sandbox="allow-same-origin" data-renderer="docx-preview"
      onLoad={() => setReady(true)} srcDoc={'<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; img-src data: blob:; font-src data: blob:"></head><body style="margin:0"></body></html>'} />
  </>;
}

export function OriginalFilePreview({ tenant, project, file, close }: { tenant: string; project: string; file: Artifact; close: () => void }) {
  const [bytes, setBytes] = useState<ArrayBuffer>();
  const [error, setError] = useState("");
  const mime = file.media_type.split(";")[0].trim().toLowerCase();
  const supported = mime === "application/pdf" || mime === DOCX || mime.startsWith("text/");
  useEffect(() => {
    if (!supported) return;
    const controller = new AbortController();
    fetch(originalUrl(file), { signal: controller.signal }).then(async response => {
      if (!response.ok) throw new Error(`读取原始文件失败：HTTP ${response.status}`);
      if (response.headers.get("Content-Type")?.split(";")[0].trim().toLowerCase() !== mime) throw new Error("原文件 MIME 与工件元数据不一致，已停止预览");
      const data = await response.arrayBuffer();
      if (!controller.signal.aborted) setBytes(data);
    }).catch(error => { if (!controller.signal.aborted) setError(String(error)); });
    return () => controller.abort();
  }, [file.id, file.original_file_url, mime, supported]);
  let text = "";
  if (bytes && mime.startsWith("text/")) {
    try { text = new TextDecoder("utf-8", { fatal: true }).decode(bytes); }
    catch { text = "原文件不是有效 UTF-8，无法直接预览，请下载查看。"; }
  }
  return <article className="preview">
    <header className="toolbar"><div><h2>{file.filename}</h2><span className="muted">{file.file_format || "未知格式"} · {file.media_type}</span></div>
      <div className="actions"><a className="button" href={projectUrl(tenant, `/${part(project)}/artifacts/${part(file.id)}/download`)}>下载原文件</a><button onClick={close}>关闭预览</button></div></header>
    {error ? <Alert>{error}</Alert> : !supported ? <Alert>{mime === "application/msword" ? "旧版 DOC 文件不受 DOCX 渲染器支持，不会伪装成 DOCX。请下载原文件查看。" : `不支持直接预览此原始格式（${file.media_type}），请下载查看。`}</Alert> :
      !bytes ? <Loading /> : mime === "application/pdf" ? <PdfPreview bytes={bytes} /> : mime === DOCX ? <DocxPreview bytes={bytes} /> : <pre className="raw-text" data-renderer="original-text">{text}</pre>}
  </article>;
}
