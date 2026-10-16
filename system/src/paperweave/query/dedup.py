"""写入时的查重（:class:`paperweave.commit.Deduper` 的实现）：为新建的 Entity / Concept 找同 kind 的已有节点。

- 精确：外部标识（含 ``url``）、名称与别名（规范化后不分大小写）。全部列出。
- 近似：名称与描述的全文、向量两路，RRF 融合后取前 :data:`NEAR` 个。没有阈值：库中有同 kind 的节点就会给出近邻，
  所以每个新节点都要有一次明确的判断（是同一个就改用它的 id，不是就列进 ``distinct_from``）。
- 桩只有名称，只开精确与名称全文两路。

只给候选，不判断是不是同一对象。
"""

from __future__ import annotations

from ..commit.review import Candidate, Lookup
from ..model.namekey import normalize
from ..model.schema import NODE_TEXT_INDEX, NODE_VECTOR_INDEX
from ..store.store import Store, brief
from .search import INSTRUCT, RRF_K, _lucene

NEAR = 3
POOL = 10


class SearchDeduper:
    def __init__(self, store: Store):
        self.store = store

    def lookup(
        self, kind: str, *, name: str | None, identities: list[str], description: str | None, stub: bool
    ) -> Lookup:
        found: dict[str, set[str]] = {}
        errors: list[str] = []
        if identities:
            for r in self.store.query(
                f"MATCH (n:{kind}) WHERE any(i IN n.identities WHERE i IN $ids) RETURN n.id AS id", ids=identities
            ):
                found.setdefault(r["id"], set()).add("identity")
        if name:
            for r in self.store.query(
                f"MATCH (k:NameKey)-[:NAMES]->(n:{kind}) WHERE toLower(k.normalized) = $q RETURN DISTINCT n.id AS id",
                q=normalize(name).lower(),
            ):
                found.setdefault(r["id"], set()).add("name")
        near: dict[str, float] = {}
        text = " ".join(filter(None, [name, None if stub else description]))
        terms = _lucene(text)
        if terms:
            try:
                rows = self.store.query(
                    f"""CALL db.index.fulltext.queryNodes('{NODE_TEXT_INDEX}', $terms, {{limit: 100}})
                        YIELD node WHERE node:{kind} RETURN node.id AS id LIMIT $pool""",
                    terms=terms, pool=POOL,
                )
                for rank, r in enumerate(rows, 1):
                    near[r["id"]] = near.get(r["id"], 0) + 1 / (RRF_K + rank)
                    found.setdefault(r["id"], set())
            except Exception as exc:  # noqa: BLE001
                errors.append(f"text: {brief(exc)}")
        if text and not stub and self.store.embed is not None:
            try:
                vector = self.store.embed([INSTRUCT + text])[0]
                rows = self.store.query(
                    f"""CALL db.index.vector.queryNodes('{NODE_VECTOR_INDEX}', 100, $v) YIELD node
                        WHERE node:{kind} RETURN node.id AS id LIMIT $pool""",
                    v=vector, pool=POOL,
                )
                for rank, r in enumerate(rows, 1):
                    near[r["id"]] = near.get(r["id"], 0) + 1 / (RRF_K + rank)
                    found.setdefault(r["id"], set())
            except Exception as exc:  # noqa: BLE001
                errors.append(f"vector: {brief(exc)}")
        exact = [i for i, ch in found.items() if ch]
        fuzzy = [i for i in sorted(near, key=lambda i: -near[i]) if i not in exact][:NEAR]
        for i in fuzzy:
            found[i].add("similar")
        ids = exact + fuzzy
        return Lookup(tuple(Candidate(i, tuple(sorted(found[i]))) for i in ids), tuple(errors))


__all__ = ["SearchDeduper"]
