"""写入路径在真实 Neo4j 上的往返：结果与内存中走同一流程得到的状态一致。

只在设置了 ``GRAPH_VC_TEST_NEO4J_URI`` 时运行（infra/neo4j-test，端口 7688），要求开始时库为空，结束后清空。
不会连 neo4j-e09。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from conftest import AT, DLINEAR, SEED, MemoryGraph, doc, write_material

from paperweave.commit import Context, Neo4jReader, apply
from paperweave.store import open_graph
from graph_vc import VersionedGraph


@pytest.fixture
def store(test_driver: Any, tmp_path: Path) -> tuple[VersionedGraph, Context]:
    write_material(tmp_path, "papers/2023-DLinear/paper.md")
    graph = open_graph(test_driver, file_root=tmp_path)
    graph.setup()
    return graph, Context(Neo4jReader(graph, test_driver), "test", AT, tmp_path)


def test_database_matches_the_in_memory_run(store, tmp_path: Path) -> None:
    graph, ctx = store
    memory = MemoryGraph(tmp_path)
    edits = [SEED, DLINEAR, doc("method_0002:\n  aliases: [Decomposition-Linear]\ndataset_0002:\n  kind: Benchmark")]
    for text in edits:
        prepared, record = apply(text, graph, ctx, message="test")
        assert record is not None, prepared.errors
        assert memory.submit(text).ok
    assert graph.snapshot() == memory.state

    history = graph.history()
    assert [c.source for c in history] == ["test"] * 3
    assert history[1].meta["ids"]["$paper"] == "paper_0001"
    assert history[1].input == DLINEAR


def test_resubmission_is_blocked_and_writes_nothing(store) -> None:
    graph, ctx = store
    assert apply(SEED, graph, ctx)[1] is not None
    assert apply(DLINEAR, graph, ctx)[1] is not None
    before, head = graph.snapshot(), graph.head()

    prepared, record = apply(DLINEAR, graph, ctx)
    assert record is None
    assert {p.rule for p in prepared.errors} == {"identifier-taken", "name-taken", "material"}
    assert graph.snapshot() == before and graph.head() == head


def test_revert_restores_names_and_material(store) -> None:
    graph, ctx = store
    apply(SEED, graph, ctx)
    before = graph.snapshot()
    _, record = apply(DLINEAR, graph, ctx)
    graph.revert(record.id, author="claude")
    assert graph.snapshot() == before
