# Software Quality Agent

面向“通用软件质量管理系统开发”的多 Agent 后端原型，当前重点支持生命周期文档和代码资产的管理、质量问答、项目报告生成、数据库读写，以及大型项目 PDF 的分块式需求抽取。

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
- OpenAI-compatible chat API，可用 OpenAI、DeepSeek、本地或私有模型服务；必须配置 LLM，不再提供 mock 模式

## 多 Agent 划分

- `OrchestratorAgent`：任务路由、上下文汇总、调用子 Agent。
- `EvidenceAgent`：收集项目、文档、代码、测试、trace link 和报告证据，识别缺口。
- `ConversationAgent`：项目质量问答、追踪关系解释、下一步建议。
- `ReportAgent`：生成项目质量总览、需求追踪、覆盖分析和专题报告。
- `DatabaseReadAgent`：受控读取项目库、资产库、追踪关系、报告和审计事件。
- `DatabaseWriteAgent`：受控写入项目、资产、trace link、对话、报告和审计事件。
- `VerifierAgent`：校验报告结构、风险提示和证据完整性。
- `RequirementDecompositionAgent`：本地按段落分批调用 LLM 识别候选需求，再按业务能力合并过细条目，最后由后端去重、编号并执行 Pydantic 校验。

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

## 本地运行

```powershell
python -m pip install -e .
software-quality-agent serve --host 127.0.0.1 --port 8010
```

或者：

```powershell
python -m uvicorn software_quality_agent.server:app --host 127.0.0.1 --port 8010 --reload
```

默认数据库：`data/software_quality_agent.sqlite`。首次启动会写入一个演示项目，用于前端联调。

启动前必须在 `.env` 中配置真实的 OpenAI-compatible LLM：

```env
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=your-api-key
LLM_MODEL=gpt-4o-mini
```

未配置完整时，服务启动会直接报错，不会使用规则或 mock 结果替代 LLM。

## 环境变量

复制 `.env.example` 为 `.env` 后可配置：

- `DATABASE_URL`
- `LLM_PROVIDER`
- `LLM_BASE_URL`
- `LLM_API_KEY`
- `LLM_MODEL`
- `API_CORS_ORIGINS`
