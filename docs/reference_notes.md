# 参考项目说明

## DocAgent

适合借鉴：

- 层次化遍历代码和上下文
- `Reader / Searcher / Writer / Verifier` 分工
- 生成与校验分离
- Orchestrator 控制多轮补充上下文

## RepoAgent

适合借鉴：

- 仓库级结构建模
- Git 变更感知
- AST、依赖关系和项目结构分析
- 持续维护项目文档

## OpenHands Software Agent SDK

适合借鉴：

- `Agent / Tool / Conversation / Workspace` 统一抽象
- 本地工作区和远程工作区模型
- 工具注册、任务运行和事件流
- 多 Agent 协作和子任务委派

## Open WebUI / LibreChat / AnythingLLM

适合借鉴：

- 左侧导航 + 主工作区的控制台布局
- 对话、资料、报告、配置分区
- 会话历史和模型/知识库配置入口
- 可扩展的管理界面

## 本项目第一阶段采用方式

- 后端按领域 Agent 划分，不直接复制通用 Agent 框架，先保证质量管理任务闭环。
- 前端先做三块核心界面：对话、指定项目报告生成、数据库读写。
- 数据层先存项目、资产、trace link、对话、报告和审计，后续再加结构化需求、测试用例、代码单元和质量指标。
