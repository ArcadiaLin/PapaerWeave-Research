"""检索用的派生字段：每次提交后补算，不受版本管理（``schema.DERIVED_FIELDS``）。

- 节点的 ``search_text``（全文索引 ``node_texts``）：名称、别名、描述，以及邻居的名称——检索 "PatchTST ETTh1"
  能命中用到二者的 Experiment，即使它的描述里没写这两个名字。邻居不经 ``USED``；产物是标题、摘要与它用到的节点的
  名称（只在产物一侧：节点的文本里不放产物标题，免得热门节点被产物挤满）。
- 节点的 ``embedding``（向量索引 ``node_vectors``）：名称、别名与描述；Content 是描述；产物是标题与摘要。
- 带 ``description`` 的边的 ``search_text``（``edge_texts``）与 ``embedding``（``edge_vectors``）：两端的名称、
  关系类型与描述。没有描述的边不进索引。

**范围。** 提交后只重算受影响的对象：本次触及的节点（新建、修改、增删过边的端点）与它们的一层邻居（邻居的
``related`` 里有它的名称），以及端点在触及节点中的带描述的边（边文本里有端点的名称或描述开头）。只写回变了的文本，
只为向量文本变了的对象补算向量。不给范围时全量重算（建库、修复时用）。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from neo4j import Driver, RoutingControl

from ..model.schema import ARTIFACT, FROM, INDEXED_RELS, SEARCHABLE
from .embedding import embedding_key

Embed = Callable[[list[str]], list[list[float]]]
NEIGHBOR_NAMES = 40  # search_text 中邻居名称的上限：ETTh1 这类节点有上百个邻居，名称只取一部分


def node_texts(driver: Driver, database: str | None, ids: list[str] | None = None) -> list[dict[str, Any]]:
    """可检索节点的检索文本与向量文本；``ids`` 给出时只算这些节点。"""
    rows = _read(
        driver,
        database,
        f"""MATCH (n:{SEARCHABLE}) WHERE $ids IS NULL OR n.id IN $ids
            OPTIONAL MATCH (k:NameKey)-[:NAMES]->(n) WHERE k.raw <> n.name
            WITH n, collect(DISTINCT k.raw) AS alias
            OPTIONAL MATCH (n)-[r]-(m:{SEARCHABLE}) WHERE type(r) <> 'USED' OR (n:{ARTIFACT} AND startNode(r) = n)
            WITH n, alias, collect(DISTINCT coalesce(m.name, m.title))[..{NEIGHBOR_NAMES}] AS near
            OPTIONAL MATCH (n)-[:{FROM}]->(p:Paper)
            RETURN n.id AS id, n.name AS name, n.title AS title, n.abs AS abs, n.description AS description,
                   alias, near, p.name AS paper, n.search_text AS search_text, n.embedding_key AS key""",
        ids=ids,
    )
    out = []
    for r in rows:
        head = [r["name"] or r["title"] or ""]
        if r["alias"]:
            head.append("also: " + ", ".join(sorted(r["alias"])))
        body = r["description"] or r["abs"] or ""
        near = sorted({n for n in r["near"] if n and n != r["name"]})
        search_text = "\n".join(filter(None, [*head, body, "related: " + "; ".join(near) if near else ""]))
        vector_text = "\n".join(filter(None, [*head, body]))
        out.append({**r, "stored": r["search_text"], "search_text": search_text, "vector_text": vector_text})
    return out


def edge_texts(driver: Driver, database: str | None, ids: list[str] | None = None) -> list[dict[str, Any]]:
    """带描述的边的检索文本；``ids`` 给出时只算一端在其中的边。"""
    rows = _read(
        driver,
        database,
        f"""MATCH (a)-[r:{'|'.join(INDEXED_RELS)}]->(b)
            WHERE r.description IS NOT NULL AND ($ids IS NULL OR a.id IN $ids OR b.id IN $ids)
            RETURN elementId(r) AS eid, a.id AS src, type(r) AS type, b.id AS dst,
                   coalesce(a.name, a.title, left(a.description, 80)) AS a_name,
                   coalesce(b.name, b.title, left(b.description, 80)) AS b_name,
                   r.description AS description, r.search_text AS search_text, r.embedding_key AS key""",
        ids=ids,
    )
    for r in rows:
        r["stored"] = r["search_text"]
        r["search_text"] = f"{r['a_name']} {r['type']} {r['b_name']}\n{r['description']}"
        r["vector_text"] = r["search_text"]
    return rows


def sync(driver: Driver, database: str | None, embed: Embed | None, touched: Iterable[str] | None = None) -> int:
    """补算派生字段：``touched`` 给出时只算受影响的对象（见模块说明），否则全部；``embed`` 为 ``None`` 时只算检索
    文本。返回补算了向量的对象与边的个数。"""
    ids = None if touched is None else sorted(set(touched))
    scope = None if ids is None else _with_neighbors(driver, database, ids)
    nodes = node_texts(driver, database, scope)
    edges = edge_texts(driver, database, ids)
    _write(
        driver,
        database,
        "UNWIND $rows AS row MATCH (n {id: row.id}) SET n.search_text = row.text",
        [{"id": n["id"], "text": n["search_text"]} for n in nodes if n["search_text"] != n["stored"]],
    )
    _write(
        driver,
        database,
        "UNWIND $rows AS row MATCH ()-[r]->() WHERE elementId(r) = row.eid SET r.search_text = row.text",
        [{"eid": e["eid"], "text": e["search_text"]} for e in edges if e["search_text"] != e["stored"]],
    )
    if embed is None:
        return 0
    todo_nodes = [n for n in nodes if n["vector_text"] and n["key"] != embedding_key(n["vector_text"])]
    todo_edges = [e for e in edges if e["key"] != embedding_key(e["vector_text"])]
    vectors = embed([t["vector_text"] for t in todo_nodes + todo_edges]) if todo_nodes or todo_edges else []
    node_rows = [
        {"id": n["id"], "v": v, "key": embedding_key(n["vector_text"])} for n, v in zip(todo_nodes, vectors, strict=False)
    ]
    edge_rows = [
        {"eid": e["eid"], "v": v, "key": embedding_key(e["vector_text"])}
        for e, v in zip(todo_edges, vectors[len(todo_nodes) :], strict=False)
    ]
    _write(
        driver,
        database,
        """UNWIND $rows AS row MATCH (n {id: row.id})
           CALL db.create.setNodeVectorProperty(n, 'embedding', row.v) SET n.embedding_key = row.key""",
        node_rows,
    )
    _write(
        driver,
        database,
        """UNWIND $rows AS row MATCH ()-[r]->() WHERE elementId(r) = row.eid
           CALL db.create.setRelationshipVectorProperty(r, 'embedding', row.v) SET r.embedding_key = row.key""",
        edge_rows,
    )
    return len(node_rows) + len(edge_rows)


def _with_neighbors(driver: Driver, database: str | None, ids: list[str]) -> list[str]:
    """``ids`` 与它们的一层可检索邻居，口径与 ``related`` 相同：不经 ``USED``，但用到它们的产物算在内。"""
    rows = _read(
        driver,
        database,
        f"""UNWIND $ids AS id MATCH (n:{SEARCHABLE} {{id: id}})-[r]-(m:{SEARCHABLE})
            WHERE type(r) <> 'USED' OR (m:{ARTIFACT} AND startNode(r) = m)
            RETURN DISTINCT m.id AS id""",
        ids=ids,
    )
    return sorted({*ids, *(r["id"] for r in rows)})


def _read(driver: Driver, database: str | None, cypher: str, **params: Any) -> list[dict[str, Any]]:
    records = driver.execute_query(cypher, params, database_=database, routing_=RoutingControl.READ).records
    return [r.data() for r in records]


def _write(driver: Driver, database: str | None, cypher: str, rows: list[dict[str, Any]]) -> None:
    for i in range(0, len(rows), 200):
        driver.execute_query(cypher, {"rows": rows[i : i + 200]}, database_=database)


__all__ = ["edge_texts", "node_texts", "sync"]
