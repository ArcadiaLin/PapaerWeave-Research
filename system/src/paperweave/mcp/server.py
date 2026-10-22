"""PaperWeave 的 MCP 服务（stdio）：把 :data:`paperweave.tools.TOOLS` 作为 MCP 工具提供给通用 Agent。

    python -m paperweave.mcp       # 由 MCP 客户端启动；实验目录的 .pi/mcp.json 由 python -m paperweave.workspace 生成

每个工具按 ``server.yml`` 装配（:mod:`paperweave.mcp.spec`），调用经 ``Operator.call``，与命令行入口
（:mod:`paperweave.cli`）的结果相同。读取工具返回带注释的 YAML，其余以 YAML 文本返回；``status`` 为 ``rejected``、
``blocked`` 或 ``conflict`` 时标为 ``isError``，内容照样交给模型。启动时按当前库生成总览，附在 ``search`` 的说明末尾
（:func:`paperweave.query.overview.overview`）：服务每个连接启动一次，总览是会话开始时的快照。

**调用环境。** 会话由服务进程启动时生成（一个客户端会话对应一个服务进程）。写入者的身份由连接配置给出，相当于登录：
``PAPERWEAVE_USER`` 记为提交的作者与产物的 ``formed_by``，写入者无法自己声明。``PAPERWEAVE_AGENT`` 是所用的 Agent
与模型，记入提交的 ``meta.agent``。

环境变量：``PAPERWEAVE_NEO4J_URI`` 等连接参数（:mod:`paperweave.config`）；``PAPERWEAVE_USER``；``PAPERWEAVE_AGENT``；
``PAPERWEAVE_READ_ONLY=1`` 时只列出不写入的工具，``PAPERWEAVE_HIDE_TOOLS`` 中逗号分隔的工具不列出；
``PAPERWEAVE_EVIDENCE_SCOPE=artifacts`` 时 read_evidence 只读产物文档，不读来源（:func:`scoped`）；
``PAPERWEAVE_SOURCES`` 是只读来源目录（:mod:`paperweave.query.sources`）；
``PAPERWEAVE_NO_EMBED=1`` 时关闭查询向量，写入后也不补算；``PAPERWEAVE_MCP_LOG`` 给出日志文件（追加写）；
``PAPERWEAVE_WORKDIR`` 是写者的工作目录，commit 的文件只从这里读，checkout 也写到这里，不设时取服务进程的当前目录；
``PAPERWEAVE_WORKDIR_ALIAS`` 是写者看到的同一目录（见 :mod:`paperweave.draft`）。库没有版本记录时服务不启动。

**日志。** 每次调用记一行：会话、工具、结果状态，以及执行前对参数的兜底修复（:mod:`paperweave.operators.repair`）。
"""

from __future__ import annotations

import logging
import os
import secrets
import sys
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import anyio
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from ..draft import Workdir
from ..operators import Context
from ..operators.base import Operator, params_of, rejected
from ..operators.db.read_evidence import read_evidence
from ..query.overview import overview
from ..store import Store, UnversionedDatabaseError, check_versioned, open_graph, setup_database
from ..tools import TOOLS
from .spec import Spec, load

log = logging.getLogger("paperweave.mcp")


def enabled(spec: Spec) -> dict[str, types.Tool]:
    """列出的工具：``PAPERWEAVE_READ_ONLY=1`` 时只列出不写入的工具；``PAPERWEAVE_HIDE_TOOLS`` 中的工具不列出。"""
    read_only = os.environ.get("PAPERWEAVE_READ_ONLY") == "1"
    hidden = set(filter(None, os.environ.get("PAPERWEAVE_HIDE_TOOLS", "").split(",")))
    return {
        name: t
        for name, t in spec.tools.items()
        if not (read_only and TOOLS[name].writes) and name not in hidden
    }


SCOPE_NOTES = {
    "artifacts": " In this session only artifact documents can be read; sources are not available.",
}


def scoped(tools: dict[str, types.Tool]) -> tuple[dict[str, types.Tool], dict[str, Operator]]:
    """``PAPERWEAVE_EVIDENCE_SCOPE`` 为 ``artifacts`` 时把 read_evidence 换成限定范围的版本，说明中补一句。"""
    ops = dict(TOOLS)
    scope = os.environ.get("PAPERWEAVE_EVIDENCE_SCOPE") or None
    if scope is not None and scope not in SCOPE_NOTES:  # 拼错时不能悄悄放开原文
        raise ValueError(f"PAPERWEAVE_EVIDENCE_SCOPE must be one of {sorted(SCOPE_NOTES)}, not {scope!r}")
    if scope is None or "read_evidence" not in tools:
        return tools, ops
    base = TOOLS["read_evidence"]
    ops["read_evidence"] = replace(base, execute=_scoped(base, scope))
    tool = tools["read_evidence"]
    note = SCOPE_NOTES[scope]
    return {**tools, "read_evidence": tool.model_copy(update={"description": (tool.description or "") + note})}, ops


def _scoped(base: Operator, scope: str):
    def execute(ctx: Context, request: Any) -> dict[str, Any]:
        return read_evidence(ctx.store, **params_of(base.name, base.parameters, request), scope=scope)

    return execute


def with_overview(spec: Spec, store: Store) -> Spec:
    """``search`` 的说明末尾附上库的总览；生成失败时只记日志。"""
    if "search" not in spec.tools:
        return spec
    try:
        text = overview(store)
    except Exception as exc:  # noqa: BLE001 —— 总览只是提示
        log.warning("overview failed: %s", exc)
        return spec
    tool = spec.tools["search"]
    tools = {**spec.tools, "search": tool.model_copy(update={"description": f"{tool.description}\n\n{text}"})}
    return replace(spec, tools=tools)


def serve(
    store: Store,
    *,
    session: str,
    formed_by: str | None,
    sync: Any,
    spec: Spec | None = None,
    agent: str | None = None,
    workdir: Workdir | None = None,
) -> Server:
    """MCP 服务：调用逐个执行（同一时间只有一个写入，不与自己的写入冲突）。"""
    spec = spec or load()
    server: Server = Server(spec.name, version=spec.version, instructions=spec.instructions)
    tools, ops = scoped(enabled(spec))
    lock = anyio.Lock()

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return list(tools.values())

    @server.call_tool(validate_input=False)  # 参数由算子核对，错误与命令行同形
    async def call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        op = ops[name] if name in tools else None
        if op is None:
            result = rejected([{"rule": "format", "at": "tool", "msg": f"one of {list(tools)}"}])
        else:
            at = datetime.now(UTC).isoformat(timespec="seconds")
            ctx = Context(
                store, at=at, session=session, formed_by=formed_by, agent=agent, sync=sync, workdir=workdir
            )
            async with lock:
                result = await anyio.to_thread.run_sync(op.call, ctx, arguments or {})
        status = result.details.get("status", "ok")
        log.info("%s %s %s%s", session, name, status, "".join(f"\n  repaired {r}" for r in result.repairs))
        return types.CallToolResult(content=[types.TextContent(type="text", text=result.text)], isError=result.is_error)

    return server


def main() -> int:
    from ..config import DATA, NEO4J_DB, NEO4J_URI, SOURCES
    from ..store.derived import sync as sync_derived
    from ..store.embedding import embed
    from ..store.graph import connect

    _logging(os.environ.get("PAPERWEAVE_MCP_LOG"))
    spec = load()

    no_embed = os.environ.get("PAPERWEAVE_NO_EMBED") == "1"
    formed_by = os.environ.get("PAPERWEAVE_USER") or None
    agent = os.environ.get("PAPERWEAVE_AGENT") or None
    session = f"mcp-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"
    driver = connect()
    try:
        check_versioned(driver, database=NEO4J_DB)
    except UnversionedDatabaseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        driver.close()
        return 2
    graph = open_graph(driver, database=NEO4J_DB, file_root=DATA)
    setup_database(graph, driver, database=NEO4J_DB)  # 空库也有 main 分支与索引：读取工具不必区分“没有索引”与“没有结果”
    store = Store(driver, graph, DATA, database=NEO4J_DB, embed=None if no_embed else embed, source_root=SOURCES)
    def sync(touched: list[str] | None = None) -> int:
        return sync_derived(driver, NEO4J_DB, None if no_embed else embed, touched)

    spec = with_overview(spec, store)
    workdir = Workdir.from_env()
    server = serve(store, session=session, formed_by=formed_by, sync=sync, spec=spec, agent=agent, workdir=workdir)
    log.info(
        "%s %s (server.yml %s): session %s, user %s, agent %s, %s, workdir %s",
        spec.name,
        spec.version,
        spec.digest,
        session,
        formed_by,
        agent,
        NEO4J_URI,
        workdir.root,
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
    root = logging.getLogger("paperweave")  # 服务自己的记录与各算子的记录（如 paperweave.search 的排名依据）
    for handler in handlers:
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        root.addHandler(handler)
    root.setLevel(logging.INFO)


__all__ = ["enabled", "main", "serve", "with_overview"]
