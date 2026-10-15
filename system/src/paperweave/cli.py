"""算子与版本记录读取接口的命令行入口：读一份请求（YAML），按 ``op`` 交给对应的工具，输出结果。

    python -m paperweave <请求.yml | -> [--no-embed] [--session 会话 --formed-by 形成者]
    python -m paperweave -e '{op: Traverse, start: [method_0028], path: [{rel: EVALUATES, dir: in}]}'
    python -m paperweave <文档.yml> --source <来源标签> [--apply] [--message 说明] [--base 提交 id] [--no-dedup]

请求的 ``op`` 是任一算子或读取接口（见 :mod:`paperweave.tools`），其余键是它的参数。直接给一份 graph-doc
（以 ``graph-doc:`` 开头）时视为 ``Commit``，``--source`` 等选项给出它的参数。写入时可给出
``--session`` 与 ``--formed-by``（调用环境的信息，不写在请求中）；FetchArtifact 与 CheckIn 读写写者的工作目录，只经
MCP 入口。作为 MCP 工具提供给 Agent 的入口见
:mod:`paperweave.mcp`。连接、文档目录与向量服务用 ``PAPERWEAVE_NEO4J_URI`` 所指的库、
``paperweave.config.DATA`` 与 ``EMBED_URL``；``--no-embed`` 关闭查询向量，写入后也不补算向量。写入前建立约束与
索引。没有版本记录的旧库一律拒绝。

退出码：0 表示有结果（可以是空结果，或写入、重试命中、dry_run 通过）；1 表示错误结果（``status`` 为 ``rejected``、
``blocked`` 或 ``conflict``，``errors`` 列出原因）；2 表示库不能使用。
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from graph_doc import GraphDocError, load

from .operators import Context
from .operators.base import rejected
from .store import Store, UnversionedDatabaseError, check_versioned, open_graph
from .tools import call


def request_of(text: str, args: argparse.Namespace) -> dict[str, Any]:
    """命令行给出的请求；graph-doc 视为 ``Commit``，其参数来自命令行选项。"""
    request = load(text)
    if isinstance(request, dict) and "graph-doc" in request:
        commit = {"op": "Commit", "doc": text, "source": args.source, "apply": args.apply, "dedup": not args.no_dedup}
        if args.message:
            commit["message"] = args.message
        if args.base:
            commit["base"] = args.base
        return {k: v for k, v in commit.items() if v is not None}
    return request


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.expr is not None:
        text = args.expr
    elif args.request == "-":
        text = sys.stdin.read()
    elif args.request is not None:
        text = Path(args.request).read_text(encoding="utf-8")
    else:
        print("error: give a request file, - or -e", file=sys.stderr)
        return 1

    from .config import DATA, NEO4J_DB
    from .store.embedding import embed, sync_embeddings
    from .store.graph import driver

    graph = open_graph(driver, database=NEO4J_DB, file_root=DATA)
    store = Store(driver, graph, DATA, database=NEO4J_DB, embed=None if args.no_embed else embed)
    ctx = Context(
        store,
        at=datetime.now(UTC).isoformat(timespec="seconds"),
        session=args.session,
        formed_by=args.formed_by,
        sync=None if args.no_embed else sync_embeddings,
        text=text,
    )
    try:
        check_versioned(driver, database=NEO4J_DB)
        try:
            request = request_of(text, args)
        except GraphDocError as exc:
            out = rejected([{"rule": "format", "at": "request", "msg": str(exc)}])
        else:
            out = call(ctx, request)
    except UnversionedDatabaseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        driver.close()
    sys.stdout.write(out.text)
    return 1 if out.is_error else 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m paperweave", description=__doc__.split("\n\n")[0])
    parser.add_argument("request", nargs="?", help="请求文件路径；- 表示从标准输入读取")
    parser.add_argument("-e", "--expr", help="直接给出请求（YAML 文本）")
    parser.add_argument("--no-embed", action="store_true", help="关闭查询向量，写入后也不补算向量")
    agent = parser.add_argument_group("写入时（调用环境）")
    agent.add_argument("--session", help="调用所在的会话；Commit 不给 --source 时记为来源")
    agent.add_argument("--formed-by", help="登录身份（模型或人），记为提交的作者")
    commit = parser.add_argument_group("直接给出 graph-doc 时（Commit）")
    commit.add_argument("--source", help="来源标签，记入提交的 source 与 NameKey.registered_from")
    commit.add_argument("--apply", action="store_true", help="提交；不加时只做 dry_run")
    commit.add_argument("--message", help="提交说明")
    commit.add_argument("--base", help="写入者读视图时所在的提交 id，只记录")
    commit.add_argument("--no-dedup", action="store_true", help="不查重，用于种子这类可信的批量入库")
    return parser


__all__ = ["main", "request_of"]
