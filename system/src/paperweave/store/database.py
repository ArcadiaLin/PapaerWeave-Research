"""写入所连的库：拒绝没有版本记录的旧库，建立版本记录、约束与索引。

旧写入路径建出的库（tag ``e09-legacy-write``，如现有的 neo4j-e09）有数据却没有 ``Branch`` 节点；
它的 NameKey 没有 ``id``，还有冻结模型之外的 Metric，新路径既不能在上面求差，也不迁移它，只能重建。
"""

from __future__ import annotations

from pathlib import Path

from neo4j import Driver, RoutingControl

from graph_vc import VersionedGraph

from ..model.schema import (
    CONSTRAINTS,
    DERIVED_FIELDS,
    DESCRIBED_RELS,
    FULLTEXT,
    NODE_LABELS,
    REL_TYPES,
    RETIRED_CONSTRAINTS,
)
from .embedding import EMBED_DIM, REL_VECTOR_INDEX, VECTOR_INDEXES


class UnversionedDatabaseError(RuntimeError):
    """库中有数据，但没有版本记录：不是由新写入路径建出的库。"""


def open_graph(driver: Driver, *, database: str | None = None, file_root: Path) -> VersionedGraph:
    """按 PaperWeave 的词表与派生属性打开版本化的图；材料路径相对于 ``file_root``。"""
    return VersionedGraph(
        driver,
        database=database,
        file_root=file_root,
        node_labels=NODE_LABELS,
        rel_types=REL_TYPES,
        unversioned_props=DERIVED_FIELDS,
    )


def check_versioned(driver: Driver, *, database: str | None = None) -> None:
    """空库或已有分支记录的库才能读写；否则抛出 :class:`UnversionedDatabaseError`。"""
    record = driver.execute_query(
        """OPTIONAL MATCH (b:Branch) WITH count(b) AS branches
           OPTIONAL MATCH (n) RETURN branches, count(n) AS nodes""",
        database_=database,
        routing_=RoutingControl.READ,
    ).records[0]
    if record["nodes"] and not record["branches"]:
        raise UnversionedDatabaseError(
            f"the database has {record['nodes']} nodes but no version history; it was not built by this write path "
            "(the legacy neo4j-e09 database is rebuilt, not migrated)"
        )


def setup_database(graph: VersionedGraph, driver: Driver, *, database: str | None = None) -> None:
    """建立版本记录与 main 分支、模型的约束、全文索引与向量索引，删除已退役的约束；可重复调用。

    全部是 ``IF NOT EXISTS`` / ``IF EXISTS``：已有同名索引的配置与声明不一致时不会改动它。
    """
    graph.setup()
    for name in RETIRED_CONSTRAINTS:
        driver.execute_query(f"DROP CONSTRAINT {name} IF EXISTS", database_=database)
    for statement in index_statements():
        driver.execute_query(statement, database_=database)
    driver.execute_query("CALL db.awaitIndexes(300)", database_=database)


def index_statements() -> list[str]:
    options = f"OPTIONS {{indexConfig: {{`vector.dimensions`: {EMBED_DIM}, `vector.similarity_function`: 'cosine'}}}}"
    statements = list(CONSTRAINTS)
    for name, (label, fields, analyzer) in FULLTEXT.items():
        on = ", ".join(f"n.{f}" for f in fields)
        statements.append(
            f"CREATE FULLTEXT INDEX {name} IF NOT EXISTS FOR (n:{label}) ON EACH [{on}] "
            f"OPTIONS {{indexConfig: {{`fulltext.analyzer`: '{analyzer}'}}}}"
        )
    for name, label in VECTOR_INDEXES.items():
        statements.append(f"CREATE VECTOR INDEX {name} IF NOT EXISTS FOR (n:{label}) ON n.embedding {options}")
    statements.append(
        f"CREATE VECTOR INDEX {REL_VECTOR_INDEX} IF NOT EXISTS "
        f"FOR ()-[r:{'|'.join(DESCRIBED_RELS)}]-() ON r.embedding {options}"
    )
    return statements


__all__ = ["UnversionedDatabaseError", "check_versioned", "index_statements", "open_graph", "setup_database"]
