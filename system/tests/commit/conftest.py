"""写入路径测试的共用部件：内存中的图、材料文件与种子文档，以及测试实例的连接。"""

from __future__ import annotations

import os
import textwrap
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from paperweave.commit import Context, Deduper, MemoryReader, Prepared, allocate_ids, prepare
from graph_vc import GraphState

AT = "2026-10-05T12:00:00+00:00"

# 数据库测试只连显式给出的测试实例（infra/neo4j-test，端口 7688），不会连 neo4j-e09
TEST_URI = os.environ.get("GRAPH_VC_TEST_NEO4J_URI")
TEST_AUTH = (
    os.environ.get("GRAPH_VC_TEST_NEO4J_USER", "neo4j"),
    os.environ.get("GRAPH_VC_TEST_NEO4J_PASSWORD", "password"),
)

SEED = """
graph-doc: v0.2
create:
  $tsf:
    kind: Task
    name: Time series forecasting
    alias: [TSF]
    description: Predict future values of a series from its past.
  $ltsf:
    kind: Task
    name: Long-term time series forecasting
    alias: [LTSF]
    description: Forecasting with a long horizon.
    BROADER: [$tsf]
  $tf:
    kind: Method
    name: Transformer-based forecasting
    description: Forecasting models built on Transformer architectures.
  $ett:
    kind: Dataset
    name: ETT
    description: Electricity transformer temperature data.
    identities: ["url:https://github.com/zhouhaoyi/ETDataset"]
    FOR_TASK: [$ltsf]
  $etth1:
    kind: Dataset
    name: ETTh1
    description: Hourly subset of ETT.
    identities: ["url:https://github.com/zhouhaoyi/ETDataset"]
    PART_OF: [$ett]
    FOR_TASK: [$ltsf]
"""
# 种子按文档顺序、按前缀分配：task_0001 tsf、task_0002 ltsf、method_0001 tf、dataset_0001 ett、dataset_0002 etth1

DLINEAR = """
graph-doc: v0.2
create:
  $paper:
    kind: Paper
    name: Are Transformers Effective for Time Series Forecasting?
    identities: ["arxiv:2205.13504"]
    year: 2023
    source: [2205.13504v3]
    description: |
      Questions whether Transformers are effective for LTSF and introduces DLinear.
    extra:
      venue: AAAI 2023
  $dlinear:
    kind: Method
    name: DLinear
    alias: [D-Linear]
    description: |
      A linear model on a trend and remainder decomposition.
    BROADER: [method_0001]
  $code:
    kind: Code
    name: LTSF-Linear
    identities: ["url:https://github.com/cure-lab/LTSF-Linear"]
    IMPLEMENTS:
      $dlinear:
        anchor: [2205.13504v3::20:21]
  $exp:
    kind: Experiment
    paper: $paper
    anchor: [2205.13504v3::198:240]
    figures: [S5.T2, A3.T9]
    description: |
      Compare DLinear with Transformer baselines on nine datasets.
    EVALUATES:
      $dlinear:
        role: target
        result: own
      method_0001:
        role: baseline
        result: cited
    USES:
      dataset_0002:
        role: evaluation_data
        printed_as: ETTh1
    ON_TASK: [task_0002]
  $claim:
    kind: Claim
    paper: $paper
    anchor: [2205.13504v3::10:14]
    description: |
      DLinear outperforms Transformer methods in most settings.
    ABOUT: [$dlinear, task_0002]
  $contrib:
    kind: Contribution
    paper: $paper
    anchor: [2205.13504v3::40:44]
    description: |
      Introduces a simple linear baseline for LTSF.
    ABOUT: [$dlinear]
  $exp2:
    kind: Experiment
    paper: $paper
    anchor: [2205.13504v3::250:260]
    figures: [S5.T4]
    description: |
      Ablation of the decomposition.
    EVALUATES:
      $dlinear:
        role: target
    SUPPORTS: [$claim]
"""
# 写入后：paper_0001、method_0002 dlinear、code_0001、exp_0001、claim_0001、contrib_0001、exp_0002


class Counters:
    """内存中的 id 分配，与 VersionedGraph.allocate_ids 的格式相同。"""

    def __init__(self) -> None:
        self.last: dict[str, int] = defaultdict(int)

    def allocate_ids(self, prefix: str, count: int = 1) -> list[str]:
        start = self.last[prefix]
        self.last[prefix] += count
        return [f"{prefix}_{n:04d}" for n in range(start + 1, start + count + 1)]


class MemoryGraph:
    """在内存状态上走与 apply 相同的流程：dry_run、分配 id、用真实 id 准备、应用。"""

    def __init__(self, root: Path):
        self.root = root
        self.state = GraphState()
        self.counters = Counters()
        self.deduper: Deduper | None = None

    def context(self, source: str = "test", user: str = "claude") -> Context:
        return Context(MemoryReader(self.state), source, AT, self.root, user, self.deduper)

    def dry_run(self, text: str, source: str = "test", user: str = "claude") -> Prepared:
        return prepare(text, self.context(source, user))

    def submit(self, text: str, source: str = "test", user: str = "claude") -> Prepared:
        dry = self.dry_run(text, source, user)
        if not dry.ok:
            return dry
        assert dry.document is not None
        prepared = prepare(text, self.context(source, user), allocate_ids(dry.document, self.counters))
        assert prepared.ok, prepared.errors
        assert prepared.changeset is not None
        self.state = self.state.apply(prepared.changeset)
        return prepared


def write_source(root: Path, source: str, lines: int = 300) -> None:
    """来源目录（材料根目录下的 sources/）中的一篇论文：每行写着来源 ID 与行号。"""
    path = f"sources/{source}/paper.md"
    file = root / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text("".join(f"{path} line {i}\n" for i in range(1, lines + 1)), encoding="utf-8")


@pytest.fixture
def graph(tmp_path: Path) -> MemoryGraph:
    write_source(tmp_path, "2205.13504v3")
    write_source(tmp_path, "2211.14730v2")
    g = MemoryGraph(tmp_path)
    assert g.submit(SEED, "seed:tsf").ok
    return g


@pytest.fixture
def ingested(graph: MemoryGraph) -> MemoryGraph:
    prepared = graph.submit(DLINEAR, "paper:2023-DLinear")
    assert prepared.ok, prepared.errors
    return graph


@pytest.fixture
def test_driver() -> Iterator[Any]:
    """测试实例的连接：未配置时跳过；要求开始时库为空，结束后清空库、约束与索引。"""
    if TEST_URI is None:
        pytest.skip("GRAPH_VC_TEST_NEO4J_URI is not set")
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(TEST_URI, auth=TEST_AUTH, notifications_disabled_classifications=["UNRECOGNIZED"])
    count = driver.execute_query("MATCH (n) RETURN count(n) AS c").records[0]["c"]
    if count:
        driver.close()
        pytest.skip(f"refusing to run: test database at {TEST_URI} is not empty ({count} nodes)")
    yield driver
    driver.execute_query("MATCH (n) DETACH DELETE n")
    for record in driver.execute_query("SHOW CONSTRAINTS YIELD name").records:
        driver.execute_query(f"DROP CONSTRAINT {record['name']}")
    for record in driver.execute_query("SHOW INDEXES YIELD name, type WHERE type <> 'LOOKUP' RETURN name").records:
        driver.execute_query(f"DROP INDEX {record['name']}")
    driver.close()


def rules(prepared: Prepared) -> set[str]:
    return {p.rule for p in prepared.errors}


def doc(body: str) -> str:
    """补上文档头；正文按原样（各节顶格）写出。"""
    return "graph-doc: v0.2\n" + textwrap.dedent(body).strip("\n") + "\n"
