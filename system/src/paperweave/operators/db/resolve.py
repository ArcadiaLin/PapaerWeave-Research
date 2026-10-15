"""Resolve：把一个说法解析为已存对象的引用（docs/designs/v2/operators.md §3.2）。

三级逐级解析（标识、名称精确键、语义候选），实现见 :mod:`paperweave.query.resolve`；Commit 的查重也用它。Resolve 经
``paperweave.store.graph`` 的连接读 ``E09_NEO4J_URI`` 所指的库，不用调用环境中的 ``store``。

返回给 Agent 的是解析视图：``status`` 与 ``refs``，每个引用带 kind、名称、别名与说明的开头，供 Agent 判断候选
是否就是它要找的对象；语义阶段另给的近似对象（read 模式的 ambiguous、write 模式的查重）在 ``similar`` 中。
匹配过程（各阶段的键与命中、各通道的名次与分数、覆盖与状态）写入日志 ``paperweave.resolve``。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ...model.namekey import normalize
from ...model.schema import kind_of
from ...query.excerpts import cut
from ...query.resolve import resolve
from ...store.graph import q
from ...store.store import ContractError, Store
from ..base import TERMS, db_operator, schema

log = logging.getLogger("paperweave.resolve")

ABOUT_BYTES = 200  # 说明的开头：够判断是不是同一个对象，完整字段用 Traverse 读


def run(
    store: Store, query: dict[str, str] | str, kind: str, scope: str = "global", mode: str = "read"
) -> dict[str, Any]:
    """解析一个说法；参数不合法（未知 kind、未声明的命名空间等）是契约错误。"""
    del store  # 见模块说明
    try:
        result = resolve(query, kind=kind, scope=scope, mode=mode)
    except ValueError as exc:
        raise ContractError([{"at": "query", "msg": str(exc)}]) from exc
    log.info("Resolve %s", json.dumps({"query": query, "kind": kind, "mode": mode, **result}, ensure_ascii=False))
    return view(result)


def view(result: dict[str, Any]) -> dict[str, Any]:
    refs = result["refs"]
    similar = [
        c["id"]
        for step in result["match_trace"]
        if step["stage"] == "semantic" and step["role"] != "result"
        for c in step["candidates"]
    ]
    described = _describe([*refs, *similar])
    out: dict[str, Any] = {"status": result["status"], "refs": [described[i] for i in refs]}
    if similar:
        out["similar"] = [described[i] for i in similar]
    if result["states"]["issues"]:
        out["issues"] = result["states"]["issues"]
    if failed := {ch: s for ch, s in result["coverage"]["channels"].items() if s.startswith("error")}:
        out["failed"] = failed
    return out


def _describe(ids: list[str]) -> dict[str, dict[str, Any]]:
    """各对象的 ``{id, kind, name, aliases?, about?}``；``about`` 是 description 或 definition 的开头。"""
    rows = q(
        """MATCH (o) WHERE o.id IN $ids
           OPTIONAL MATCH (k:NameKey)-[:NAMES]->(o)
           RETURN o.id AS id, labels(o) AS labels, o.name AS name, coalesce(o.description, o.definition) AS about,
                  collect(k.raw) AS raws""",
        ids=sorted(set(ids)),
    )
    out = {}
    for r in rows:
        name = r["name"] or ""
        entry: dict[str, Any] = {"id": r["id"], "kind": kind_of(set(r["labels"])), "name": r["name"]}
        aliases = sorted({raw for raw in r["raws"] if raw and normalize(raw) != normalize(name)})
        if aliases:
            entry["aliases"] = aliases
        if r["about"]:
            entry["about"] = r["about"] if len(r["about"].encode()) <= ABOUT_BYTES else cut(r["about"], ABOUT_BYTES)
        out[r["id"]] = entry
    return {i: out.get(i, {"id": i}) for i in ids}


RESOLVE = db_operator(
    name="Resolve",
    parameters=schema(
        {
            "query": TERMS,
            "kind": {"type": "string"},
            "scope": {"type": "string"},
            "mode": {"type": "string", "enum": ["read", "write"]},
        },
        ["query", "kind"],
    ),
    run=run,
)


__all__ = ["RESOLVE", "run", "view"]
