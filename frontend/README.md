# Software Quality UI

质量管理工作台前端，包含三个核心界面：

- 对话
- 指定项目报告生成
- 数据库读写

## 技术栈

- React
- Vite
- TypeScript
- lucide-react

## 运行

```powershell
npm install
npm run dev
```

默认连接 `http://127.0.0.1:8010`，可通过 `VITE_AGENT_API_BASE` 覆盖。

## 交互

- 左侧切换项目和功能区
- 对话页用于质量问答和追踪解释
- 报告页用于指定项目报告生成
- 数据库页用于受控读写和模式查看

后端未启动时会自动回退到本地 mock 数据，便于先看界面。
