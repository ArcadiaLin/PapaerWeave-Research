"""知识访问与 commit 测试的共用部件：在测试实例上经 commit 写入一小份图，供各测试读取。

只在设置了 ``GRAPH_VC_TEST_NEO4J_URI`` 时运行，要求开始时库为空，结束后清空库、约束与索引。向量关闭（只有全文与
精确命中两路），结果因此确定。
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from paperweave.draft import Workdir
from paperweave.operators.base import Context
from paperweave.store import Store, open_graph
from paperweave.store.derived import sync
from paperweave.tools import TOOLS

TEST_URI = os.environ.get("GRAPH_VC_TEST_NEO4J_URI")
TEST_AUTH = (
    os.environ.get("GRAPH_VC_TEST_NEO4J_USER", "neo4j"),
    os.environ.get("GRAPH_VC_TEST_NEO4J_PASSWORD", "password"),
)
AT = "2026-10-16T12:00:00+00:00"
MATERIAL = "papers/2205.13504/paper.md"
PAPER_TEXT = "".join(
    ["# Are Transformers Effective\n", "## Abstract\n", *[f"abstract line {i}\n" for i in range(3, 10)],
     "## 5 Experiments\n", "### 5.2 Comparison\n", *[f"comparison line {i}\n" for i in range(12, 61)], "- •\n"]
)  # 第 2 行起是摘要，第 11 行起是 5.2 节，第 61 行只有列表符号

SEED = """graph-doc: v0.2
create:
  $ltsf:
    kind: Task
    name: Long-term time series forecasting
    alias: [LTSF]
    description: Forecasting many steps ahead.
  $tf:
    kind: Method
    name: Transformer-based forecasting
    description: Forecasting models built on Transformer architectures.
  $linear:
    kind: Method
    name: Linear forecasting model
    description: Models mapping the look-back window to the horizon with one linear layer.
  $etth1:
    kind: Dataset
    name: ETTh1
    description: Hourly electricity transformer temperature data.
  $paper:
    kind: Paper
    name: Are Transformers Effective for Time Series Forecasting?
    identities: [arxiv:2205.13504]
    year: 2023
    material: papers/2205.13504/paper.md
    description: Questions whether Transformers are effective for LTSF and introduces DLinear.
  $dlinear:
    kind: Method
    name: DLinear
    description: A linear model on a trend and remainder decomposition.
    BROADER:
      $linear:
    RELATES_TO:
      $tf: {description: "DLinear is proposed as a simple baseline that questions Transformer forecasters"}
  $main:
    kind: Experiment
    paper: $paper
    anchor: [12:20]
    figures: [S5.T2]
    description: Multivariate long-term forecasting comparing DLinear with Transformer baselines.
    EVALUATES:
      $dlinear: {role: target, result: own}
      $tf: {role: baseline, result: cited}
    USES:
      $etth1: {role: evaluation_data, printed_as: ETTh1}
    ON_TASK:
      $ltsf:
  $claim:
    kind: Claim
    paper: $paper
    anchor: [3:5]
    description: A one-layer linear model outperforms Transformer forecasters on long-term benchmarks.
    ABOUT:
      $dlinear:
  $main2claim:
    kind: Contribution
    paper: $paper
    anchor: [6:7]
    description: Introduces DLinear as an embarrassingly simple baseline.
    ABOUT:
      $dlinear:
"""
# task_0001 ltsf、method_0001 tf、method_0002 linear、dataset_0001 etth1、paper_0001、method_0003 dlinear、
# exp_0001、claim_0001、contrib_0001（按 $ 名在 create 中出现的顺序分配）


class Writer:
    """一个写者：自己的工作目录与登录身份，经工具调用。"""

    def __init__(self, store: Store, name: str, root: Path) -> None:
        self.store, self.name, self.root = store, name, root
        root.mkdir(parents=True, exist_ok=True)

    def ctx(self) -> Context:
        refresh = lambda touched=None: sync(self.store.driver, None, None, touched)  # noqa: E731
        return Context(self.store, AT, session=f"s-{self.name}", formed_by=self.name, workdir=Workdir(self.root), sync=refresh)

    def call(self, op: str, **params: Any) -> Any:
        return TOOLS[op].call(self.ctx(), params)

    def commit(self, text: str, *, dry_run: bool = False, name: str = "doc.yaml") -> dict[str, Any]:
        (self.root / name).write_text(text, encoding="utf-8")
        out = self.call("commit", files=[name], message="test", dry_run=dry_run).details
        return {**out.get("graph_doc", {}), "status": out["status"]} if "graph_doc" in out else out


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Store]:
    if TEST_URI is None:
        pytest.skip("GRAPH_VC_TEST_NEO4J_URI is not set")
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(TEST_URI, auth=TEST_AUTH, notifications_disabled_classifications=["UNRECOGNIZED", "DEPRECATION"])
    count = driver.execute_query("MATCH (n) RETURN count(n) AS c").records[0]["c"]
    if count:
        driver.close()
        pytest.skip(f"refusing to run: test database at {TEST_URI} is not empty ({count} nodes)")
    root = tmp_path_factory.mktemp("materials")
    (root / MATERIAL).parent.mkdir(parents=True)
    (root / MATERIAL).write_text(PAPER_TEXT, encoding="utf-8")
    try:
        seeded = Store(driver, open_graph(driver, file_root=root), root)
        done = Writer(seeded, "seed", tmp_path_factory.mktemp("seed")).commit(SEED)
        assert done["status"] == "committed", done
        yield seeded
    finally:
        driver.execute_query("MATCH (n) DETACH DELETE n")
        for record in driver.execute_query("SHOW CONSTRAINTS YIELD name").records:
            driver.execute_query(f"DROP CONSTRAINT {record['name']}")
        for record in driver.execute_query("SHOW INDEXES YIELD name, type WHERE type <> 'LOOKUP' RETURN name").records:
            driver.execute_query(f"DROP INDEX {record['name']}")
        driver.close()


@pytest.fixture(scope="module")
def writer(store: Store, tmp_path_factory: pytest.TempPathFactory) -> Writer:
    return Writer(store, "alice", tmp_path_factory.mktemp("alice"))
