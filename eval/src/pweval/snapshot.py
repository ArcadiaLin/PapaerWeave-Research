"""检查点的冻结快照（evaluation_draft §10.1）：运行到检查点时立即导出，之后的测量只读快照，可以离线重算。

    export_a3(uri, data_root, out)   # Cypher 直接读库，按 graph_model_v2 写明的标签与属性
    export_a0(store, tag, out)       # git 标签下的文件树与提交列表
    load(out) -> Snapshot            # 测量层也可以只用 json 与 yaml 自己读这些文件

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

import io
import json
import os
import shutil
import subprocess
import tarfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

VERSION_LABELS = ("Commit", "Branch", "IdCounter")
VERSION_RELS = ("TOUCHED", "PARENT")
DERIVED = ("embedding", "embedding_key")


def driver(uri: str):
    """连接被测系统的库；用户名与密码取系统自己的环境变量（只是连接配置，不导入系统代码）。"""
    from neo4j import GraphDatabase

    auth = (os.environ.get("E09_NEO4J_USER", "neo4j"), os.environ.get("E09_NEO4J_PASSWORD", "password"))
    return GraphDatabase.driver(uri, auth=auth, notifications_disabled_classifications=["UNRECOGNIZED"])


def head(uri: str, branch: str = "main") -> str | None:
    """分支头的提交 id；没有分支节点时为 ``None``。"""
    with driver(uri) as d:
        rows = d.execute_query("MATCH (b:Branch {name: $b}) RETURN b.head AS head", b=branch).records
    return rows[0]["head"] if rows else None


def export_a3(uri: str, data_root: Path, out: Path) -> dict[str, Any]:
    """把库导出到 ``out``（必须不存在或为空）；返回 ``meta``。"""
    _empty(out)
    with driver(uri) as d:
        nodes = d.execute_query(
            "MATCH (n) WHERE n.id IS NOT NULL AND none(l IN labels(n) WHERE l IN $skip) "
            "RETURN n.id AS id, labels(n) AS labels, properties(n) AS props",
            skip=list(VERSION_LABELS),
        ).records
        edges = d.execute_query(
            "MATCH (a)-[e]->(b) WHERE a.id IS NOT NULL AND b.id IS NOT NULL AND NOT type(e) IN $skip "
            "AND none(l IN labels(a) + labels(b) WHERE l IN $labels) "
            "RETURN a.id AS src, type(e) AS type, b.id AS dst, properties(e) AS props",
            skip=list(VERSION_RELS),
            labels=list(VERSION_LABELS),
        ).records
        commits = d.execute_query("MATCH (c:Commit) RETURN properties(c) AS props ORDER BY c.seq").records
        branch = d.execute_query("MATCH (b:Branch) RETURN b.name AS name, b.head AS head ORDER BY name").records
    node_rows = sorted(({"node": r["id"], "labels": sorted(r["labels"]), "props": _clean(r["props"])} for r in nodes),
                       key=lambda x: x["node"])
    edge_rows = sorted(({"edge": [r["src"], r["type"], r["dst"]], "props": _clean(r["props"])} for r in edges),
                       key=lambda x: (*x["edge"], _dump(x["props"])))
    with open(out / "graph.jsonl", "w", encoding="utf-8") as f:
        for row in [*node_rows, *edge_rows]:
            f.write(_dump(row) + "\n")
    with open(out / "commits.jsonl", "w", encoding="utf-8") as f:
        for r in commits:
            f.write(_dump(_clean(r["props"])) + "\n")
    documents = 0
    for row in node_rows:
        path = str(row["props"].get("path", ""))
        if "Material" in row["labels"] and path.startswith("artifacts/"):
            target = out / "documents" / path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(data_root / path, target)
            documents += 1
    meta = {
        "arm": "A3",
        "uri": uri,
        "branches": {r["name"]: r["head"] for r in branch},
        "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "counts": {"nodes": len(node_rows), "edges": len(edge_rows), "commits": len(commits), "documents": documents},
    }
    (out / "meta.yml").write_text(yaml.safe_dump(meta, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return meta


def export_a0(store: Path, tag: str, out: Path) -> dict[str, Any]:
    """A0 笔记库在 ``tag`` 时的文件树与提交列表。"""
    _empty(out)
    archive = subprocess.run(["git", "-C", str(store), "archive", "--format=tar", tag], capture_output=True, check=True)
    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
        tar.extractall(out / "tree", filter="data")
    fmt = "%H%x1f%an%x1f%aI%x1f%s"
    log = subprocess.run(["git", "-C", str(store), "log", "--reverse", f"--format={fmt}", tag],
                         capture_output=True, text=True, check=True).stdout
    commits = [dict(zip(("id", "author", "at", "message"), line.split("\x1f"), strict=True))
               for line in log.splitlines() if line]
    with open(out / "log.jsonl", "w", encoding="utf-8") as f:
        for c in commits:
            f.write(_dump(c) + "\n")
    files = sum(1 for p in (out / "tree").rglob("*") if p.is_file())
    meta = {
        "arm": "A0",
        "store": str(store),
        "tag": tag,
        "head": commits[-1]["id"] if commits else None,
        "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "counts": {"files": files, "commits": len(commits)},
    }
    (out / "meta.yml").write_text(yaml.safe_dump(meta, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return meta


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


def _clean(props: dict[str, Any]) -> dict[str, Any]:
    return {k: props[k] for k in sorted(props) if k not in DERIVED}


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _empty(out: Path) -> None:
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"{out} exists and is not empty")
    out.mkdir(parents=True, exist_ok=True)


__all__ = ["Snapshot", "driver", "export_a0", "export_a3", "head", "load"]
