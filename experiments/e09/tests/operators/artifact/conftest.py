"""共同产物（CheckIn、FetchArtifact）测试的共用部件：在测试实例上写入一小份图，产物文档写到临时的材料根目录，
写者的工作目录也是临时目录。

只在设置了 ``GRAPH_VC_TEST_NEO4J_URI`` 时运行，要求开始时库为空，结束后清空库、约束与索引。不会连 neo4j-e09。
每个测试模块重建一次图，模块内的测试按顺序共享写入的产物。
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from e09.commit import Context as CommitContext
from e09.commit import Neo4jReader
from e09.draft import Workdir
from e09.operators.base import Context
from e09.operators.db import CHECK_IN, COMMIT, FETCH_ARTIFACT
from e09.operators.db.commit import run
from e09.store import Store, open_graph, setup_database

TEST_URI = os.environ.get("GRAPH_VC_TEST_NEO4J_URI")
TEST_AUTH = (
    os.environ.get("GRAPH_VC_TEST_NEO4J_USER", "neo4j"),
    os.environ.get("GRAPH_VC_TEST_NEO4J_PASSWORD", "password"),
)
AT = "2026-10-14T12:00:00+00:00"
MATERIAL = "papers/2023-DLinear/paper.md"

GRAPH = """
graph-doc: v0.1
by: seed
nodes:
  $ltsf:
    kind: Task
    name: Long-term time series forecasting
    definition: Forecasting with a long horizon.
  $tf:
    kind: Method
    name: Transformer-based forecasting
    definition: Forecasting models built on Transformer architectures.
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
    definition: A linear model on a trend and remainder decomposition.
  $main:
    kind: Experiment
    anchors: [S5.T2]
    text: Multivariate long-term forecasting comparing DLinear with Transformer baselines.
    FROM:
      - {to: $paper, locators: ["5.2 Comparison::10:20"]}
    EVALUATES:
      - {to: $dlinear, role: target}
      - {to: $tf, role: baseline}
    USES:
      - {to: $etth1, role: evaluation_data}
    ON_TASK: [$ltsf]
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
def store(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Store]:
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
    file.write_text("".join(f"line {i}\n" for i in range(1, 61)), encoding="utf-8")
    graph = open_graph(driver, file_root=root)
    try:
        seeded = Store(driver, graph, root)
        ctx = CommitContext(Neo4jReader(graph, driver), "seed:test", AT, root)
        run(GRAPH, graph=graph, driver=driver, ctx=ctx, commit=True)
        setup_database(graph, driver)
        yield seeded
    finally:
        driver.execute_query("MATCH (n) DETACH DELETE n")
        for record in driver.execute_query("SHOW CONSTRAINTS YIELD name").records:
            driver.execute_query(f"DROP CONSTRAINT {record['name']}")
        for record in driver.execute_query("SHOW INDEXES YIELD name, type WHERE type <> 'LOOKUP' RETURN name").records:
            driver.execute_query(f"DROP INDEX {record['name']}")
        driver.close()


def commit_doc(store: Store, text: str) -> dict[str, Any]:
    """经 Commit 写入路径提交一份 graph-doc。"""
    ctx = CommitContext(Neo4jReader(store.graph, store.driver), "test", AT, store.material_root)
    return run(text, graph=store.graph, driver=store.driver, ctx=ctx, commit=True)


class Writer:
    """一个写者：自己的工作目录与登录身份。"""

    def __init__(self, store: Store, name: str, root: Path) -> None:
        self.store, self.name, self.root = store, name, root
        root.mkdir(parents=True, exist_ok=True)

    def ctx(self) -> Context:
        return Context(self.store, AT, session=f"s-{self.name}", formed_by=self.name, workdir=Workdir(self.root))

    def write(self, path: str, text: str) -> str:
        file = self.root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text, encoding="utf-8")
        return path

    def read(self, path: str) -> str:
        return (self.root / path).read_text(encoding="utf-8")

    def fetch(self, *ids: str, at: str | None = None) -> dict[str, Any]:
        request: dict[str, Any] = {"artifact": list(ids)}
        if at is not None:
            request["at"] = at
        return FETCH_ARTIFACT.call(self.ctx(), request).details

    def commit(self, text: str) -> dict[str, Any]:
        return COMMIT.call(self.ctx(), {"doc": text, "source": "test", "dedup": False}).details

    def check_in(self, *paths: str, message: str = "Edit.", **extra: Any) -> dict[str, Any]:
        request = {"artifact_doc": list(paths), "update_abstract": message, **extra}
        return CHECK_IN.call(self.ctx(), request).details


@pytest.fixture(scope="module")
def writers(store: Store, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Writer]:
    base = tmp_path_factory.mktemp("work")
    return {name: Writer(store, name, base / name) for name in ("claude", "bob", "alice")}
