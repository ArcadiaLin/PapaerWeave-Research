"""PaperWeave 的 MCP 服务（stdio）：把 :data:`paperweave.tools.TOOLS`（算子与版本记录的读取接口）作为 MCP 工具提供给
通用 Agent。

    python -m paperweave.mcp       # 由 MCP 客户端启动；实验目录的 .pi/mcp.json 由 python -m paperweave.workspace 生成

每个算子与读取接口是一个工具：工具名就是它的名称，工具按 ``server.yml`` 装配（:mod:`paperweave.mcp.spec`），
调用经 ``Operator.call``，与命令行入口（:mod:`paperweave.cli`）的结果相同。结果以 YAML 文本返回；``status`` 为
``rejected``、``blocked`` 或 ``conflict`` 时标为 ``isError``，内容照样交给模型。

**调用环境。** MCP 调用不带客户端的会话与模型，所以 CheckIn 记下的 ``session`` 由服务进程启动时生成（一个客户端
会话对应一个服务进程）。写入者的身份由连接配置给出，相当于登录：``PAPERWEAVE_USER`` 是编辑者，记为提交的作者与
Artifact 的 ``formed_by``；Commit 的 ``by`` 可以省略（取登录身份），写了就必须相同。``PAPERWEAVE_AGENT`` 是所用的
Agent 与模型，记入提交的 ``meta.agent``。写入者无法自己声明身份。

环境变量：``PAPERWEAVE_NEO4J_URI`` 等连接参数（:mod:`paperweave.config`）；``PAPERWEAVE_USER`` 登录身份，写入时记为
编辑者；``PAPERWEAVE_AGENT`` 所用的 Agent 与模型；
``PAPERWEAVE_ENABLE_COMMIT=1`` 时才列出 ``Commit``（它改动知识本身）；``PAPERWEAVE_READ_ONLY=1`` 时只列出不写入的
工具，``PAPERWEAVE_HIDE_TOOLS`` 中的工具不列出；
``PAPERWEAVE_EVIDENCE_SCOPE=artifacts`` 时 ReadEvidence 只读 Artifact 的文档，不读论文原文（:func:`scoped`）；
``PAPERWEAVE_NO_EMBED=1`` 时关闭查询向量，写入后也不补算；
``PAPERWEAVE_MCP_LOG`` 给出日志文件（追加写）；``PAPERWEAVE_WORKDIR`` 是写者的工作目录，草稿文件（``doc_file``、
``artifact_doc``）只从这里读，FetchArtifact 也取到这里，不设时取服务进程的当前目录；``PAPERWEAVE_WORKDIR_ALIAS``
是写者看到的同一目录（如沙箱中的 ``/work``，见 :mod:`paperweave.draft`）。库没有版本记录时服务不启动。

**日志。** 每次调用记一行：会话、工具、结果状态，以及执行前对参数的兜底修复（:mod:`paperweave.operators.repair`）。
修复不告诉模型，只记在这里；日志写到 stderr，给了 ``PAPERWEAVE_MCP_LOG`` 时也写入该文件。
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
from ..store import Store, UnversionedDatabaseError, check_versioned, open_graph
from ..tools import TOOLS
from .spec import Spec, load

log = logging.getLogger("paperweave.mcp")


def enabled(spec: Spec) -> dict[str, types.Tool]:
    """列出的工具：``Commit`` 只在 ``PAPERWEAVE_ENABLE_COMMIT=1`` 时列出；``PAPERWEAVE_READ_ONLY=1`` 时只列出不写入的工具
    （读者：查找、读取与历史，不能写 Artifact，也不能提交）；``PAPERWEAVE_HIDE_TOOLS`` 中逗号分隔的工具不列出。"""
    commit = os.environ.get("PAPERWEAVE_ENABLE_COMMIT") == "1"
    read_only = os.environ.get("PAPERWEAVE_READ_ONLY") == "1"
    hidden = set(filter(None, os.environ.get("PAPERWEAVE_HIDE_TOOLS", "").split(",")))
    return {
        name: t
        for name, t in spec.tools.items()
        if (name != "Commit" or commit) and not (read_only and TOOLS[name].writes) and name not in hidden
    }


def scoped(tools: dict[str, types.Tool]) -> tuple[dict[str, types.Tool], dict[str, Operator]]:
    """``PAPERWEAVE_EVIDENCE_SCOPE=artifacts`` 时把 ReadEvidence 换成只读产物文档的版本，说明中补一句。T1 中只读库的读者
    这样设置：库的内容都能读，论文原文不能读（产物存在集中式的库中，ReadEvidence 是读产物文档的途径）。"""
    ops = dict(TOOLS)
    if os.environ.get("PAPERWEAVE_EVIDENCE_SCOPE") != "artifacts" or "ReadEvidence" not in tools:
        return tools, ops
    base = TOOLS["ReadEvidence"]
    ops["ReadEvidence"] = replace(base, execute=_artifacts_only(base))
    note = " In this session only artifact documents can be read; source papers are not available."
    tool = tools["ReadEvidence"]
    return {**tools, "ReadEvidence": tool.model_copy(update={"description": (tool.description or "") + note})}, ops


def _artifacts_only(base: Operator):
    def execute(ctx: Context, request: Any) -> dict[str, Any]:
        return read_evidence(ctx.store, **params_of(base.name, base.parameters, request), artifacts_only=True)

    return execute


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
    from ..config import DATA, NEO4J_DB, NEO4J_URI
    from ..store.embedding import embed, sync_embeddings
    from ..store.graph import driver

    _logging(os.environ.get("PAPERWEAVE_MCP_LOG"))
    spec = load()

    no_embed = os.environ.get("PAPERWEAVE_NO_EMBED") == "1"
    formed_by = os.environ.get("PAPERWEAVE_USER") or None
    agent = os.environ.get("PAPERWEAVE_AGENT") or None
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


__all__ = ["enabled", "main", "serve"]
