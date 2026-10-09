"""Read-only project query tool for the SDK console conversation."""

from __future__ import annotations

import json
from typing import Literal
from urllib.parse import quote

from agents import function_tool
from agents.tool import FunctionTool

from ..review_runtime.context import BackendClient


def create_project_query_tool(backend: BackendClient, prefix: str) -> FunctionTool:
    @function_tool(failure_error_function=None)
    async def query_project_data(
        resource: Literal["artifacts", "artifact", "node", "runs", "run", "links"],
        identifier: str = "",
        node_id: str = "",
        offset: int = 0,
    ) -> str:
        """读取已保存项目事实，先列出工件或运行记录取得真实 ID。

        artifact/node/run 使用前次结果返回的 identifier。links 要求
        identifier=run_id，并提供 canonical 查询返回的真实 node_id。
        offset 使用返回的 next_offset；查询 node 时表示 text_start。
        此工具不执行 TLR、检索、embedding 或评审。
        """
        if offset < 0:
            raise ValueError("offset must be nonnegative")
        paths = {
            "artifacts": "/artifacts",
            "artifact": f"/artifacts/{quote(identifier, safe='')}",
            "node": f"/nodes/{quote(identifier, safe='')}",
            "runs": "/tlr-runs",
            "run": f"/tlr-runs/{quote(identifier, safe='')}",
            "links": f"/tlr-runs/{quote(identifier, safe='')}/nodes/{quote(node_id, safe='')}/links",
        }
        if resource not in {"artifacts", "runs"} and not identifier:
            raise ValueError("identifier is required")
        if resource == "links" and not node_id:
            raise ValueError("node_id is required")
        params = (
            {"text_start": offset, "text_limit": 4000}
            if resource == "node"
            else {"offset": offset, "limit": 10}
        )
        return json.dumps(
            await backend.get(prefix + "/information" + paths[resource], params), ensure_ascii=False
        )

    return query_project_data
