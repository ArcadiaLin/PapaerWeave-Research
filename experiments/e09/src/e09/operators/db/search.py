"""Search：在一个类别内按查询与结构条件发现对象（docs/designs/v2/operators.md §3.1）。

    search(type, query?, kinds?, where={}, expand={}, scope="global", budget=10, continuation?) -> 结果视图

- 不给 ``query`` 时按结构条件枚举，按 id 排序。
- 给 ``query`` 时，精确命中（Entity 的标识，名称的 NameKey 精确键）排在前面，不计分；其余通道
  （名称词面、文本全文、向量）按 RRF 融合，不设阈值。各通道的召回都在 ``kinds``、``where`` 与 ``scope`` 之内；
  向量索引先超取再过滤，可能漏掉条件内的可行候选，超取数记入 ``coverage``。
- 返回结果视图（:mod:`e09.query.excerpts`）：每个结果只有识别字段与检索字段的开头摘录，不带关系，整份结果按
  容量上限截取。完整对象与关系用 Traverse 读取。各结果的取得依据（精确命中方式、各通道名次与融合分）与覆盖
  信息（通道状态、候选池、向量超取）写入日志 ``e09.search``；通道失败另在 ``meta.failed`` 中给出。

``type`` 为 Entity、Concept、Content 时结果中不出现 Artifact；要找已有的工作产物，显式写 ``type=Artifact``。
Artifact 没有 kind，按 ``where.op`` 筛选；查询只有 ``text``，在 ``title`` 与 ``abs`` 上检索。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ...artifact.stale import readonly
from ...query.revisions import latest_revisions
from ...model.namekey import name_key
from ...model.schema import ARTIFACT, KINDS, NAMED, NAMESPACES
from ...query.conditions import Compiled, compile_where
from ...query.excerpts import results
from ...query.fusion import POOL, RRF_K, fuse, tokens
from ...store.embedding import EMBED_MODEL, VECTOR_INDEXES
from ...store.store import ContractError, Store
from ..base import STRINGS, TERMS, db_operator, schema

TYPES = ("Entity", "Concept", "Content", ARTIFACT)
QUERY_FIELDS = {
    "Entity": ("identifier", "mention", "text"),
    "Concept": ("mention", "text"),
    "Content": ("text",),
    ARTIFACT: ("text",),
}
TEXT_INDEX = {
    "Entity": "entity_texts",
    "Concept": "concept_texts",
    "Content": "content_texts",
    ARTIFACT: "artifact_texts",
}
VECTOR_INDEX = {label: name for name, label in VECTOR_INDEXES.items()}
INSTRUCT = {  # 查询侧的任务说明（Qwen3-Embedding 的 Instruct 格式）
    "Entity": "Instruct: Given a search query, retrieve papers, datasets, benchmarks, models, code or tools "
    "described by it\nQuery: ",
    "Concept": "Instruct: Given a search query, retrieve research methods, tasks or issues described by it\nQuery: ",
    "Content": "Instruct: Given a search query, retrieve claims, experiments, contributions or observations "
    "from research papers that match it\nQuery: ",
    ARTIFACT: "Instruct: Given a search query, retrieve earlier work products (extracted records, summaries, checks, "
    "verifications, filters, answers) whose title or abstract matches it\nQuery: ",
}
OVERFETCH = 5
DEFAULT_BUDGET = 10
MAX_BUDGET = 100

log = logging.getLogger("e09.search")


@dataclass(frozen=True)
class Found:
    """一次检索的全部排名与依据：``ranked`` 是全部匹配的 id，本页为 ``ranked[offset : offset + budget]``。"""

    request: dict[str, Any]
    ranked: list[str]
    offset: int
    budget: int
    bindings: dict[str, Any]
    coverage: dict[str, Any]
    missing: list[dict[str, str]]
    diagnostics: dict[str, Any]
    expanded: dict[str, Any]

    @property
    def page(self) -> list[str]:
        return self.ranked[self.offset : self.offset + self.budget]


def search(
    store: Store,
    type: str,  # 与契约中的参数名一致
    query: str | Mapping[str, str] | None = None,
    kinds: list[str] | str | None = None,
    where: Mapping[str, Any] | None = None,
    expand: Mapping[str, Any] | None = None,
    scope: str | list[str] = "global",
    budget: int = DEFAULT_BUDGET,
    continuation: int | None = None,
) -> dict[str, Any]:
    before = store.snapshot()
    found = find(store, type, query, kinds, where, expand, scope, budget, continuation)
    page = found.page
    state = store.graph.local_state(page)
    artifacts = readonly(store, page) if type == ARTIFACT else {}
    if type == "Content":
        artifacts = {k: {"_revised": v} for k, v in latest_revisions(store, page).items()}
    snapshot, changed = store.stable(before)
    failed = {k: v for k, v in found.coverage.get("channels", {}).items() if v.startswith("error")}
    diagnostics = found.diagnostics | changed
    extra = {"missing": found.missing, "diagnostics": diagnostics, "expanded": found.expanded, "failed": failed}
    extra = {k: v for k, v in extra.items() if v}
    view = results(type, state, page, found.offset, len(found.ranked), extra | {"snapshot": snapshot}, artifacts)
    trace = {"query": found.request, "coverage": found.coverage, "bindings": found.bindings}
    log.info("Search %s", json.dumps(trace, ensure_ascii=False, default=str))
    return view


def find(
    store: Store,
    type: str,  # 与契约中的参数名一致
    query: str | Mapping[str, str] | None = None,
    kinds: list[str] | str | None = None,
    where: Mapping[str, Any] | None = None,
    expand: Mapping[str, Any] | None = None,
    scope: str | list[str] = "global",
    budget: int = DEFAULT_BUDGET,
    continuation: int | None = None,
) -> Found:
    """校验参数并排名；``search`` 在它之上取本页并生成结果视图。"""
    request = _request(type, query, kinds, where, expand, scope, budget, continuation)
    problems: list[dict[str, str]] = []
    if type not in TYPES:
        raise ContractError([{"at": "type", "msg": f"one of {list(TYPES)}"}])
    subjects = _kinds(type, kinds, problems)
    terms = _query(type, query, problems)
    papers = _scope(type, scope, problems)
    offset = _paging(budget, continuation, problems)
    if problems:
        raise ContractError(problems)

    compiled = compile_where(store, where, subjects, expand=expand)
    missing = list(compiled.missing)
    base = f"x:{type} AND any(l IN labels(x) WHERE l IN $kinds) AND {compiled.predicate}"
    params: dict[str, Any] = {"kinds": sorted(subjects), **compiled.params}
    if papers is not None:
        found = store.kinds(papers)
        wrong = [p for p in papers if p in found and found[p] != "Paper"]
        if wrong:
            raise ContractError([{"at": "scope", "msg": f"not papers: {wrong}"}])
        missing += [{"ref": p, "param": "scope", "missing_in": "store"} for p in papers if p not in found]
        base += " AND EXISTS { MATCH (x)-[:FROM]->(p:Paper) WHERE p.id IN $scope }"
        params["scope"] = papers

    coverage: dict[str, Any] = {"type": type, "kinds": sorted(subjects), "scope": scope, "budget": budget}
    bindings: dict[str, Any] = {}
    if missing:  # 引用不在库中：数据缺失，返回空结果
        ranked: list[str] = []
        coverage["order"] = "none (missing references)"
    elif not terms:
        ranked = [r["id"] for r in store.query(f"MATCH (x) WHERE {base} RETURN x.id AS id ORDER BY id", **params)]
        coverage["order"] = "id"
    else:
        ranked, bindings, channels = _ranked(store, type, subjects, terms, base, params)
        coverage.update(order="exact, then rrf", channels=channels, pool=POOL, rrf_k=RRF_K)
        if "semantic" in channels:
            coverage["vector"] = {"model": EMBED_MODEL, "overfetch": POOL * OVERFETCH, "filter": "after index"}

    page = ranked[offset : offset + budget]
    more = offset + budget < len(ranked)
    coverage.update(matched=len(ranked), returned=len(page), truncated=more, snapshot=store.snapshot())
    return Found(
        request=request,
        ranked=ranked,
        offset=offset,
        budget=budget,
        bindings={i: bindings[i] for i in page if i in bindings},
        coverage=coverage,
        missing=missing,
        diagnostics=_diagnostics(store, compiled, set(ranked)),
        expanded=dict(compiled.expanded or {}),
    )


# ── 参数 ──────────────────────────────────────────────────────────────


def _request(type_: str, query: Any, kinds: Any, where: Any, expand: Any, scope: Any, budget: int, cont: Any) -> dict:
    request = {"op": "Search", "type": type_, "query": query, "kinds": kinds, "where": where, "expand": expand}
    request.update(scope=scope, budget=budget, continuation=cont)
    return {k: v for k, v in request.items() if v not in (None, {}, [])}


def _kinds(type_: str, kinds: Any, problems: list[dict[str, str]]) -> frozenset[str]:
    if type_ == ARTIFACT:
        if kinds is not None:
            problems.append({"at": "kinds", "msg": "Artifact has no kinds; filter by where.op"})
        return frozenset({ARTIFACT})
    allowed = frozenset(KINDS.get(type_, ()))
    if kinds is None:
        return allowed
    kinds = [kinds] if isinstance(kinds, str) else kinds
    if not isinstance(kinds, list) or not kinds or not set(kinds) <= allowed:
        problems.append({"at": "kinds", "msg": f"a non-empty list from {sorted(allowed)}"})
        return allowed
    return frozenset(kinds)


def _query(type_: str, query: Any, problems: list[dict[str, str]]) -> dict[str, str]:
    if query is None:
        return {}
    terms = {"text": query} if isinstance(query, str) else query
    if not isinstance(terms, Mapping):
        problems.append({"at": "query", "msg": "a string or {identifier?, mention?, text?}"})
        return {}
    for key, value in terms.items():
        if key not in QUERY_FIELDS[type_]:
            problems.append({"at": f"query.{key}", "msg": f"{type_} accepts {list(QUERY_FIELDS[type_])}"})
        elif not isinstance(value, str) or not value.strip():
            problems.append({"at": f"query.{key}", "msg": "a non-empty string"})
    identifier = terms.get("identifier")
    if isinstance(identifier, str) and identifier.partition(":")[0] not in NAMESPACES:
        problems.append({"at": "query.identifier", "msg": f"namespace is one of {sorted(NAMESPACES)}"})
    return dict(terms)


def _scope(type_: str, scope: Any, problems: list[dict[str, str]]) -> list[str] | None:
    if scope == "global":
        return None
    if type_ != "Content":
        problems.append({"at": "scope", "msg": "a paper list only applies to Content"})
    elif not isinstance(scope, list) or not scope or not all(isinstance(p, str) for p in scope):
        problems.append({"at": "scope", "msg": '"global" or a list of paper ids'})
    else:
        return scope
    return None


def _paging(budget: Any, continuation: Any, problems: list[dict[str, str]]) -> int:
    if not isinstance(budget, int) or isinstance(budget, bool) or not 1 <= budget <= MAX_BUDGET:
        problems.append({"at": "budget", "msg": f"an integer from 1 to {MAX_BUDGET}"})
    if continuation is None:
        return 0
    if not isinstance(continuation, int) or isinstance(continuation, bool) or continuation < 0:
        problems.append({"at": "continuation", "msg": "the continuation returned by the previous call"})
        return 0
    return continuation


# ── 召回与排序 ────────────────────────────────────────────────────────


def _ranked(
    store: Store, type_: str, subjects: frozenset[str], terms: dict[str, str], base: str, params: dict[str, Any]
) -> tuple[list[str], dict[str, Any], dict[str, str]]:
    status: dict[str, str] = {}
    exact: dict[str, str] = {}  # id → 精确命中的通道，先到先得
    identifier, mention, text = terms.get("identifier"), terms.get("mention"), terms.get("text")
    if identifier:
        rows = store.query(
            f"MATCH (x) WHERE $identifier IN x.identifiers AND {base} RETURN x.id AS id ORDER BY id",
            identifier=identifier,
            **params,
        )
        exact.update((r["id"], "identifier") for r in rows if r["id"] not in exact)
        status["identifier"] = f"ok ({len(rows)})"
    named = sorted(subjects & NAMED)
    if mention and named:
        rows = store.query(
            f"""MATCH (k:NameKey)-[:NAMES]->(x) WHERE k.key IN $keys AND {base}
                RETURN DISTINCT x.id AS id ORDER BY id""",
            keys=[name_key(mention, kind) for kind in named],
            **params,
        )
        for r in rows:
            exact.setdefault(r["id"], "name")
        status["name"] = f"ok ({len(rows)})"

    plan = {
        "lexical_name": (lambda: _lexical_name(store, mention, base, params)) if mention and named else None,
        "lexical_text": (lambda: _lexical_text(store, type_, text, base, params)) if text else None,
        "semantic": (lambda: _semantic(store, type_, text or mention, base, params))
        if store.embed and (text or mention)
        else None,  # 只给标识符时没有可嵌入的文本
    }
    channels: dict[str, list[dict[str, Any]]] = {}
    for name, run in plan.items():
        if run is None:
            status[name] = "disabled"
            continue
        try:
            channels[name] = run()
            status[name] = f"ok ({len(channels[name])})"
        except Exception as exc:  # 服务不可用、索引缺失等：记入通道状态，不当作空结果
            status[name] = f"error: {type(exc).__name__}: {exc}"

    bindings: dict[str, Any] = {i: {"exact": how} for i, how in exact.items()}
    ranked = list(exact)
    for row in fuse(channels):
        if row["id"] not in exact:
            ranked.append(row["id"])
            bindings[row["id"]] = {"rrf": row["rrf"], **{ch: e["rank"] for ch, e in row["evidence"].items()}}
    return ranked, bindings, status


def _lexical_name(store: Store, mention: str, base: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    """名称词面：NameKey.raw 的全文索引，每个词取原词、前缀与模糊三种写法；同一对象多个键取最高分。"""
    words = " ".join(f"{t} {t}* {t}~" for t in tokens(mention))
    if not words:
        return []
    return store.query(
        f"""CALL db.index.fulltext.queryNodes('namekey_raw', $words) YIELD node, score
            MATCH (node)-[:NAMES]->(x) WHERE {base}
            RETURN x.id AS id, max(score) AS score ORDER BY score DESC, id LIMIT $pool""",
        words=words,
        pool=POOL,
        **params,
    )


def _lexical_text(store: Store, type_: str, text: str, base: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    words = " ".join(tokens(text))
    if not words:
        return []
    return store.query(
        f"""CALL db.index.fulltext.queryNodes($index, $words) YIELD node AS x, score WHERE {base}
            RETURN x.id AS id, score ORDER BY score DESC, id LIMIT $pool""",
        index=TEXT_INDEX[type_],
        words=words,
        pool=POOL,
        **params,
    )


def _semantic(store: Store, type_: str, text: str | None, base: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    assert store.embed is not None and text
    vector = store.embed([INSTRUCT[type_] + text])[0]
    return store.query(
        f"""CYPHER 25
            MATCH (x) SEARCH x IN (VECTOR INDEX {VECTOR_INDEX[type_]} FOR $vector LIMIT $k) SCORE AS score
            WITH x, score WHERE {base}
            RETURN x.id AS id, score ORDER BY score DESC, id LIMIT $pool""",
        vector=vector,
        k=POOL * OVERFETCH,
        pool=POOL,
        **params,
    )


# ── 诊断 ──────────────────────────────────────────────────────────────


def _diagnostics(store: Store, compiled: Compiled, matched: set[str]) -> dict[str, Any]:
    """写了 ``uses`` 时：``role_missing`` 是 USES 指向这些数据集却没有 role 的实验；
    ``expandable`` 是评测数据落在其组成部分上、本次没有选中的实验（可用 ``expand.parts`` 放宽）。"""
    refs = compiled.refs.get("uses")
    if not refs:
        return {}
    out: dict[str, Any] = {}
    rows = store.query(
        """MATCH (x:Experiment)-[r:USES]->(t) WHERE t.id IN $refs AND r.role IS NULL
           RETURN DISTINCT x.id AS id ORDER BY id""",
        refs=refs,
    )
    if rows:
        out["role_missing"] = {"count": len(rows), "refs": [r["id"] for r in rows]}
    rows = store.query(
        """MATCH (part)-[:PART_OF*1..3]->(t) WHERE t.id IN $refs AND NOT part.id IN $refs
           MATCH (x:Experiment)-[:USES {role: 'evaluation_data'}]->(part)
           RETURN DISTINCT x.id AS id ORDER BY id""",
        refs=refs,
    )
    extra = [r["id"] for r in rows if r["id"] not in matched]
    if extra:
        out["expandable"] = {"count": len(extra), "refs": extra, "with": "expand: {parts: <depth>}"}
    return out


SEARCH = db_operator(
    name="Search",
    parameters=schema(
        {
            "type": {"type": "string", "enum": list(TYPES)},
            "query": TERMS,
            "kinds": STRINGS,
            "where": {
                "type": "object",
            },
            "expand": {"type": "object"},
            "scope": STRINGS,
            "budget": {"type": "integer"},
            "continuation": {"type": "integer"},
        },
        ["type"],
    ),
    run=search,
)


__all__ = ["DEFAULT_BUDGET", "SEARCH", "Found", "find", "search"]
