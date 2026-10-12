"""Project conversation SDK role and structured output contract."""

from __future__ import annotations

from typing import Any

from agents import Agent, ModelSettings
from agents.tool import FunctionTool
from pydantic import BaseModel


class ChatAnswer(BaseModel):
    answer: str
    evidence: list[str]
    suggested_actions: list[str]


def create_project_conversation_agent(
    model: Any, query_project_data: FunctionTool, mode: str
) -> Agent:
    agent = Agent(
        name="Project Conversation",
        model=model,
        instructions="你是项目质量问答助手。先查询工具返回的真实项目事实再作答，ID 从列表结果取得。不能编造追溯、审核、证据或完成情况；已完成执行不等于需求满足。只读查询，不触发分析或改动原文。工件是完整文件，canonical node 是文件内节点。证据数组只能引用实际查询到的 ID。当前模式："
        + mode,
        tools=[query_project_data],
        output_type=ChatAnswer,
        model_settings=ModelSettings(temperature=0, parallel_tool_calls=False),
    )
    return agent
