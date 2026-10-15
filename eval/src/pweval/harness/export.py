"""检查点快照的导出（格式见 :mod:`pweval.protocol.snapshot`）：运行到检查点时立即导出，之后的测量只读快照。

    export_a3(uri, data_root, out)   # Cypher 直接读库，按 graph_model_v2 写明的标签与属性
    export_a0(store, tag, out)       # git 标签下的文件树与提交列表
    head(uri)                        # 分支头的提交 id

    python -m pweval.harness.export <运行名> [--config …]   # A3 的当前状态 → <运行目录>/checkpoints/head/A3/（试跑）
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tarfile
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

    auth = (os.environ.get("PAPERWEAVE_NEO4J_USER", "neo4j"), os.environ.get("PAPERWEAVE_NEO4J_PASSWORD", "password"))
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


def _clean(props: dict[str, Any]) -> dict[str, Any]:
    return {k: props[k] for k in sorted(props) if k not in DERIVED}


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _empty(out: Path) -> None:
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"{out} exists and is not empty")
    out.mkdir(parents=True, exist_ok=True)


def main(argv: list[str] | None = None) -> int:
    """试跑时读库的当前状态：先导出成快照（``checkpoints/head/A3/``，已有的先删除），测量层再读这份快照。"""
    import argparse

    from ..paths import REPO
    from ..protocol.config import run_config

    parser = argparse.ArgumentParser(prog="python -m pweval.harness.export", description=main.__doc__)
    parser.add_argument("name")
    parser.add_argument("--config", default=str(REPO / "eval/config/pilot-ltsf.yml"))
    args = parser.parse_args(argv)
    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    run = Path(config["runner"]["workdir_root"]).expanduser() / args.name
    config = run_config(run, config)
    out = run / "checkpoints/head/A3"
    if out.exists():
        shutil.rmtree(out)
    meta = export_a3(config["arms"]["A3"]["neo4j"], run / "A3/data", out)
    print(f"{out}: {meta['counts']} head {meta['branches'].get('main')}")
    return 0


__all__ = ["driver", "export_a0", "export_a3", "head", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
