"""种子产物的检入：经被测系统的 MCP 入口，以 ``seed`` 身份检入 ``eval/seeds/`` 中的 Leaderboard 与 skill。

先检入全部 Leaderboard（一个提交，id 按文件名顺序为 ``art_0001`` 起），再检入 skill（另一个提交），表的 id 因此不随
skill 的增减而变。运行框架的 A3 起点与 ``seeds/scripts/checkin.py`` 共用这里的批次。
"""

from __future__ import annotations

import sys

from ..paths import SEEDS
from .mcp_client import Client, status

BATCHES = [  # (相对 seeds/ 的 glob，update_abstract)
    ("leaderboards/*.md", "Seed leaderboards from the seed papers' main tables."),
    ("skills/*/SKILL.md", "Seed skills for paper forms, Leaderboards and Generate documents."),
]


def documents(pattern: str) -> list[str]:
    return sorted(p.relative_to(SEEDS).as_posix() for p in SEEDS.glob(pattern))


def check_in(env: dict[str, str], *, confirm: bool = True) -> tuple[bool, list[tuple[str, str]]]:
    """按批次检入；``confirm`` 为假时只检查。返回是否全部通过与各次回复 ``(阶段, 文本)``。``env`` 给出库地址与
    ``PAPERWEAVE_DATA``；工作目录与登录身份在这里设定。"""
    mcp_env = {**env, "PAPERWEAVE_WORKDIR": str(SEEDS), "PAPERWEAVE_USER": "seed", "PAPERWEAVE_AGENT": "t1-seed"}
    replies: list[tuple[str, str]] = []
    with Client([sys.executable, "-m", "paperweave.mcp"], mcp_env, name="t1-seed") as client:
        for pattern, abstract in BATCHES:
            request = {"artifact_doc": documents(pattern), "update_abstract": abstract}
            replies.append((f"check {pattern}", client.call("CheckIn", request)))
            if status(replies[-1][1]) != "checked":
                return False, replies
            if confirm:
                replies.append((f"confirm {pattern}", client.call("CheckIn", {**request, "confirm": True})))
                if status(replies[-1][1]) != "committed":
                    return False, replies
    return True, replies


__all__ = ["BATCHES", "check_in", "documents"]
