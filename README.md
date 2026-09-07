# Software Quality Agent

## 项目资料库前端

`frontend/` 当前正式入口包含“项目资料库”和“模型配置”。项目入口支持本地上传、显式选择业务类型、新快照、重新检测和证据可视化；模型入口展示本地/远程 OpenAI 兼容模型，保存 API 密钥并为 TLR 任务选择模型。启动、存储、可视化基线与端到端测试见 [frontend/README.md](frontend/README.md)。

## 部署与启动
进入 `frontend` 子目录：

```powershell
$env:QUALITY_BACKEND_URL = "http://127.0.0.1:8000"
npm run dev
```

## 开发与协作规范（Git Workflow）

采用特性分支工作流与 Pull Request 审查机制，参照工作区 `日志/README.md`。

- `main` 用于稳定发布，`develop` 用于开发集成；禁止直接在这两个分支开发或推送，通过 PR 合并。
- 每次开发前先保存当前改动，切换并同步 `develop`，再创建 `feature/姓名缩写-功能` 或 `bugfix/姓名缩写-问题`。如果远程尚无 `develop`，由维护者建立集成分支，不默认向 `main` 提交功能 PR。
- 按模块小步提交，使用 `feat`、`fix`、`docs`、`refactor`、`test`、`style`、`chore` 提交前缀。
- 开发期间及时合并最新 `develop`，尽早解决冲突；定期推送自己的特性分支备份，禁止强推公共分支。
- PR 选择 `base: develop`，写明行为变化、相关基线、数据或接口影响、验证结果，由同事审查后合并。
- Agent、工具、数据接入和界面按模块协作；跨模块接口和数据库结构变化在 PR 中明确，避免把业务逻辑堆入编排器。
- 不提交密钥、`.env`、IDE 配置、虚拟环境、`node_modules/`、数据库、日志、模型缓存与构建产物。原始数据放 `datasets/` 并保留来源、版本和许可；抽取与转换结果放 `data/`、`artifacts/` 或 `outputs/`。

```bash
git switch develop
git pull --ff-only origin develop
git switch -c feature/yourname-topic
# 开发、验证，按实际修改文件 git add 后提交
git commit -m "feat: describe the change"
git fetch origin
git merge origin/develop
git push -u origin feature/yourname-topic
# 创建 PR：feature/yourname-topic -> develop；审查合并后再清理
git switch develop
git pull --ff-only origin develop
git branch -d feature/yourname-topic
```

面向“通用软件质量管理系统开发”的多 Agent 后端原型，当前重点支持生命周期文档和代码资产的管理、质量问答、项目报告生成、数据库读写。

## 参考基线

- [DocAgent](https://github.com/facebookresearch/DocAgent)：借鉴 `Reader / Searcher / Writer / Verifier / Orchestrator` 的分工方式。
- [RepoAgent](https://github.com/OpenBMB/RepoAgent)：借鉴仓库级结构化文档、Git 变更感知、代码结构分析和持续更新思路。
- [OpenHands Software Agent SDK](https://github.com/OpenHands/software-agent-sdk)：借鉴 `Agent / Tool / Conversation / Workspace` 的组合式 Agent 架构。
- [Open WebUI](https://github.com/open-webui/open-webui)、[LibreChat](https://github.com/danny-avila/LibreChat)、[AnythingLLM](https://github.com/Mintplex-Labs/anything-llm)：借鉴左侧导航、主工作区、多会话和管理控制台式 UI。

## 技术栈

- Python 3.11+
- FastAPI
- SQLAlchemy Async ORM
- SQLite + aiosqlite，后续可切 PostgreSQL
- OpenAI-compatible chat API，可用本地或私有模型服务；未配置时使用 mock LLM

## 多 Agent 划分

- `OrchestratorAgent`：任务路由、上下文汇总、调用子 Agent。
- `EvidenceAgent`：收集项目、文档、代码、测试、trace link 和报告证据，识别缺口。
- `ConversationAgent`：项目质量问答、追踪关系解释、下一步建议。
- `ReportAgent`：生成项目质量总览、需求追踪、覆盖分析和专题报告。
- `DatabaseReadAgent`：受控读取项目库、资产库、追踪关系、报告和审计事件。
- `DatabaseWriteAgent`：受控写入项目、资产、trace link、对话、报告和审计事件。
- `VerifierAgent`：校验报告结构、风险提示和证据完整性。

## 接口

- `GET /api/health`
- `GET /api/projects`
- `GET /api/chat/history?project_id=...`
- `POST /api/chat`
- `GET /api/reports?project_id=...`
- `POST /api/reports/generate`
- `GET /api/database/schema`
- `POST /api/database/read`
- `POST /api/database/write`

## 目录结构

```text
software-quality-agent/
├─ README.md                              # 项目入口、部署方式与协作规范
├─ .env.example                           # Agent 服务与 OpenAI 兼容模型配置示例
├─ pyproject.toml                         # Python 3.11+、FastAPI、SQLAlchemy 等依赖
├─ src/software_quality_agent/            # 可独立运行的多 Agent 后端原型
│  ├─ agents.py                           # 编排、证据、问答、报告、读写与校验 Agent
│  ├─ service.py                          # Agent 调度和业务服务
│  ├─ store.py                            # 项目、制品、追踪关系、报告等本地持久化
│  ├─ schemas.py                          # 请求与响应模型
│  ├─ server.py                           # FastAPI 接口及前端静态资源入口
│  ├─ config.py                           # 数据库、模型、跨域等配置
│  └─ cli.py                              # software-quality-agent 命令行入口
├─ frontend/                              # 当前正式使用的质量管理工作台
│  ├─ src/
│  │  ├─ App.tsx                          # 应用入口与页面切换
│  │  ├─ api.ts / types.ts / mock.ts      # Agent 原型接口、类型与模拟数据
│  │  └─ quality/                         # 对接质量管理后端的项目资料库界面
│  │     ├─ Workspace.tsx                 # 文件上传、快照与检测工作区
│  │     ├─ Structure.tsx                 # 生命周期层级和检测矩阵配置
│  │     ├─ ModelConfig.tsx               # 本地/远程模型配置
│  │     ├─ Results.tsx                   # TLR 结果与证据展示
│  │     ├─ LayerAnalysis.tsx             # 分层分析
│  │     ├─ Dialogs.tsx / common.tsx      # 对话框与公共组件
│  │     └─ api.ts / styles.css           # 后端 API 封装与页面样式
│  ├─ e2e/console.spec.ts                 # Playwright 端到端测试
│  ├─ package.json / package-lock.json
│  ├─ vite.config.ts / playwright.config.ts
│  └─ README.md                           # 前端部署、测试和交互基线
├─ datasets/                              # 原始/整理后的公开数据集与来源清单
│  ├─ knowledge-base/                     # 外置知识库及标准目录
│  ├─ lissa-smos-req2code/                # SMOS 需求—代码及金标准链接
│  ├─ arta-requirement-testability/       # 需求可测试性数据
│  ├─ SAFA-Artifacts/                     # SAFA 原始制品、图和论文
│  ├─ safa-dronology-v0-v1/               # Dronology V0/V1 简化数据
│  ├─ Dronology-Community-Datasets/       # Dronology 数据来源占位/说明
│  ├─ irrelevant-requirements/            # 无关需求 ARFF 数据
│  ├─ manifest.json                       # 数据集来源与校验清单
│  └─ README.md
├─ data/
│  ├─ research/quality_route_2026-09-04/  # 路线调研论文和 sources.json
│  └─ software_quality_agent.sqlite       # 多 Agent 原型本地数据库
├─ artifacts/                             # 控制台 QA、前端参考资料等中间产物
├─ docs/                                  # 多 Agent 设计、参考记录、存储能力检查
└─ scripts/                               # 知识库下载/校验与前端参考资料抓取
```