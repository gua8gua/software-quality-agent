# 软件项目资料库

正式入口包含项目资料库和模型配置。项目路径为：所有项目 → 单个项目（资料快照 / TLR 记录）→ 单份资料或检测结果。连接软件质量管理后端，接口失败展示错误，不回退示例数据。工作空间对应后端 tenant_id。

## 首次部署（仅第一次执行）

先按 [后端 README](../../software-quality-management-backend/README.md) 选择 SQLite 或 PostgreSQL 部署。当前工作区已完成 SQLite 初始化，含 SMOS 的 167 份制品。

安装 Node.js 后，在 PowerShell 中进入前端目录安装锁定依赖：

```powershell
cd E:\PyFile\Differentiated_Quality_Management_NG_EIE\projects\0_\software-quality-agent\frontend
npm ci
```

默认配置即可连接本机后端，不必创建前端 `.env`。如需定制，参照 `.env.example` 设置 VITE_QUALITY_API_BASE（默认 `/api/v1/tlr`）、VITE_TENANT_ID（默认 local），修改后重启 Vite。

## 日常启动（部署完成后每次执行）

窗口 1：启动当前本地 SQLite 后端。

```powershell
cd E:\PyFile\Differentiated_Quality_Management_NG_EIE\projects\0_\software-quality-management-backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

窗口 2：启动前端。

```powershell
cd E:\PyFile\Differentiated_Quality_Management_NG_EIE\projects\0_\software-quality-agent\frontend
$env:QUALITY_BACKEND_URL = "http://127.0.0.1:8000"
npm run dev
```

打开 **http://localhost:5173**，工作空间选 `local`；若端口被占用，以 Vite 输出地址为准。Docker 后端用户将窗口 1 命令替换为后端目录的 `docker compose up -d`。

两个窗口保持运行，Ctrl+C 停止，下次重复日常启动即可。无需每次 npm ci、数据库初始化或导入数据。当前页面不需要 Agent 的 8010 服务。

默认 `/api/v1` 由 Vite 代理到 QUALITY_BACKEND_URL；上面的环境变量明确使用 8000，避免沿用测试端口 18080。在 software-quality-agent 根目录执行 npm run dev 会找不到 package.json，必须先进入 frontend。

## 构建部署产物（发布或更新时执行）

```powershell
# frontend 目录；依赖变化时先 npm ci
npm run build
```

此命令检查 TypeScript 并生成 dist，不会启动网站。正式部署需由静态服务器托管 dist，并把同源 `/api/v1` 反向代理到后端；不能直接双击 dist/index.html 作为完整部署。当前本地开发继续使用上面的 npm run dev。

## 使用和保存

1. 总览搜索、进入或创建项目。
2. 项目中选择资料快照，按业务类型筛选清单；TLR 标签展示全部历史运行。
3. 上传时所属项目为当前项目，逐文件必选业务类型，也可批量设置；不会自动推断项目或类型。
4. 输入新版本，上传继承当前快照并新增制品；明确勾选才允许在新快照中替换同标识制品。旧快照和结果保留。
5. 资料详情展示完整正文、JSON、类型、版本、摘要，并提供原始文件下载。
6. “重新进行 TLR 检测”打开层间矩阵，默认选中有正文的相邻非空层，可增选跨层或反向比较。每格产生独立运行并依次执行；手工制品选择入口仍保留。按类型可选整制品、句子、Chunk、Method/Class、章节、模型特征或显式 LLM 文档结构抽取。
7. “结构关系”展示原数据集的关系树，点击节点查看父节点、关联节点和来源元数据。原始关系与模型 TLR 输出分开。运行历史中的层间矩阵可按批次切换、进入某格查看候选和证据。
8. 左侧“模型配置”可选择 DeepSeek 官方 API、本地服务或其他 OpenAI 兼容 API。DeepSeek 只需填写密钥，官方地址由后端维护；每个 API 可展开查看模型级类型、参数和验证状态。Ollama 自动识别对话、向量编码与视觉能力，其他服务可用“设置类型”人工标注。任务下拉框只显示能力匹配或尚待实测的模型。为 TLR 向量化、链接判定和架构结构抽取分别选模型并保存，再点“实测”确认真实任务接口可调用。密钥保存后不回显。

支持 UTF-8 文本/代码、可提取文字的 PDF、DOCX 段落和表格，不做 OCR。单文件 10 MiB、单批 50 件/50 MiB、正文最多 50 万字符；超限报错，整批验证后原子保存。

数据保存在后端 DATABASE_URL 指定数据库：`tlr_projects` 保存项目，`tlr_datasets`/`tlr_artifacts` 保存不可变快照和正文，`tlr_files` 保存原始字节、名称、媒体类型和摘要；TLR 的运行、单元、候选、链接、评测使用对应 tlr 表。浏览器不作为数据库。结果 JSON 导出包含配置、资料清单、单元索引、候选摘要和链接；完整证据通过候选详情接口查询。

真实检测需配置 embedding 和 LLM。模型页中的任务绑定优先于后端 `.env`，更改后无需重启；未绑定的任务继续使用 `.env`。执行接口同步运行，页面独立轮询状态；没有持久任务队列。工作空间输入延续后端作用域约定，不等于登录认证。

## 分层与数据更新

当前 Dronology SAFA 项目保留 13 种原始类型及关系树；只有引用的包/源码节点明确标记并排除模型分析。SMOS 的源码虽以 TXT 保存，已通过 language 元数据标记 Java。详细数据限制、字段与分割基线见 [后端设计说明](../../software-quality-management-backend/docs/tlr-layers-and-structure.md)。旧 SQLite 先执行后端 scripts.upgrade_local_tlr，PostgreSQL 执行 alembic upgrade head。

多任务当前由网页串行请求；关闭页面后未发出的运行仍为 pending，可以进入其详情继续执行。尚未接入持久后台任务队列。

## 基线与模块

- [Eclipse Capra](https://projects.eclipse.org/projects/modeling.capra) 和[图/矩阵介绍](https://www.eclipse.org/community/eclipse_newsletter/2020/december/2.php)：参考跨制品追踪的图与矩阵；本项目展示 LiSSA 流程的证据和链接，不复制 Eclipse/EMF 模型。
- [Cytoscape.js](https://js.cytoscape.org/)：复用图渲染、缩放、平移和事件。源/目标分列，图最多显示前 200 个制品并明确提示；完整数据可查矩阵、列表及导出。
- [FastAPI UploadFile](https://fastapi.tiangolo.com/tutorial/request-files/)：复用 multipart，增加项目归属、业务类型、解析和快照事务。

图只绘制最终正向链接；矩阵区分最终链接、全负判定、未完成、未召回。未召回不等于无关联，相似度不等于概率。点击连线或矩阵单元格查看证据，点击制品查看原文。

根目录运行 `python scripts/fetch_frontend_references.py` 保存原文 HTML、抽取文本和 SHA-256 清单至 `artifacts/frontend-research/`。

`LayerAnalysis.tsx` 管理多选层间矩阵和批次汇总，`Structure.tsx` 管理原始关系树与详情，`ModelConfig.tsx` 管理连接、模型目录和任务绑定。`src/quality/Workspace.tsx` 管理路由与项目页面；`Dialogs.tsx` 管理输入；`Results.tsx` 管理图、矩阵和证据；`api.ts` 管理真实后端契约；`common.tsx`/`styles.css` 管理共用交互与样式。旧原型页面不再挂载。

## 端到端验证

使用独立 SQLite 与确定性测试模型，仅验证功能，不代表模型效果。三个终端分别执行：

```powershell
# 后端目录
.venv/Scripts/python -m uvicorn tests.console_server:app --host 127.0.0.1 --port 18080
# 前端目录
$env:QUALITY_BACKEND_URL='http://127.0.0.1:18080'
npm run dev -- --host 127.0.0.1 --port 15173
# 前端目录，第三个终端
npx playwright install chromium
npx playwright test
```

覆盖创建、上传、原文下载、TLR、证据、历史、移动端和接口错误。截图与失败追踪保存在 `../artifacts/console-qa/`。
