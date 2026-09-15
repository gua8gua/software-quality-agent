# 前端启动说明

## 安装

使用 Node.js 22.12+，在 `frontend` 目录执行：

```powershell
npm ci
```

按照 [Agent 启动说明](../README.md) 启动 8010 服务，按照 [质量后端启动说明](../../software-quality-management-backend/README.md) 启动 8000 服务。

## 开发启动

```powershell
$env:AGENT_BACKEND_URL = "http://127.0.0.1:8010"
$env:QUALITY_BACKEND_URL = "http://127.0.0.1:8000"
npm run dev
```

打开 `http://localhost:5173`。

| 页面 | 地址 |
| --- | --- |
| 对话 | `http://localhost:5173/#/chat` |
| 报告生成 | `http://localhost:5173/#/report` |
| 需求拆分 | `http://localhost:5173/#/requirements` |
| 数据库读写 | `http://localhost:5173/#/database` |
| 项目资料库 | `http://localhost:5173/#/projects` |
| 模型配置 | `http://localhost:5173/#/models` |

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

开发代理使用 `AGENT_BACKEND_URL` 和 `QUALITY_BACKEND_URL`。发布服务使用 Agent 根目录 `.env` 的 `QUALITY_BACKEND_URL`。

需要浏览器直接访问指定接口时，在 `frontend/.env` 设置 `VITE_AGENT_API_BASE`、`VITE_QUALITY_API_BASE`；`VITE_QUALITY_API_BASE` 填写到 `/api/v1/tlr`。设置后重新启动开发服务或重新构建。默认工作空间可通过 `VITE_TENANT_ID` 设置。

## 停止

在服务终端按 `Ctrl+C`。
