"""写入所连的库：拒绝没有版本记录的旧库，建立版本记录、约束与索引。

没有 ``Branch`` 节点却有数据的库不是由这条写入路径建出的，不迁移，只能重建。V2 的库（tag ``v2-pilot3``）字段不同，
同样从零重建。
"""

from __future__ import annotations

from pathlib import Path

from neo4j import Driver, RoutingControl

from graph_vc import VersionedGraph

from ..model.schema import (
    CONSTRAINTS,
    DERIVED_FIELDS,
    EDGE_TEXT_INDEX,
    EDGE_VECTOR_INDEX,
    INDEXED_RELS,
    NODE_LABELS,
    NODE_TEXT_INDEX,
    NODE_VECTOR_INDEX,
    REL_TYPES,
    RETIRED_CONSTRAINTS,
    SEARCHABLE,
)
from .embedding import EMBED_DIM


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
    """约束、两个全文索引（节点与边的 ``search_text``）与两个向量索引（节点与边的 ``embedding``）。"""
    options = f"OPTIONS {{indexConfig: {{`vector.dimensions`: {EMBED_DIM}, `vector.similarity_function`: 'cosine'}}}}"
    analyzer = "OPTIONS {indexConfig: {`fulltext.analyzer`: 'english'}}"
    rels = "|".join(INDEXED_RELS)
    return [
        *CONSTRAINTS,
        "CREATE INDEX namekey_normalized IF NOT EXISTS FOR (k:NameKey) ON (k.normalized)",
        f"CREATE FULLTEXT INDEX {NODE_TEXT_INDEX} IF NOT EXISTS FOR (n:{SEARCHABLE}) ON EACH [n.search_text] {analyzer}",
        f"CREATE FULLTEXT INDEX {EDGE_TEXT_INDEX} IF NOT EXISTS FOR ()-[r:{rels}]-() ON EACH [r.search_text] {analyzer}",
        f"CREATE VECTOR INDEX {NODE_VECTOR_INDEX} IF NOT EXISTS FOR (n:{SEARCHABLE}) ON n.embedding {options}",
        f"CREATE VECTOR INDEX {EDGE_VECTOR_INDEX} IF NOT EXISTS FOR ()-[r:{rels}]-() ON r.embedding {options}",
    ]


__all__ = ["UnversionedDatabaseError", "check_versioned", "index_statements", "open_graph", "setup_database"]
