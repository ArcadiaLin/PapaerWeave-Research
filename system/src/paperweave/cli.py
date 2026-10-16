"""工具的命令行入口：读一份请求（YAML），按 ``op`` 交给对应的工具，输出结果。

    python -m paperweave <请求.yml | -> [--no-embed] [--user 登录身份]
    python -m paperweave -e '{op: traverse, start: [method_0028], path: [{rel: EVALUATES, dir: in}]}'
    python -m paperweave <graph-doc.yaml> [--apply] [--message 说明] [--user 登录身份]

请求的 ``op`` 是任一工具（见 :mod:`paperweave.tools`），其余键是它的参数。直接给一份 graph-doc 文件（以
``graph-doc:`` 开头）时视为 ``commit``，工作目录是文件所在的目录，不加 ``--apply`` 时只检查（``dry_run``）。
其余读写工作目录的工具（``checkout``）以当前目录为工作目录。作为 MCP 工具提供给 Agent 的入口见
:mod:`paperweave.mcp`。连接与材料根目录见 :mod:`paperweave.config`；``--no-embed`` 关闭查询向量，写入后也不补算向量。

退出码：0 表示有结果；1 表示错误结果（``status`` 为 ``rejected``、``blocked`` 或 ``conflict``）；2 表示库不能使用。
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from graph_doc import GraphDocError, load

from .draft import Workdir
from .operators import Context
from .operators.base import rejected
from .store import Store, UnversionedDatabaseError, check_versioned, open_graph, setup_database
from .tools import call


def request_of(text: str, path: Path | None, args: argparse.Namespace) -> tuple[dict[str, Any], Path]:
    """命令行给出的请求与工作目录；graph-doc 文件视为 ``commit``。"""
    request = load(text)
    if isinstance(request, dict) and "graph-doc" in request:
        if path is None:
            raise GraphDocError("give a graph-doc as a file, so that commit can read it from its directory")
        commit = {"op": "commit", "files": [path.name], "message": args.message or path.name, "dry_run": not args.apply}
        return commit, path.parent
    return request, Path.cwd()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    path = None
    if args.expr is not None:
        text = args.expr
    elif args.request == "-":
        text = sys.stdin.read()
    elif args.request is not None:
        path = Path(args.request).resolve()
        text = path.read_text(encoding="utf-8")
    else:
        print("error: give a request file, - or -e", file=sys.stderr)
        return 1

    from .config import DATA, NEO4J_DB
    from .store.derived import sync
    from .store.embedding import embed
    from .store.graph import connect

    driver = connect()
    graph = open_graph(driver, database=NEO4J_DB, file_root=DATA)
    store = Store(driver, graph, DATA, database=NEO4J_DB, embed=None if args.no_embed else embed)
    try:
        check_versioned(driver, database=NEO4J_DB)
        setup_database(graph, driver, database=NEO4J_DB)
        try:
            request, root = request_of(text, path, args)
        except GraphDocError as exc:
            out = rejected([{"rule": "format", "at": "request", "msg": str(exc)}])
        else:
            ctx = Context(
                store,
                at=datetime.now(UTC).isoformat(timespec="seconds"),
                session=args.session,
                formed_by=args.user,
                sync=lambda: sync(driver, NEO4J_DB, None if args.no_embed else embed),
                text=text,
                workdir=Workdir(root),
            )
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
    parser.add_argument("request", nargs="?", help="请求文件或 graph-doc 文件的路径；- 表示从标准输入读取")
    parser.add_argument("-e", "--expr", help="直接给出请求（YAML 文本）")
    parser.add_argument("--no-embed", action="store_true", help="关闭查询向量，写入后也不补算向量")
    parser.add_argument("--user", help="登录身份（模型或人），记为提交的作者")
    parser.add_argument("--session", help="调用所在的会话，记为提交的来源")
    commit = parser.add_argument_group("直接给出 graph-doc 文件时（commit）")
    commit.add_argument("--apply", action="store_true", help="提交；不加时只检查")
    commit.add_argument("--message", help="提交说明；默认是文件名")
    return parser


__all__ = ["main", "request_of"]
