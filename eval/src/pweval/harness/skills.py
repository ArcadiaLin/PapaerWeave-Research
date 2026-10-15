"""A3 写者会话前放置 skill（arXiv v1 待办 C1）：库中各 Skill 的当前版本取到写者工作目录的 ``.agents/skills/``，pi
启动时从这里扫描。A0 不放 skill；读者（探针）也不放。

取用经系统的 MCP 入口（``FetchArtifact``），以该写者的身份、在其工作目录中执行，相当于写者自己取了一次；这次调用
不写入写者的服务日志（``paperweave.log``），以免算进写者的工具调用统计。Skill 的 id 用 Cypher 从库中读出。
"""

from __future__ import annotations

import os
import sys
from typing import Any

import yaml

from . import export
from .mcp_client import Client
from .sandbox import Arm, Paths, Writer, mcp_env

SKILLS_DIR = ".agents/skills"


def skill_ids(uri: str) -> list[str]:
    with export.driver(uri) as d:
        rows = d.execute_query("MATCH (a:Artifact {op: 'Skill'}) RETURN a.id AS id ORDER BY id").records
    return [r["id"] for r in rows]


def place(paths: Paths, arm: Arm, writer: Writer) -> dict[str, Any]:
    """取出全部 skill，覆盖工作目录中同名的文件；返回 id、各自的版本、取用中的问题与工作目录中现有的 skill 文件。"""
    assert arm.neo4j is not None
    ids = skill_ids(arm.neo4j)
    out: dict[str, Any] = {"ids": ids}
    if ids:
        env = mcp_env(paths, arm, writer)
        for key in ("PAPERWEAVE_MCP_LOG", "PAPERWEAVE_ENABLE_COMMIT"):
            env.pop(key, None)
        with Client([sys.executable, "-m", "paperweave.mcp"], {**os.environ, **env}, name="t1-skills") as client:
            reply = yaml.safe_load(client.call("FetchArtifact", {"artifact": ids})) or {}
        out["versions"] = {item["artifact"]: item.get("version") for item in reply.get("items") or []}
        if reply.get("missing") or reply.get("errors"):
            out["problems"] = reply.get("missing") or reply.get("errors")
    root = paths.work / SKILLS_DIR
    found = root.glob("*/SKILL.md") if root.exists() else []
    out["files"] = sorted(p.relative_to(paths.work).as_posix() for p in found)
    return out


__all__ = ["SKILLS_DIR", "place", "skill_ids"]
