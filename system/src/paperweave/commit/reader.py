"""写入路径读取现状的接口：局部状态与按属性查找。

翻译与检查只依赖 :class:`Reader`，所以既能在内存状态上测试（:class:`MemoryReader`），
也能在 Neo4j 上运行（:class:`Neo4jReader`）。读取都在提交事务之外；读取之后库若被改动，
提交时 graph-vc 核对改前状态会发现。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Protocol

from neo4j import Driver, RoutingControl

from graph_vc import RESERVED_LABELS, GraphState, VersionedGraph


class Reader(Protocol):
    def local_state(self, ids: Iterable[str]) -> GraphState:
        """这些节点、它们的全部关系，以及关系另一端的节点。"""
        ...

    def find(self, prop: str, value: Any, *, label: str | None = None) -> set[str]:
        """属性 ``prop`` 等于 ``value``（列表属性则包含 ``value``）的节点 id。"""
        ...


class MemoryReader:
    """在一个完整的内存状态上读取，用于测试。"""

    def __init__(self, state: GraphState):
        self.state = state

    def local_state(self, ids: Iterable[str]) -> GraphState:
        wanted = {i for i in ids if i in self.state.nodes}
        edges = {k: dict(v) for k, v in self.state.edges.items() if k.src in wanted or k.dst in wanted}
        ends = wanted | {k.src for k in edges} | {k.dst for k in edges}
        return GraphState({i: self.state.nodes[i] for i in ends}, edges)

    def find(self, prop: str, value: Any, *, label: str | None = None) -> set[str]:
        found = set()
        for node_id, node in self.state.nodes.items():
            if label is not None and label not in node.labels:
                continue
            current = node.props.get(prop)
            if current == value or (isinstance(current, list) and value in current):
                found.add(node_id)
        return found


class Neo4jReader:
    """经 :class:`VersionedGraph` 读取局部状态，按属性查找时直接查询 Neo4j。"""

    def __init__(self, graph: VersionedGraph, driver: Driver, *, database: str | None = None):
        self._graph = graph
        self._driver = driver
        self._database = database

    def local_state(self, ids: Iterable[str]) -> GraphState:
        return self._graph.local_state(ids)

    def find(self, prop: str, value: Any, *, label: str | None = None) -> set[str]:
        match = "MATCH (n:$($label))" if label is not None else "MATCH (n)"
        records = self._driver.execute_query(
            f"""{match}
                WHERE n.id IS NOT NULL AND none(l IN labels(n) WHERE l IN $reserved)
                  AND CASE WHEN valueType(n[$prop]) STARTS WITH 'LIST' THEN $value IN n[$prop]
                           ELSE n[$prop] = $value END
                RETURN n.id AS id""",
            {"label": label, "prop": prop, "value": value, "reserved": sorted(RESERVED_LABELS)},
            database_=self._database,
            routing_=RoutingControl.READ,
        ).records
        return {r["id"] for r in records}


__all__ = ["MemoryReader", "Neo4jReader", "Reader"]
