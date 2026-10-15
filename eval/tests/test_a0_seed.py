"""A0 的检查点 0：由 A3 检查点 0 的快照渲染笔记，加上种子 Leaderboard。用合成的小快照检验；真实语料（data/，
只在本地）上的渲染在运行中由不变式守住。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from pweval.harness.a0_seed import RenderError, check_board, commit_seed, object_views, render, render_board, write
from pweval.protocol.snapshot import Snapshot, load

NODES = [
    ("paper_0001", ["Entity", "Paper"],
     {"name": "Informer: Beyond Efficient Transformer", "identifiers": ["arxiv:2012.07436"], "year": 2021,
      "description": "Proposes Informer."}),
    ("material_a1", ["Material"], {"path": "papers/2012.07436v3/paper.md", "content_hash": "x"}),
    ("method_0001", ["Concept", "Method"], {"name": "Informer", "definition": "A sparse-attention Transformer."}),
    ("method_0002", ["Concept", "Method"], {"name": "Autoformer", "stub": True, "note": "Cited as [38]."}),
    ("dataset_0002", ["Entity", "Dataset"], {"name": "ETTh1", "description": "Hourly transformer data."}),
    ("task_0002", ["Concept", "Task"],
     {"name": "Long-term time series forecasting", "definition": "Forecasting far ahead."}),
    ("exp_0001", ["Content", "Experiment"], {"text": "Multivariate results on ETT.", "anchors": ["S3.T1"]}),
    ("Informer|Method|global", ["NameKey"], {"raw": "Informer", "key": "Informer|Method|global"}),
    ("ProbSparse Informer|Method|global", ["NameKey"], {"raw": "ProbSparse Informer"}),
    ("art_0001", ["Artifact"], {"op": "Leaderboard", "title": "ETTh1 multivariate long-term forecasting"}),
]
EDGES = [
    ("material_a1", "MATERIAL_OF", "paper_0001", {}),
    ("Informer|Method|global", "NAMES", "method_0001", {}),
    ("ProbSparse Informer|Method|global", "NAMES", "method_0001", {}),
    ("exp_0001", "FROM", "paper_0001", {"material_ref": "material_a1", "locators": ["Datasets::265:273"]}),
    ("exp_0001", "EVALUATES", "method_0002", {"role": "baseline", "source_refs": ["material_a1::Datasets::269"]}),
    ("exp_0001", "EVALUATES", "method_0001", {"role": "target", "description": "Run by the authors."}),
    ("exp_0001", "USES", "dataset_0002", {"role": "evaluation_data"}),
    ("exp_0001", "ON_TASK", "task_0002", {}),
]
BOARD = """---
type: Leaderboard
title: ETTh1 multivariate long-term forecasting
abs: >-
  MSE reported on ETTh1.
task: task_0002          # Long-term time series forecasting
dataset: dataset_0002    # ETTh1
setting: {variate: multivariate}
metrics: {MSE: lower}
---
## Results

| method | variant | paper | role | origin | lookback | pred_len | MSE | source |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| method_0001 Informer |  | paper_0001 Informer | target | run | not stated | 24 | 0.577 | paper_0001::Datasets::269 |
| method_0002 Autoformer |  | paper_0001 Informer | baseline |  | not stated | 24 |  | \
paper_0001::Datasets::269; paper_0001::Datasets::270 |

## Notes

- Look-back is searched [paper_0001::The hyperparameter tuning range::773].

## Papers covered

| paper | tables | complete |
| --- | --- | --- |
| paper_0001 Informer | Table 2 (paper_0001::Datasets::265:273) | yes |
"""


@pytest.fixture
def snap() -> Snapshot:
    return Snapshot(
        nodes={i: {"labels": labels, "props": {"id": i, **props}} for i, labels, props in NODES},
        edges=list(EDGES),
    )


def test_views_assemble_kind_aliases_material_and_edges(snap: Snapshot) -> None:
    views = object_views(snap)
    assert set(views) == {"paper_0001", "method_0001", "method_0002", "dataset_0002", "task_0002", "exp_0001"}
    assert views["method_0001"]["aliases"] == ["ProbSparse Informer"]  # 名称本身的 NameKey 不算别名
    assert views["paper_0001"]["material"] == "papers/2012.07436v3/paper.md"
    assert [e["to"] for e in views["exp_0001"]["EVALUATES"]] == ["method_0001", "method_0002"]  # 按终点 id
    assert views["exp_0001"]["ON_TASK"] == ["task_0002"]


def test_one_file_per_object_and_contents_inside_papers(snap: Snapshot) -> None:
    files = render(snap)
    assert sorted(files) == [
        "README.md",
        "datasets/etth1.md",
        "methods/autoformer.md",
        "methods/informer.md",
        "papers/informer-2012-07436.md",
        "tasks/long-term-time-series-forecasting.md",
    ]
    paper = files["papers/informer-2012-07436.md"]
    assert "## Experiment S3.T1" in paper and "- Datasets::265:273" in paper
    assert "sources: [Informer: Beyond Efficient Transformer](informer-2012-07436.md) Datasets::269" in paper
    assert "known only from citations" in files["methods/autoformer.md"]
    assert render(snap) == files


def test_board_follows_the_a0_rules(snap: Snapshot) -> None:
    files = render(snap, {"etth1-multivariate.md": BOARD})
    board = files["leaderboards/etth1-multivariate.md"]
    assert board.startswith("# ETTh1 multivariate long-term forecasting\n\nMSE reported on ETTh1.\n")
    assert "- **task:** [Long-term time series forecasting](../tasks/long-term-time-series-forecasting.md)" in board
    assert "- **setting:** variate: multivariate\n- **metrics:** MSE (lower is better)\n\n## Results" in board
    row = "| [Informer](../methods/informer.md) |  | [Informer](../papers/informer-2012-07436.md) | target | run |"
    assert row + " not stated | 24 | 0.577 | Datasets::269 |" in board
    assert "|  | Datasets::269; Datasets::270 |" in board
    assert "searched [Informer](../papers/informer-2012-07436.md) The hyperparameter tuning range::773]" not in board
    note = "- Look-back is searched [Informer](../papers/informer-2012-07436.md) The hyperparameter tuning range::773."
    assert note in board
    assert "| Table 2 (Datasets::265:273) | yes |" in board
    assert "leaderboards/" in files["README.md"]


def test_board_check_catches_a_changed_row(snap: Snapshot) -> None:
    views = object_views(snap)
    files = {"method_0001": "methods/informer.md", "method_0002": "methods/autoformer.md",
             "paper_0001": "papers/informer-2012-07436.md", "task_0002": "tasks/long-term-time-series-forecasting.md",
             "dataset_0002": "datasets/etth1.md"}
    a0 = render_board(BOARD, "leaderboards/b.md", views, files)
    check_board(BOARD, a0, files)
    with pytest.raises(RenderError, match="MSE"):
        check_board(BOARD, a0.replace("| 0.577 |", "| 0.578 |"), files)
    with pytest.raises(RenderError, match="method"):
        check_board(BOARD, a0.replace("../methods/autoformer.md", "../methods/informer.md"), files)
    with pytest.raises(RenderError, match="cannot link"):
        render(snap, {"b.md": BOARD.replace("method_0002 Autoformer", "method_0099 Unknown")})


def test_render_reads_an_exported_snapshot(tmp_path: Path, snap: Snapshot) -> None:
    rows = [{"node": i, "labels": v["labels"], "props": v["props"]} for i, v in snap.nodes.items()]
    rows += [{"edge": [s, r, d], "props": p} for s, r, d, p in snap.edges]
    (tmp_path / "graph.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    assert render(load(tmp_path)) == render(snap)


def test_seed_commit(tmp_path: Path, snap: Snapshot) -> None:
    store = tmp_path / "store"
    write(render(snap), store)
    commit_seed(store)
    git_log = ["git", "-C", str(store), "log", "--format=%an %D"]
    log = subprocess.run(git_log, capture_output=True, text=True, check=True)
    assert log.stdout.strip() == "seed HEAD -> main, tag: checkpoint-0"
