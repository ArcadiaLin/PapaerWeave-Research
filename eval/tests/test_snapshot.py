"""检查点快照：A0 的导出（git 标签下的文件树与提交列表）与 A3 快照的读回。A3 的导出要连库，在运行中检验。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from pweval.harness.export import export_a0
from pweval.protocol.snapshot import load

GIT = ["-c", "user.name=seed", "-c", "user.email=seed@t1.example", "-c", "commit.gpgsign=false"]


def test_export_a0_takes_the_tagged_tree(tmp_path: Path) -> None:
    store = tmp_path / "store"
    (store / "papers").mkdir(parents=True)
    (store / "papers/a.md").write_text("# A\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", "-b", "main", str(store)], check=True)
    subprocess.run(["git", "-C", str(store), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(store), *GIT, "commit", "-q", "-m", "seed"], check=True)
    subprocess.run(["git", "-C", str(store), *GIT, "tag", "checkpoint-0"], check=True)
    (store / "papers/b.md").write_text("# B\n", encoding="utf-8")  # 标签之后的改动不进快照
    subprocess.run(["git", "-C", str(store), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(store), *GIT, "commit", "-q", "-m", "later"], check=True)

    meta = export_a0(store, "checkpoint-0", tmp_path / "snap")
    assert sorted(p.name for p in (tmp_path / "snap/tree/papers").iterdir()) == ["a.md"]
    log = [json.loads(line) for line in (tmp_path / "snap/log.jsonl").read_text().splitlines()]
    assert [c["message"] for c in log] == ["seed"] and log[0]["author"] == "seed"
    assert meta["counts"] == {"files": 1, "commits": 1}
    assert yaml.safe_load((tmp_path / "snap/meta.yml").read_text())["tag"] == "checkpoint-0"
    with pytest.raises(FileExistsError):
        export_a0(store, "checkpoint-0", tmp_path / "snap")


def test_load_reads_nodes_edges_and_commits(tmp_path: Path) -> None:
    rows = [
        {"node": "method_0001", "labels": ["Concept", "Method"], "props": {"id": "method_0001", "name": "Informer"}},
        {"node": "paper_0001", "labels": ["Entity", "Paper"], "props": {"id": "paper_0001"}},
        {"edge": ["method_0001", "FROM", "paper_0001"], "props": {"locators": ["4::1:2"]}},
    ]
    (tmp_path / "graph.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    (tmp_path / "commits.jsonl").write_text(json.dumps({"id": "commit_000001", "seq": 1}) + "\n", encoding="utf-8")
    snap = load(tmp_path)
    assert snap.nodes["method_0001"]["props"]["name"] == "Informer"
    assert snap.edges == [("method_0001", "FROM", "paper_0001", {"locators": ["4::1:2"]})]
    assert snap.commits[0]["id"] == "commit_000001"
