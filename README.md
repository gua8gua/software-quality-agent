# Software Quality Agent 启动说明

## 安装依赖

使用 Python 3.11 或 3.12、Node.js 22.12+。在项目根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
if (!(Test-Path .env)) { Copy-Item .env.example .env }
npm --prefix frontend ci
```

编辑项目根目录 `.env`：

```dotenv
DATABASE_URL=sqlite+aiosqlite:///./data/software_quality_agent.sqlite
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://你的模型服务/v1
LLM_API_KEY=你的密钥
LLM_MODEL=你的模型名称
LLM_TIMEOUT_SECONDS=60
QUALITY_BACKEND_URL=http://127.0.0.1:8000
```

## 开发启动

- `GET /api/health`
- `GET /api/projects`
- `GET /api/chat/history?project_id=...`
- `POST /api/chat`
- `GET /api/reports?project_id=...`
- `POST /api/reports/generate`
- `POST /api/requirements/extract`
- `POST /api/requirements/coverage`
- `GET /api/database/schema`
- `POST /api/database/read`
- `POST /api/database/write`
先按照 [质量后端启动说明](../software-quality-management-backend/README.md) 启动 8000 端口服务。

在 Agent 项目根目录的第一个终端执行：

```powershell
.\.venv\Scripts\python.exe -m software_quality_agent.cli serve --host 127.0.0.1 --port 8010
```

在同一目录的第二个终端执行：

```powershell
$env:QUALITY_BACKEND_URL = "http://127.0.0.1:8000"
$env:AGENT_BACKEND_URL = "http://127.0.0.1:8010"
npm --prefix frontend run dev
```

打开 `http://localhost:5173`。项目资料库为 `http://localhost:5173/#/projects`，模型配置为 `http://localhost:5173/#/models`。

## 构建与启动

```powershell
npm --prefix frontend run build
.\.venv\Scripts\python.exe -m software_quality_agent.cli serve --host 0.0.0.0 --port 8010
```

保持质量后端在 `.env` 的 `QUALITY_BACKEND_URL` 地址运行。打开 `http://localhost:8010`；其他设备使用服务器 IP 和 8010 端口访问。

Agent 接口文档：`http://localhost:8010/docs`。健康检查：`http://localhost:8010/api/health`。

## 停止

在服务终端按 `Ctrl+C`。
