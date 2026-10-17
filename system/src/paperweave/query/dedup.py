"""写入时的查重（:class:`paperweave.commit.Deduper` 的实现）：为新建的 Entity / Concept 找同 kind 的已有节点。

- 精确：外部标识（含 ``url``）、名称与别名（规范化后不分大小写）。全部列出。
- 近似：名称与描述的全文、向量两路，RRF 融合后取前 :data:`NEAR` 个，只留向量分数（Neo4j 的 ``(1 + cos) / 2``）
  不低于 :data:`VECTOR_MIN` 的。阈值来自实验室库上的侦察（2026-10-16，20 个新节点：5 个造的真重复最高近邻 0.851–0.911，
  其余不是重复的近邻多在 0.76–0.84），暂定。给出的每个候选都要有一次明确的判断（是同一个就改用它的 id，
  不是就列进 ``distinct_from``）。
- 两边都有唯一命名空间（``arxiv``、``doi``、``s2``）的外部标识而互不相同时，是两个对象，不列为近似候选。
- 桩只有名称，只开精确与名称全文两路，全文近邻不设阈值；没有向量服务时同样只按全文取前几个。
- 已有的桩作为候选时也不设阈值：它的向量只来自名称，与带描述的新节点比分数偏低，换了写法（ECL 与 Electricity）
  就会被阈值滤掉。桩少，多列几个候选的负担不大。

只给候选，不判断是不是同一对象。
"""

from __future__ import annotations

from ..commit.review import Candidate, Lookup
from ..model.namekey import normalize
from ..model.schema import NAMESPACES, NODE_TEXT_INDEX, NODE_VECTOR_INDEX
from ..store.store import Store, brief
from .search import INSTRUCT, RRF_K, _lucene

NEAR = 3
POOL = 10
VECTOR_MIN = 0.84


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
        close: set[str] | None = None  # 向量分数过阈值的近邻；None 表示没有向量这一路
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
                    f"""CALL db.index.vector.queryNodes('{NODE_VECTOR_INDEX}', 100, $v) YIELD node, score
                        WHERE node:{kind} RETURN node.id AS id, score LIMIT $pool""",
                    v=vector, pool=POOL,
                )
                close = {r["id"] for r in rows if r["score"] >= VECTOR_MIN}
                for rank, r in enumerate(rows, 1):
                    near[r["id"]] = near.get(r["id"], 0) + 1 / (RRF_K + rank)
                    found.setdefault(r["id"], set())
            except Exception as exc:  # noqa: BLE001
                errors.append(f"vector: {brief(exc)}")
        exact = [i for i, ch in found.items() if ch]
        ranked = sorted(near, key=lambda i: -near[i])
        if close is not None:
            close |= self._stubs(ranked)
        fuzzy = [i for i in ranked if i not in exact and (close is None or i in close)]
        fuzzy = [i for i in fuzzy if i not in self._identified_apart(fuzzy, identities)][:NEAR]
        for i in fuzzy:
            found[i].add("similar")
        ids = exact + fuzzy
        return Lookup(tuple(Candidate(i, tuple(sorted(found[i]))) for i in ids), tuple(errors))

    def _stubs(self, ids: list[str]) -> set[str]:
        if not ids:
            return set()
        rows = self.store.query("MATCH (n) WHERE n.id IN $ids AND n.stub = true RETURN n.id AS id", ids=ids)
        return {r["id"] for r in rows}

    def _identified_apart(self, ids: list[str], identities: list[str]) -> set[str]:
        """``ids`` 中与新节点各有唯一标识、且没有一个相同的节点。"""
        mine = {i for i in identities if NAMESPACES.get(i.partition(":")[0])}
        if not mine or not ids:
            return set()
        rows = self.store.query("MATCH (n) WHERE n.id IN $ids RETURN n.id AS id, n.identities AS identities", ids=ids)
        apart = set()
        for r in rows:
            theirs = {i for i in r["identities"] or [] if NAMESPACES.get(i.partition(":")[0])}
            if theirs and not theirs & mine:
                apart.add(r["id"])
        return apart


__all__ = ["SearchDeduper"]
