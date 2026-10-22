"""共同产物（commit 检入、checkout 取出、``_stale``）测试的共用部件：在测试实例上写入一小份图，产物文档写到临时的材料根目录，
写者的工作目录也是临时目录。

只在设置了 ``GRAPH_VC_TEST_NEO4J_URI`` 时运行，要求开始时库为空，结束后清空库、约束与索引。不会连 neo4j-e09。
每个测试模块重建一次图，模块内的测试按顺序共享写入的产物。论文材料默认是 60 行 ``line <i>``，模块中定义
``PAPER_TEXT`` 时用它。
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from paperweave.commit import Context as CommitContext
from paperweave.commit import Neo4jReader, apply
from paperweave.draft import Workdir
from paperweave.operators.base import Context
from paperweave.operators.db import CHECKOUT, COMMIT
from paperweave.store import Store, open_graph, setup_database
from paperweave.store.derived import sync

TEST_URI = os.environ.get("GRAPH_VC_TEST_NEO4J_URI")
TEST_AUTH = (
    os.environ.get("GRAPH_VC_TEST_NEO4J_USER", "neo4j"),
    os.environ.get("GRAPH_VC_TEST_NEO4J_PASSWORD", "password"),
)
AT = "2026-10-14T12:00:00+00:00"
MATERIAL = "papers/2023-DLinear/paper.md"

GRAPH = """
graph-doc: v0.2
create:
  $ltsf:
    kind: Task
    name: Long-term time series forecasting
    description: Forecasting with a long horizon.
  $tf:
    kind: Method
    name: Transformer-based forecasting
    description: Forecasting models built on Transformer architectures.
  $etth1:
    kind: Dataset
    name: ETTh1
    description: Hourly electricity transformer temperature data.
  $paper:
    kind: Paper
    name: Are Transformers Effective for Time Series Forecasting?
    year: 2023
    material: papers/2023-DLinear/paper.md
    description: Questions whether Transformers are effective for LTSF and introduces DLinear.
  $dlinear:
    kind: Method
    name: DLinear
    description: A linear model on a trend and remainder decomposition.
  $main:
    kind: Experiment
    paper: $paper
    anchor: [10:20]
    figures: [S5.T2]
    description: Multivariate long-term forecasting comparing DLinear with Transformer baselines.
    EVALUATES:
      $dlinear: {role: target}
      $tf: {role: baseline}
    USES:
      $etth1: {role: evaluation_data}
    ON_TASK:
      $ltsf:
"""
# task_0001、method_0001 tf、dataset_0001 etth1、paper_0001、method_0002 dlinear、exp_0001

LEADERBOARD = """---
type: Leaderboard
title: ETTh1 multivariate long-term forecasting
abs: MSE reported for methods on ETTh1 (multivariate), by paper and horizon.
task: task_0001          # Long-term forecasting
dataset: dataset_0001    # ETTh1
setting: {variate: multivariate}
---
## Results

| method | variant | paper | role | lookback | pred_len | MSE | source |
| --- | --- | --- | --- | --- | --- | --- | --- |
| method_0002 DLinear |  | paper_0001 DLinear | target | 336 | 96 | 0.375 | paper_0001::5.2 Comparison::10:12 |
| method_0001 Transformer |  | paper_0001 DLinear | baseline | 96 | 96 | 0.865 | paper_0001::5.2 Comparison::12 |

## Papers covered

| paper | tables | complete |
| --- | --- | --- |
| paper_0001 DLinear | Table 2 (paper_0001::5.2 Comparison::10:20) | no |
"""


@pytest.fixture(scope="module")
def store(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> Iterator[Store]:
    if TEST_URI is None:
        pytest.skip("GRAPH_VC_TEST_NEO4J_URI is not set")
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(TEST_URI, auth=TEST_AUTH, notifications_disabled_classifications=["UNRECOGNIZED"])
    count = driver.execute_query("MATCH (n) RETURN count(n) AS c").records[0]["c"]
    if count:
        driver.close()
        pytest.skip(f"refusing to run: test database at {TEST_URI} is not empty ({count} nodes)")
    root = tmp_path_factory.mktemp("materials")
    file = root / MATERIAL
    file.parent.mkdir(parents=True)
    default = "".join(f"line {i}\n" for i in range(1, 61))
    file.write_text(getattr(request.module, "PAPER_TEXT", default), encoding="utf-8")
    graph = open_graph(driver, file_root=root)
    try:
        seeded = Store(driver, graph, root)
        setup_database(graph, driver)
        _, record = apply(GRAPH, graph, CommitContext(Neo4jReader(graph, driver), "seed:test", AT, root, "seed"))
        assert record is not None
        sync(driver, None, None)
        yield seeded
    finally:
        driver.execute_query("MATCH (n) DETACH DELETE n")
        for record in driver.execute_query("SHOW CONSTRAINTS YIELD name").records:
            driver.execute_query(f"DROP CONSTRAINT {record['name']}")
        for record in driver.execute_query("SHOW INDEXES YIELD name, type WHERE type <> 'LOOKUP' RETURN name").records:
            driver.execute_query(f"DROP INDEX {record['name']}")
        driver.close()


def commit_doc(store: Store, text: str, *, user: str = "test", commit: bool = True) -> dict[str, Any]:
    """经 commit 提交（或 dry_run）一份 graph-doc：写到临时工作目录再交文件，与写者的路径相同。"""
    root = store.material_root.parent / "maintainer"
    root.mkdir(exist_ok=True)
    (root / "doc.yaml").write_text(text, encoding="utf-8")
    ctx = Context(store, AT, session="s-maintainer", formed_by=user, workdir=Workdir(root), sync=lambda touched=None: sync(store.driver, None, None, touched))
    out = COMMIT.call(ctx, {"files": ["doc.yaml"], "message": "test", "dry_run": not commit}).details
    return {**out.get("graph_doc", {}), "status": out["status"]} if "graph_doc" in out else out


class Writer:
    """一个写者：自己的工作目录与登录身份。"""

    def __init__(self, store: Store, name: str, root: Path) -> None:
        self.store, self.name, self.root = store, name, root
        root.mkdir(parents=True, exist_ok=True)

    def ctx(self) -> Context:
        refresh = lambda touched=None: sync(self.store.driver, None, None, touched)  # noqa: E731
        return Context(self.store, AT, session=f"s-{self.name}", formed_by=self.name, workdir=Workdir(self.root), sync=refresh)

    def write(self, path: str, text: str) -> str:
        file = self.root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text, encoding="utf-8")
        return path

    def read(self, path: str) -> str:
        return (self.root / path).read_text(encoding="utf-8")

    def fetch(self, *ids: str) -> dict[str, Any]:
        """checkout 产物：``items`` 是取出的产物，``missing`` 是取不到的。"""
        out = CHECKOUT.call(self.ctx(), {"ids": list(ids)}).details
        items = [{k: v for k, v in f.items() if k != "kind"} for f in out["files"] if f["kind"] == "artifact"]
        return {"items": items, "missing": [{"artifact": m["id"], "msg": m["msg"]} for m in out["missing"]]}

    def commit(self, text: str) -> dict[str, Any]:
        """commit 一份 graph-doc，返回其中 graph-doc 部分的结果。"""
        self.write("doc.yaml", text)
        out = COMMIT.call(self.ctx(), {"files": ["doc.yaml"], "message": "test"}).details
        return {**out.get("graph_doc", {}), "status": out["status"]}

    def check_in(self, *paths: str, message: str = "Edit.", confirm: bool = False, **extra: Any) -> dict[str, Any]:
        """commit 产物文档；``confirm`` 为假时只检查（dry_run）。返回其中产物部分的结果。"""
        request = {"files": list(paths), "message": message, "dry_run": not confirm, **extra}
        out = COMMIT.call(self.ctx(), request).details
        return out.get("artifacts", out)


@pytest.fixture(scope="module")
def writers(store: Store, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Writer]:
    base = tmp_path_factory.mktemp("work")
    return {name: Writer(store, name, base / name) for name in ("claude", "bob", "alice")}
