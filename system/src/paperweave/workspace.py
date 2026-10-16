"""生成一个实验目录：通用 Agent（默认配置的 pi）在这里启动，经 MCP 使用 PaperWeave 的工具。

    python -m paperweave.workspace <目录> [--user <登录身份>] [--agent pi/provider/model] [--neo4j-uri bolt://...]
                            [--data <材料根目录>] [--no-embed]

目录里只有三样：``.pi/mcp.json`` 登记 ``PaperWeave`` 服务（``python -m paperweave.mcp``，工具直接列给模型；服务的
调用日志写到 ``.pi/paperweave.log``）；``.pi/settings.json`` 把 pi 的会话存到 ``.pi/sessions/``，一次实验的记录都在
目录里；``pi.sh`` 在目录中启动 pi
（``./pi.sh`` 进入交互界面，``./pi.sh -r`` 选择会话继续）。pi 会从工作目录及其上层目录加载 ``AGENTS.md`` 等上下文
文件，所以目录必须在仓库之外；目录已存在且不空时拒绝。``--user`` 是写入者的登录身份（``PAPERWEAVE_USER``，
记为 ``formed_by``）；``--agent`` 是所用的 Agent 与模型（``PAPERWEAVE_AGENT``），默认取 pi 的默认模型
（``$PI_CODING_AGENT_DIR`` 或 ``~/.pi/agent`` 下 ``settings.json`` 的 ``defaultProvider/defaultModel``），写成 ``pi/provider/model``；不给 ``--user`` 时
登录身份与它相同。
项目级的 ``.pi/mcp.json`` 只在信任该目录后加载：第一次在目录中启动 pi 时确认信任，非交互模式用 ``--approve``。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .config import NEO4J_URI, REPO

SERVER = "PaperWeave"
LAUNCHER = """#!/bin/sh
# Start pi in this directory; sessions are kept in .pi/sessions. Resume: ./pi.sh -r
cd "$(dirname "$0")" && exec pi "$@"
"""


def default_agent() -> str | None:
    """pi 与它的默认模型，写成 ``pi/provider/model``。"""
    agent = Path(os.environ.get("PI_CODING_AGENT_DIR", Path.home() / ".pi/agent")).expanduser()
    try:
        settings = json.loads((agent / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    provider, model = settings.get("defaultProvider"), settings.get("defaultModel")
    return f"pi/{provider}/{model}" if provider and model else None


def mcp_config(
    *,
    user: str,
    agent: str | None,
    neo4j_uri: str,
    no_embed: bool,
    log: Path | None = None,
    data: Path | None = None,
    workdir: Path | None = None,
) -> dict[str, Any]:
    """``.pi/mcp.json`` 的内容。stdio 服务只拿到这里写出的环境变量，连接参数因此都写明。服务在仓库中运行，
    ``workdir``（写者的工作目录）因此也写明，commit 的文件只从那里读，checkout 也写到那里。"""
    env = {"PAPERWEAVE_NEO4J_URI": neo4j_uri, "PAPERWEAVE_USER": user}
    if workdir is not None:
        env["PAPERWEAVE_WORKDIR"] = str(workdir)
    if agent:
        env["PAPERWEAVE_AGENT"] = agent
    if data is not None:
        env["PAPERWEAVE_DATA"] = str(data)
    if log is not None:
        env["PAPERWEAVE_MCP_LOG"] = str(log)
    if no_embed:
        env["PAPERWEAVE_NO_EMBED"] = "1"
    server = {
        "command": str(REPO / ".venv/bin/python"),
        "args": ["-m", "paperweave.mcp"],
        "cwd": str(REPO / "system"),
        "env": env,
        "exposure": "direct",
        "timeout": 300,
    }
    return {"mcpServers": {SERVER: server}}


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    target = Path(args.dir).expanduser().resolve()
    if target == REPO or REPO in target.parents:
        print(f"error: {target} is inside the repository; pi would load its AGENTS.md", file=sys.stderr)
        return 1
    if target.exists() and any(target.iterdir()):
        print(f"error: {target} exists and is not empty", file=sys.stderr)
        return 1
    agent = args.agent or default_agent()
    user = args.user or agent
    if not user:
        print("error: no pi default model found; give --user or --agent", file=sys.stderr)
        return 1
    config = mcp_config(
        user=user,
        agent=agent,
        neo4j_uri=args.neo4j_uri,
        no_embed=args.no_embed,
        log=target / ".pi/paperweave.log",
        workdir=target,
        data=Path(args.data).expanduser().resolve() if args.data else None,
    )
    (target / ".pi").mkdir(parents=True)
    (target / ".pi/mcp.json").write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (target / ".pi/settings.json").write_text(
        json.dumps({"sessionDir": ".pi/sessions"}, indent=2) + "\n", encoding="utf-8"
    )
    (target / "pi.sh").write_text(LAUNCHER, encoding="utf-8")
    (target / "pi.sh").chmod(0o755)
    print(f"{target}  (user {user}, agent {agent}, {args.neo4j_uri})")
    print(f"{target}/pi.sh       # trust the directory on first start; resume with -r; non-interactive runs: --approve")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m paperweave.workspace", description=__doc__.split("\n\n")[0])
    parser.add_argument("dir", help="实验目录，须在仓库之外")
    parser.add_argument("--user", help="登录身份，记为 formed_by；默认与 --agent 相同")
    parser.add_argument("--agent", help="所用的 Agent 与模型 pi/provider/model；默认取 pi 的默认模型")
    parser.add_argument("--neo4j-uri", default=NEO4J_URI, help=f"服务连接的库（默认 {NEO4J_URI}）")
    parser.add_argument("--data", help="材料根目录（论文材料与产物文档）；默认 data/raw/e09-paper-knowledge")
    parser.add_argument("--no-embed", action="store_true", help="关闭查询向量，写入后也不补算")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["LAUNCHER", "SERVER", "default_agent", "main", "mcp_config"]
