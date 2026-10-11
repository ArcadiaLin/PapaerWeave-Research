"""PaperWeave 的 MCP 服务（stdio）：把 :data:`e09.tools.TOOLS`（算子与版本记录的读取接口）作为 MCP 工具提供给
通用 Agent。

    python -m e09.mcp       # 由 MCP 客户端启动；实验目录的 .pi/mcp.json 由 python -m e09.workspace 生成

每个算子与读取接口是一个工具：工具名就是它的名称，工具按 ``server.yml`` 装配（:mod:`e09.mcp.spec`），
调用经 ``Operator.call``，与命令行入口（:mod:`e09.cli`）的结果相同。结果以 YAML 文本返回；``status`` 为
``rejected``、``blocked`` 或 ``conflict`` 时标为 ``isError``，内容照样交给模型。

**调用环境。** MCP 调用不带客户端的会话与模型，所以 Agent 算子的 ``session`` 由服务进程启动时生成（一个客户端
会话对应一个服务进程）。写入者的身份由连接配置给出，相当于登录：``E09_USER`` 是形成者，记为 Artifact 的
``formed_by``；Commit 的 ``by`` 可以省略（取登录身份），写了就必须相同。``E09_AGENT`` 是所用的 Agent 与模型，记入
提交的 ``meta.agent``。写入者无法自己声明身份。

环境变量：``E09_NEO4J_URI`` 等连接参数（:mod:`e09.config`）；``E09_USER`` 登录身份，Agent 算子写入时必需；
``E09_AGENT`` 所用的 Agent 与模型；
``E09_ENABLE_COMMIT=1`` 时才列出 ``Commit``（它改动知识本身）；``E09_NO_EMBED=1`` 时关闭查询向量，写入后也不补算；
``E09_MCP_LOG`` 给出日志文件（追加写）。库没有版本记录时服务不启动。

**日志。** 每次调用记一行：会话、工具、结果状态，以及执行前对参数的兜底修复（:mod:`e09.operators.repair`）。
修复不告诉模型，只记在这里；日志写到 stderr，给了 ``E09_MCP_LOG`` 时也写入该文件。
"""

from __future__ import annotations

import logging
import os
import secrets
import sys
from datetime import UTC, datetime
from typing import Any

import anyio
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from ..operators import Context
from ..operators.base import rejected
from ..store import Store, UnversionedDatabaseError, check_versioned, open_graph
from ..tools import TOOLS
from .spec import Spec, load

log = logging.getLogger("e09.mcp")


def enabled(spec: Spec) -> dict[str, types.Tool]:
    """列出的工具：``Commit`` 只在 ``E09_ENABLE_COMMIT=1`` 时列出。"""
    commit = os.environ.get("E09_ENABLE_COMMIT") == "1"
    return {name: t for name, t in spec.tools.items() if name != "Commit" or commit}


def serve(
    store: Store,
    *,
    session: str,
    formed_by: str | None,
    sync: Any,
    spec: Spec | None = None,
    agent: str | None = None,
) -> Server:
    """MCP 服务：调用逐个执行（同一时间只有一个写入，不与自己的写入冲突）。"""
    spec = spec or load()
    server: Server = Server(spec.name, version=spec.version, instructions=spec.instructions)
    tools = enabled(spec)
    lock = anyio.Lock()

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return list(tools.values())

    @server.call_tool(validate_input=False)  # 参数由算子核对，错误与命令行同形
    async def call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        op = TOOLS[name] if name in tools else None
        if op is None:
            result = rejected([{"rule": "format", "at": "tool", "msg": f"one of {list(tools)}"}])
        else:
            at = datetime.now(UTC).isoformat(timespec="seconds")
            ctx = Context(store, at=at, session=session, formed_by=formed_by, agent=agent, sync=sync)
            async with lock:
                result = await anyio.to_thread.run_sync(op.call, ctx, arguments or {})
        status = result.details.get("status", "ok")
        log.info("%s %s %s%s", session, name, status, "".join(f"\n  repaired {r}" for r in result.repairs))
        return types.CallToolResult(content=[types.TextContent(type="text", text=result.text)], isError=result.is_error)

    return server


def main() -> int:
    from ..config import DATA, NEO4J_DB, NEO4J_URI
    from ..store.embedding import embed, sync_embeddings
    from ..store.graph import driver

    _logging(os.environ.get("E09_MCP_LOG"))
    spec = load()

    no_embed = os.environ.get("E09_NO_EMBED") == "1"
    formed_by = os.environ.get("E09_USER") or None
    agent = os.environ.get("E09_AGENT") or None
    session = f"mcp-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"
    try:
        check_versioned(driver, database=NEO4J_DB)
    except UnversionedDatabaseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        driver.close()
        return 2
    graph = open_graph(driver, database=NEO4J_DB, file_root=DATA)
    store = Store(driver, graph, DATA, database=NEO4J_DB, embed=None if no_embed else embed)
    sync = None if no_embed else sync_embeddings
    server = serve(store, session=session, formed_by=formed_by, sync=sync, spec=spec, agent=agent)
    log.info(
        "%s %s (server.yml %s): session %s, user %s, agent %s, %s",
        spec.name,
        spec.version,
        spec.digest,
        session,
        formed_by,
        agent,
        NEO4J_URI,
    )

    async def run() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    try:
        anyio.run(run)
    finally:
        driver.close()
    return 0


def _logging(path: str | None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if path:
        handlers.append(logging.FileHandler(path, encoding="utf-8"))
    root = logging.getLogger("e09")  # 服务自己的记录与各算子的记录（如 e09.search 的排名依据）
    for handler in handlers:
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        root.addHandler(handler)
    root.setLevel(logging.INFO)


__all__ = ["enabled", "main", "serve"]
