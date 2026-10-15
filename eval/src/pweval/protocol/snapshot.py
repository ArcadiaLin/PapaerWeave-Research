"""检查点的冻结快照（evaluation_draft §10.1）的格式与读取：运行到检查点时由 :mod:`pweval.harness.export` 立即导出，
之后的测量只读快照，可以离线重算。这里只用标准库，测量层与运行框架共用。

    load(out) -> Snapshot            # A3 的快照读回内存

A3 的快照（``out/``）：

- ``graph.jsonl``：每行一个节点 ``{"node": id, "labels": [...], "props": {...}}`` 或一条边
  ``{"edge": [src, type, dst], "props": {...}}``；以节点的 ``id`` 属性连接，按 id 排序。不含版本记录（``Commit``、
  ``Branch``、``IdCounter``、``TOUCHED``、``PARENT``）与派生的向量属性（``embedding``、``embedding_key``）；
- ``commits.jsonl``：各提交的属性，按 ``seq``；``changeset``、``meta`` 等 JSON 字符串原样保留；
- ``documents/``：产物文档（``Material`` 中路径以 ``artifacts/`` 开头的文件）的副本，保持相对路径；论文材料是语料，
  不复制，``Material`` 上有路径与哈希；
- ``meta.yml``：库地址、分支头、导出时间、各类计数。

A0 的快照：``tree/``（``git archive <标签>`` 展开）、``log.jsonl``（标签及之前的提交）、``meta.yml``。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Snapshot:
    """A3 快照读回内存：节点 id → ``{labels, props}``，边 ``(src, type, dst, props)``，提交列表。"""

    nodes: dict[str, dict[str, Any]] = field(default_factory=dict)
    edges: list[tuple[str, str, str, dict[str, Any]]] = field(default_factory=list)
    commits: list[dict[str, Any]] = field(default_factory=list)
    root: Path | None = None

    def document(self, path: str) -> str:
        assert self.root is not None
        return (self.root / "documents" / path).read_text(encoding="utf-8")


def load(out: Path) -> Snapshot:
    snap = Snapshot(root=out)
    for line in (out / "graph.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if "node" in row:
            snap.nodes[row["node"]] = {"labels": row["labels"], "props": row["props"]}
        else:
            src, rel, dst = row["edge"]
            snap.edges.append((src, rel, dst, row["props"]))
    commits = out / "commits.jsonl"
    if commits.exists():
        snap.commits = [json.loads(line) for line in commits.read_text(encoding="utf-8").splitlines() if line]
    return snap


__all__ = ["Snapshot", "load"]
