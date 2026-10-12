"""论文版本与版本事件：写者先拿到论文的早期版本，事件会话时新版本才出现（evaluation_draft.md 的修订事件）。

配置中一篇论文写 ``first_version`` 时，``arxiv`` 是它的新版本：写者的任务给早期版本，``events`` 中的维护者会话在
``after_checkpoint`` 之后把新版本带进来。各组的论文目录（A3 的 ``data/papers``、A0 的 ``papers``）起初只有
:func:`initial_papers`，事件开始前才放入新版本，所以事件之前没有人能看到它。

检查点 ``k`` 时一篇论文的“当前版本”（:func:`version_at`）：``k`` 不超过事件的检查点时是早期版本，之后是新版本。
金标准、判分与健康度都按它取版本。
"""

from __future__ import annotations

from typing import Any


def first_versions(config: dict[str, Any]) -> dict[str, str]:
    """新版本 → 写者最初拿到的早期版本。"""
    return {p["arxiv"]: p["first_version"] for p in config["corpus"]["papers"] if p.get("first_version")}


def events(config: dict[str, Any]) -> list[dict[str, Any]]:
    return list(config.get("events") or [])


def event_checkpoint(config: dict[str, Any], arxiv: str) -> int | None:
    """新版本 ``arxiv`` 在哪个检查点之后出现；没有事件时为 ``None``。"""
    return next((e["after_checkpoint"] for e in events(config) if e["paper"] == arxiv), None)


def version_at(config: dict[str, Any], arxiv: str, k: int | None) -> str:
    """检查点 ``k`` 时论文 ``arxiv``（新版本的 id）的当前版本；``k`` 为 ``None`` 表示时间线结束时。"""
    first = first_versions(config).get(arxiv)
    after = event_checkpoint(config, arxiv)
    if first is None or (k is None and after is not None) or (after is not None and k is not None and k > after):
        return arxiv
    return first


def siblings(config: dict[str, Any]) -> dict[str, list[str]]:
    """每个版本 → 同一论文的其他版本。"""
    out: dict[str, list[str]] = {}
    for new, old in first_versions(config).items():
        out[new], out[old] = [old], [new]
    return out


def initial_papers(config: dict[str, Any]) -> list[str]:
    """各组论文目录起初的内容：种子论文，以及每篇论文写者最初拿到的版本。"""
    papers = [p["arxiv"] for p in config["corpus"]["seeds"]]
    return papers + [p.get("first_version") or p["arxiv"] for p in config["corpus"]["papers"]]


__all__ = ["event_checkpoint", "events", "first_versions", "initial_papers", "siblings", "version_at"]
