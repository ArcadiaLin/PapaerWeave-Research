"""读取算子测试的共用部件：在测试实例上写入一小份图，供各测试只读使用。

只在设置了 ``GRAPH_VC_TEST_NEO4J_URI`` 时运行（infra/neo4j-test，端口 7688），要求开始时库为空，结束后清空库、
约束与索引。不会连 neo4j-e09。
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from paperweave.commit import Context, Neo4jReader
from paperweave.operators.db.commit import run
from paperweave.store import Store, open_graph

TEST_URI = os.environ.get("GRAPH_VC_TEST_NEO4J_URI")
TEST_AUTH = (
    os.environ.get("GRAPH_VC_TEST_NEO4J_USER", "neo4j"),
    os.environ.get("GRAPH_VC_TEST_NEO4J_PASSWORD", "password"),
)
AT = "2026-10-05T12:00:00+00:00"
MATERIAL = "papers/2023-DLinear/paper.md"

SEED = """
graph-doc: v0.1
by: seed
nodes:
  $tsf:
    kind: Task
    name: Time series forecasting
    aliases: [TSF]
    definition: Predict future values of a series from its past.
  $ltsf:
    kind: Task
    name: Long-term time series forecasting
    aliases: [LTSF]
    definition: Forecasting with a long horizon.
    BROADER: [$tsf]
  $linear:
    kind: Method
    name: Linear forecasting model
    definition: Models that map the look-back window to the horizon with a linear layer.
  $tf:
    kind: Method
    name: Transformer-based forecasting
    definition: Forecasting models built on Transformer architectures.
  $ett:
    kind: Dataset
    name: ETT
    description: Electricity transformer temperature data.
    FOR_TASK: [$ltsf]
  $etth1:
    kind: Dataset
    name: ETTh1
    description: Hourly subset of ETT.
    PART_OF: [$ett]
  $weather:
    kind: Dataset
    name: Weather
    description: Meteorological indicators recorded every ten minutes.
"""
# task_0001 tsf、task_0002 ltsf、method_0001 linear、method_0002 tf、dataset_0001 ett、dataset_0002 etth1、
# dataset_0003 weather

PAPER = """
graph-doc: v0.1
by: claude
nodes:
  $paper:
    kind: Paper
    name: Are Transformers Effective for Time Series Forecasting?
    identifiers: ["arxiv:2205.13504"]
    year: 2023
    material: papers/2023-DLinear/paper.md
    description: Questions whether Transformers are effective for LTSF and introduces DLinear.
  $dlinear:
    kind: Method
    name: DLinear
    aliases: [D-Linear]
    definition: A linear model on a trend and remainder decomposition.
    BROADER: [method_0001]
  $main:
    kind: Experiment
    anchors: [S5.T2]
    text: Multivariate long-term forecasting comparing DLinear with Transformer baselines.
    FROM:
      - {to: $paper, locators: ["5.2 Comparison::10:20"]}
    EVALUATES:
      - {to: $dlinear, role: target}
      - to: method_0002
        role: baseline
        description: Results taken from FEDformer.
        source_refs: ["$paper::5.1::21:21"]
    USES:
      - {to: dataset_0002, role: evaluation_data}
      - {to: dataset_0003, role: evaluation_data}
    ON_TASK: [task_0002]
  $ablation:
    kind: Experiment
    anchors: [S5.T7]
    text: Ablation of the decomposition in DLinear on weather data.
    FROM:
      - {to: $paper, locators: ["5.5 Ablation::30:35"]}
    EVALUATES:
      - {to: $dlinear, role: target}
    USES:
      - dataset_0003
    ON_TASK: [task_0002]
"""
# paper_0001、method_0003 dlinear、exp_0001 main、exp_0002 ablation（USES 没有 role）


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
    write_material(root, MATERIAL)
    graph = open_graph(driver, file_root=root)
    try:
        for source, text in (("seed:tsf", SEED), ("paper:2023-DLinear", PAPER)):
            ctx = Context(Neo4jReader(graph, driver), source, AT, root)
            out = run(text, graph=graph, driver=driver, ctx=ctx, commit=True)
            assert out["status"] == "committed", out
        yield Store(driver, graph, root)
    finally:
        driver.execute_query("MATCH (n) DETACH DELETE n")
        for record in driver.execute_query("SHOW CONSTRAINTS YIELD name").records:
            driver.execute_query(f"DROP CONSTRAINT {record['name']}")
        for record in driver.execute_query("SHOW INDEXES YIELD name, type WHERE type <> 'LOOKUP' RETURN name").records:
            driver.execute_query(f"DROP INDEX {record['name']}")
        driver.close()


def write_material(root: Path, path: str, lines: int = 60) -> None:
    file = root / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text("".join(f"line {i}\n" for i in range(1, lines + 1)), encoding="utf-8")


def problems(exc: Any) -> list[str]:
    """契约错误中出错的参数位置。"""
    return [p["at"] for p in exc.value.errors]
