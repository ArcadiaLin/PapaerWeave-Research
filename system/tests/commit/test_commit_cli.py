"""命令行入口背后的流程：拒绝旧库、首次提交时建库、提交后补算向量，以及冲突的返回。

数据库部分只在设置了 ``GRAPH_VC_TEST_NEO4J_URI`` 时运行（infra/neo4j-test），不会连 neo4j-e09。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
from conftest import AT, DLINEAR, SEED, write_material

from paperweave.commit import Context, Neo4jReader, conflict
from paperweave.model.schema import FULLTEXT
from paperweave.operators.db.commit import run
from paperweave.store import UnversionedDatabaseError, check_versioned, open_graph
from paperweave.store.embedding import REL_VECTOR_INDEX, VECTOR_INDEXES
from graph_vc import Conflict, ConflictError, VersionedGraph


@pytest.fixture
def store(test_driver: Any, tmp_path: Path) -> tuple[VersionedGraph, Context]:
    write_material(tmp_path, "papers/2023-DLinear/paper.md")
    graph = open_graph(test_driver, file_root=tmp_path)
    return graph, Context(Neo4jReader(graph, test_driver), "test", AT, tmp_path)


def submit(store: tuple[VersionedGraph, Context], driver: Any, text: str, **kwargs: Any) -> dict[str, Any]:
    graph, ctx = store
    return run(text, graph=graph, driver=driver, ctx=ctx, **kwargs)


def test_a_database_without_version_history_is_refused(store, test_driver) -> None:
    test_driver.execute_query("CREATE (:Concept:Method {id: 'method_0001', name: 'legacy'})")
    with pytest.raises(UnversionedDatabaseError):
        check_versioned(test_driver)
    for commit in (False, True):
        with pytest.raises(UnversionedDatabaseError):
            submit(store, test_driver, SEED, commit=commit)
    assert test_driver.execute_query("MATCH (n) RETURN count(n) AS c").records[0]["c"] == 1


def test_first_apply_sets_up_the_database(store, test_driver) -> None:
    assert submit(store, test_driver, SEED, commit=False)["status"] == "ready"  # 空库可以 dry_run，不建任何东西
    assert test_driver.execute_query("MATCH (n) RETURN count(n) AS c").records[0]["c"] == 0

    out = submit(store, test_driver, SEED, commit=True)
    assert out["status"] == "committed" and out["commit"] == "commit_000001"
    indexes = {r["name"] for r in test_driver.execute_query("SHOW INDEXES YIELD name").records}
    assert set(FULLTEXT) | set(VECTOR_INDEXES) | {REL_VECTOR_INDEX} <= indexes
    constraints = {r["name"] for r in test_driver.execute_query("SHOW CONSTRAINTS YIELD name").records}
    assert {"namekey_key", "experiment_key", "content_key"} <= constraints
    check_versioned(test_driver)  # 已有版本记录

    assert submit(store, test_driver, SEED, commit=True)["status"] == "blocked"  # 名称已被占用


def test_embedding_failure_does_not_undo_the_commit(store, test_driver) -> None:
    calls = []

    def embed() -> int:
        calls.append(1)
        raise httpx.ConnectError("embedding service unreachable")

    assert submit(store, test_driver, SEED, commit=True, embed=lambda: 0)["status"] == "committed"
    out = submit(store, test_driver, DLINEAR, commit=True, message="DLinear", embed=embed)
    assert out["status"] == "committed" and calls == [1]
    assert [w["rule"] for w in out["warnings"]] == ["embedding"]
    assert store[0].head() == out["commit"]

    assert submit(store, test_driver, DLINEAR, commit=False)["status"] == "blocked"
    assert submit(store, test_driver, DLINEAR, commit=True, embed=embed)["status"] == "blocked"
    assert calls == [1]  # 没有提交就不补算


def test_conflict_result() -> None:
    error = ConflictError([Conflict("method_0001", "property name differs", "DLinear", "D-Linear")])
    assert conflict(error) == {
        "graph-result": "v0.1",
        "status": "conflict",
        "errors": [
            {
                "rule": "conflict",
                "at": "method_0001",
                "msg": "property name differs",
                "fix": "the database changed after the dry run; read the affected nodes again and resubmit",
            }
        ],
    }
