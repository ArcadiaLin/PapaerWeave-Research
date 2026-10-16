"""检索：一个查询覆盖全部证据节点、产物与带说明的关系（docs/designs/v3/tools.md）。

    find(store, query, kinds=(), papers=(), topn=10) -> Found

1. **精确命中**排在最前，不计分：id 本身、外部标识（``arxiv:2211.14730``，也接受不带命名空间的 arXiv 号与版本后缀）、
   名称与别名（规范化后不分大小写）。取代 V2 的 Resolve。
2. 其余按 **RRF** 融合四路召回：节点全文（``search_text``：名称、别名、描述、邻居名称）、节点向量、关系全文
   （两端名称、类型与说明）、关系向量。只用名次，不比较量纲不同的分数，不设向量阈值。
3. 关系命中按起点合并：同一起点的几条命中关系与起点本身的命中合成一条结果，名次取最好的一个。
4. ``kinds`` 可以是节点 kind、类别、产物类型或关系类型，决定开哪几路；``papers`` 只留这些论文中的 Content、论文本身，
   以及从它们出发的关系。没有指定产物类型时，结果中最多 :data:`MAX_ARTIFACTS` 条产物，其余计入 ``more_artifacts``。

各结果的依据（精确命中方式、各路名次）写入日志 ``paperweave.search``；某一路失败时在 ``failed`` 中说明，其余照常。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from graph_vc import EdgeKey

from ..model.namekey import normalize
from ..model.schema import (
    ARTIFACT,
    ARTIFACT_TYPES,
    CONTENT,
    EDGE_TEXT_INDEX,
    EDGE_VECTOR_INDEX,
    FAMILIES,
    FROM,
    KIND_SPECS,
    NODE_TEXT_INDEX,
    NODE_VECTOR_INDEX,
    RELATIONSHIPS,
    SEARCHABLE,
)
from ..store.store import ContractError, Store, brief

POOL = 30  # 每一路召回的条数
RRF_K = 20
VECTOR_OVERFETCH = 4  # 向量索引先取后滤：多取几倍
MAX_TOPN = 50
DEFAULT_TOPN = 10
MAX_ARTIFACTS = 3
INSTRUCT = (
    "Instruct: Given a search query, retrieve methods, datasets, papers, experiments, claims, relations between them, "
    "or work products from a research knowledge store that match it\nQuery: "
)
_ID = re.compile(r"[a-z]+_[0-9a-f]{4,}")
_ARXIV = re.compile(r"(?:arxiv:)?(\d{4}\.\d{4,5})(?:v\d+)?", re.I)

log = logging.getLogger("paperweave.search")

Item = tuple[str, ...]  # ("n", id) 或 ("e", src, type, dst)


@dataclass(frozen=True, slots=True)
class Filter:
    node_kinds: frozenset[str] | None  # None：不限；空集：不找节点
    artifact_types: frozenset[str] | None
    rel_types: frozenset[str] | None
    papers: frozenset[str]

    @property
    def nodes(self) -> bool:
        return self.node_kinds is None or bool(self.node_kinds) or self.artifact_types is None or bool(self.artifact_types)

    @property
    def edges(self) -> bool:
        return self.rel_types is None or bool(self.rel_types)


@dataclass
class Entry:
    """一条结果：起点 ``id``；``match`` 是精确命中的方式（或 ``None``）；``edges`` 是命中的出边。"""

    id: str
    match: str | None = None
    edges: list[EdgeKey] = field(default_factory=list)
    node_hit: bool = False


@dataclass
class Found:
    entries: list[Entry]
    more_artifacts: int = 0
    failed: dict[str, str] = field(default_factory=dict)


def parse_kinds(kinds: Sequence[str]) -> Filter:
    """``kinds`` → 过滤条件；认不出的值是契约错误。"""
    if not kinds:
        return Filter(None, None, None, frozenset())
    node, artifact, rel, unknown = set(), set(), set(), []
    for k in kinds:
        if k in KIND_SPECS:
            node.add(k)
        elif k in FAMILIES:
            node.update(s for s, spec in KIND_SPECS.items() if spec.family == k)
        elif k in ARTIFACT_TYPES:
            artifact.add(k)
        elif k == ARTIFACT:
            artifact.update(ARTIFACT_TYPES)
        elif k in RELATIONSHIPS:
            rel.add(k)
        else:
            unknown.append(k)
    if unknown:
        allowed = [*KIND_SPECS, *ARTIFACT_TYPES, *RELATIONSHIPS]
        raise ContractError([{"at": "kind", "msg": f"unknown kind {', '.join(unknown)}; one of {', '.join(allowed)}"}])
    return Filter(frozenset(node), frozenset(artifact), frozenset(rel), frozenset())


def find(
    store: Store, query: str, kinds: Sequence[str] = (), papers: Sequence[str] = (), topn: int = DEFAULT_TOPN
) -> Found:
    if not isinstance(query, str) or not query.strip():
        raise ContractError([{"at": "query", "msg": "a name, an identity or a description to search for"}])
    if not isinstance(topn, int) or not 1 <= topn <= MAX_TOPN:
        raise ContractError([{"at": "topn", "msg": f"1-{MAX_TOPN}"}])
    flt = parse_kinds(kinds)
    flt = Filter(flt.node_kinds, flt.artifact_types, flt.rel_types, frozenset(papers))
    query = query.strip()
    failed: dict[str, str] = {}

    exact = _exact(store, query, flt) if flt.nodes else []
    channels: dict[str, list[Item]] = {}
    terms = _lucene(query)
    vector: list[float] | None = None
    if store.embed is not None:
        try:
            vector = store.embed([INSTRUCT + query])[0]
        except Exception as exc:  # noqa: BLE001 —— 向量服务不可用时只关掉向量两路
            failed["vector"] = f"query embedding failed: {brief(exc)}"
    else:
        failed["vector"] = "vectors are off in this session"
    if flt.nodes:
        if terms:
            channels["node_text"] = _run(failed, "node_text", lambda: _node_text(store, terms, flt))
        if vector is not None:
            channels["node_vector"] = _run(failed, "node_vector", lambda: _node_vector(store, vector, flt))
    if flt.edges:
        if terms:
            channels["edge_text"] = _run(failed, "edge_text", lambda: _edge_text(store, terms, flt))
        if vector is not None:
            channels["edge_vector"] = _run(failed, "edge_vector", lambda: _edge_vector(store, vector, flt))

    ranked = _fuse(channels)
    entries: dict[str, Entry] = {}
    for node_id, how in exact:
        entries.setdefault(node_id, Entry(node_id, match=how, node_hit=True))
    for item in ranked:
        if item[0] == "n":
            entry = entries.setdefault(item[1], Entry(item[1]))
            entry.node_hit = True
        else:
            key = EdgeKey(item[1], item[2], item[3])
            entry = entries.setdefault(key.src, Entry(key.src))
            if key not in entry.edges:
                entry.edges.append(key)
    log.info("search %r kinds=%s papers=%s exact=%s channels=%s", query, list(kinds), list(papers), exact,
             {ch: [_show(i) for i in items[:10]] for ch, items in channels.items()})

    kinds_of = store.kinds(entries)
    out, more = [], 0
    for entry in entries.values():
        if len(out) >= topn:
            if kinds_of.get(entry.id) == ARTIFACT:
                more += 1
            continue
        if kinds_of.get(entry.id) == ARTIFACT and not flt.artifact_types and sum(
            kinds_of.get(e.id) == ARTIFACT for e in out
        ) >= MAX_ARTIFACTS:
            more += 1
            continue
        out.append(entry)
    return Found(out, more, failed)


# ── 精确命中 ──────────────────────────────────────────────────────────


def _exact(store: Store, query: str, flt: Filter) -> list[tuple[str, str]]:
    hits: list[tuple[str, str]] = []
    if _ID.fullmatch(query):
        hits += [(r["id"], "id") for r in store.query(
            f"MATCH (n:{SEARCHABLE} {{id: $q}}) RETURN n.id AS id", q=query)]
    wanted = [query.lower()]
    arxiv = _ARXIV.fullmatch(query)
    if arxiv:
        wanted.append(f"arxiv:{arxiv[1]}")
    hits += [(r["id"], "identity") for r in store.query(
        """MATCH (n:Entity) WHERE any(i IN n.identities WHERE toLower(i) IN $wanted OR toLower(i) ENDS WITH ':' + $q)
           RETURN n.id AS id ORDER BY id""",
        wanted=wanted, q=query.lower())]
    rows = store.query(
        """MATCH (k:NameKey)-[:NAMES]->(n) WHERE toLower(k.normalized) = $q
           RETURN n.id AS id, k.raw = n.name AS is_name ORDER BY is_name DESC, id""",
        q=normalize(query).lower(),
    )
    hits += [(r["id"], "name" if r["is_name"] else "alias") for r in rows]
    seen: dict[str, str] = {}
    for node_id, how in hits:
        seen.setdefault(node_id, how)
    kinds = store.kinds(seen)
    return [(i, how) for i, how in seen.items() if _node_allowed(store, i, kinds.get(i), flt)]


def _node_allowed(store: Store, node_id: str, kind: str | None, flt: Filter) -> bool:
    if kind == ARTIFACT:
        return flt.artifact_types is None or bool(flt.artifact_types)
    if flt.node_kinds is not None and kind not in flt.node_kinds:
        return False
    if flt.papers:
        if kind == "Paper":
            return node_id in flt.papers
        if kind not in CONTENT:
            return False
        rows = store.query(f"MATCH ({{id: $id}})-[:{FROM}]->(p) RETURN p.id AS p", id=node_id)
        return any(r["p"] in flt.papers for r in rows)
    return True


# ── 四路召回 ──────────────────────────────────────────────────────────


def _node_where(flt: Filter, var: str = "node") -> tuple[str, dict[str, Any]]:
    """节点一路的过滤条件：kind、产物类型与论文。"""
    clauses, params = [], {}
    kinds = list(flt.node_kinds) if flt.node_kinds is not None else list(KIND_SPECS)
    arts = list(flt.artifact_types) if flt.artifact_types is not None else list(ARTIFACT_TYPES)
    clauses.append(
        f"(any(l IN labels({var}) WHERE l IN $kinds) OR ({var}:{ARTIFACT} AND {var}.op IN $arts))"
    )
    params |= {"kinds": kinds, "arts": arts}
    if flt.papers:
        clauses.append(
            f"(({var}:Paper AND {var}.id IN $papers) OR EXISTS {{ MATCH ({var})-[:{FROM}]->(p) WHERE p.id IN $papers }})"
        )
        params["papers"] = sorted(flt.papers)
    return " AND ".join(clauses), params


def _edge_where(flt: Filter) -> tuple[str, dict[str, Any]]:
    clauses = ["type(relationship) IN $rels"]
    params: dict[str, Any] = {"rels": sorted(flt.rel_types) if flt.rel_types else list(RELATIONSHIPS)}
    if flt.papers:
        clauses.append(
            "((a:Paper AND a.id IN $papers) OR EXISTS { MATCH (a)-[:FROM]->(p) WHERE p.id IN $papers })"
        )
        params["papers"] = sorted(flt.papers)
    return " AND ".join(clauses), params


def _node_text(store: Store, terms: str, flt: Filter) -> list[Item]:
    where, params = _node_where(flt)
    rows = store.query(
        f"""CALL db.index.fulltext.queryNodes('{NODE_TEXT_INDEX}', $terms, {{limit: $limit}}) YIELD node, score
            WHERE {where} RETURN node.id AS id LIMIT $pool""",
        terms=terms, limit=POOL * VECTOR_OVERFETCH, pool=POOL, **params,
    )
    return [("n", r["id"]) for r in rows]


def _node_vector(store: Store, vector: list[float], flt: Filter) -> list[Item]:
    where, params = _node_where(flt)
    rows = store.query(
        f"""CALL db.index.vector.queryNodes('{NODE_VECTOR_INDEX}', $k, $v) YIELD node, score
            WHERE {where} RETURN node.id AS id LIMIT $pool""",
        k=POOL * VECTOR_OVERFETCH, v=vector, pool=POOL, **params,
    )
    return [("n", r["id"]) for r in rows]


def _edge_text(store: Store, terms: str, flt: Filter) -> list[Item]:
    where, params = _edge_where(flt)
    rows = store.query(
        f"""CALL db.index.fulltext.queryRelationships('{EDGE_TEXT_INDEX}', $terms, {{limit: $limit}})
            YIELD relationship, score
            WITH relationship, startNode(relationship) AS a, endNode(relationship) AS b WHERE {where}
            RETURN a.id AS src, type(relationship) AS type, b.id AS dst LIMIT $pool""",
        terms=terms, limit=POOL * VECTOR_OVERFETCH, pool=POOL, **params,
    )
    return [("e", r["src"], r["type"], r["dst"]) for r in rows]


def _edge_vector(store: Store, vector: list[float], flt: Filter) -> list[Item]:
    where, params = _edge_where(flt)
    rows = store.query(
        f"""CALL db.index.vector.queryRelationships('{EDGE_VECTOR_INDEX}', $k, $v) YIELD relationship, score
            WITH relationship, startNode(relationship) AS a, endNode(relationship) AS b WHERE {where}
            RETURN a.id AS src, type(relationship) AS type, b.id AS dst LIMIT $pool""",
        k=POOL * VECTOR_OVERFETCH, v=vector, pool=POOL, **params,
    )
    return [("e", r["src"], r["type"], r["dst"]) for r in rows]


def _run(failed: dict[str, str], name: str, fn: Any) -> list[Item]:
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 —— 一路失败不影响其余各路
        failed[name] = brief(exc)
        return []


def _fuse(channels: dict[str, list[Item]]) -> list[Item]:
    score: dict[Item, float] = {}
    for items in channels.values():
        for rank, item in enumerate(items, 1):
            score[item] = score.get(item, 0.0) + 1 / (RRF_K + rank)
    return sorted(score, key=lambda i: (-score[i], i))


def _lucene(query: str) -> str:
    """查询词：字母与数字串，用 OR 连接（Lucene 默认）。不含 Lucene 的特殊字符。"""
    words = re.findall(r"[A-Za-z0-9]+", query)
    return " ".join(dict.fromkeys(w.lower() for w in words))


def _show(item: Item) -> str:
    return item[1] if item[0] == "n" else f"{item[1]}-{item[2]}->{item[3]}"


def ids_of(found: Found) -> list[str]:
    """投影要读取的节点：各条结果的起点与命中关系的终点。"""
    out: list[str] = []
    for entry in found.entries:
        out.append(entry.id)
        out += [k.dst for k in entry.edges]
    return list(dict.fromkeys(out))


__all__ = ["DEFAULT_TOPN", "Entry", "Filter", "Found", "find", "ids_of", "parse_kinds"]
