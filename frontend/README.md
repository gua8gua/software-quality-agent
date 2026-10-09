# 前端启动说明

## 安装

使用 Node.js 22.12+，在 `frontend` 目录执行：

```powershell
npm ci
```

按照 [质量后端启动说明](../../software-quality-management-backend/README.md) 启动 8000 服务。开发模式不依赖 Agent 模型服务。

## 开发启动

```powershell
$env:QUALITY_BACKEND_URL = "http://127.0.0.1:8000"
npm run dev
```

打开 `http://localhost:5173`。

| 页面 | 地址 |
| --- | --- |
| 项目资料库 | `http://localhost:5173/#/projects` |

项目页只保留文本、代码两类顶层数据。文本子类只有需求说明文档、设计说明文档。保留文件夹父子层级、上传、原文预览、下载和删除。没有 TLR、审核、建议、图谱、批次或历史类型兼容页面。

详情页使用后端返回的真实 MIME 和 `original_file_url` 读取原文件字节。PDF 使用 npm 稳定版 `pdfjs-dist`（PDF.js）及官方 PDFViewer；DOCX 使用 `docx-preview.renderAsync`，在隔离 iframe 中保留表格、图片、页眉页脚及文件已有分页。DOCX 渲染器受 HTML 布局限制，不保证与 Word 完全一致。旧 DOC 仅提供下载，不伪装 DOCX。UTF-8 文本和代码直接显示原文件内容，不读取抽取 JSON。PDF worker、CMap、字体、WASM 随构建本地发布，不依赖 CDN。

## 构建与启动

在 `frontend` 目录执行：

```powershell
npm run build
```

在 Agent 项目根目录执行：

```powershell
.\.venv\Scripts\python.exe -m software_quality_agent.cli serve --host 0.0.0.0 --port 8010
```

保持质量后端运行，打开 `http://localhost:8010`。

## 配置地址

开发代理使用 `QUALITY_BACKEND_URL`。发布服务使用 Agent 根目录 `.env` 的 `QUALITY_BACKEND_URL`。

管理 API 唯一基址为 `VITE_PROJECT_API_BASE`（默认 `/api/v1`），调用 `/projects` 及其子资源。没有旧 `/tlr` API 适配。默认租户通过 `VITE_TENANT_ID` 设置。

## 停止

在服务终端按 `Ctrl+C`。
