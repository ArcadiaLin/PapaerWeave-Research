"""traverse：从起点沿关系走 1–3 跳，列出到达的节点（结构条件与穷举用它，不用 search）。

    traverse(start, path?, limit?: 30, offset?: 0) -> 带注释的 YAML：到达的节点 → 紧凑投影 + _via
    path = [{rel: <类型或类型列表>, dir?: out | in | both, kind?: [<kind>]}]

- 路径为空时返回起点的紧凑投影。
- 每跳的 ``rel`` 是关系类型（含系统关系 ``FROM``：Content → 论文，``USED``：产物 → 用到的节点），``dir`` 默认 ``out``；
  ``kind`` 只留这些 kind（或类别、产物类型）的终点。
- 到达的节点按 id 排序，从第 ``offset`` 个起最多列 ``limit`` 个，总数在开头的注释中；返回超过 :data:`BUDGET` 时提前
  停下。还有剩余时，结尾的注释给出下一页的 ``offset``（与 pi 的 ``read`` 同一用法）。同样的参数与库状态返回同样的一页。每个节点的 ``_via`` 给出最后一跳从哪些节点、经哪条边
  到达（最多 3 个），带边上的属性，如 ``_via: {exp_0004: {USES: {printed_as: ECL}}}``。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from ...model.schema import ARTIFACT, ARTIFACT_TYPES, FAMILIES, FROM, KIND_SPECS, RELATIONSHIPS, USED
from ...query.read import compact_view
from ...store.store import ContractError, Store
from ..base import BUDGET, STRINGS, Rendered, db_operator, schema

MAX_HOPS = 3
DEFAULT_LIMIT = 30
MAX_LIMIT = 100
VIA = 3
RELS = (*RELATIONSHIPS, FROM, USED)
_HIDDEN = {"formed_by", "formed_at", "material_ref", "embedding", "embedding_key", "search_text"}


def traverse(
    store: Store,
    start: list[str] | str,
    path: list[dict[str, Any]] | None = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> Rendered:
    starts = [start] if isinstance(start, str) else start
    if not isinstance(starts, list) or not starts or not all(isinstance(s, str) for s in starts):
        raise ContractError([{"at": "start", "msg": "a list of node ids"}])
    if not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        raise ContractError([{"at": "limit", "msg": f"1-{MAX_LIMIT}"}])
    if not isinstance(offset, int) or offset < 0:
        raise ContractError([{"at": "offset", "msg": "0 or more: reached nodes to skip"}])
    hops = [_hop(h, i) for i, h in enumerate(path or [])]
    if len(hops) > MAX_HOPS:
        raise ContractError([{"at": "path", "msg": f"at most {MAX_HOPS} hops"}])
    known = store.kinds(starts)
    missing = [s for s in starts if s not in known]
    frontier = [s for s in starts if s in known]
    via: dict[str, dict[str, dict[str, Any]]] = {}
    for rels, direction, kinds in hops:
        frontier, via = _step(store, frontier, rels, direction, kinds)
        if not frontier:
            break
    reached = sorted(frontier)
    shown = reached[offset : offset + limit]
    extra = {i: {"_via": dict(list(via[i].items())[:VIA])} for i in shown if i in via}
    view = compact_view(store, shown, extra)
    for i in shown:
        for prev in via.get(i, {}):
            view.names.setdefault(prev, prev)
    if via:
        names_needed = [p for i in shown for p in list(via.get(i, {}))[:VIA]]
        names = compact_view(store, list(dict.fromkeys(names_needed))).names if names_needed else {}
        view.names.update(names)
    header = [f"{len(reached)} node(s) reached, sorted by id"]
    if missing:
        header.append(f"not in the store: {', '.join(missing)}")
    while len(shown) > 1 and len(view.subset(shown).text(header).encode()) > BUDGET:
        shown.pop()
    page = view.subset(shown)
    end = offset + len(shown)
    following = end if shown and end < len(reached) else None
    footer = [f"[Showing {offset + 1}-{end} of {len(reached)} nodes. Use offset={end} to continue.]"] if following else []
    text = page.text(header) + "".join(f"# {line}\n" for line in footer)
    return Rendered({"reached": len(reached), "nodes": page.data, "missing": missing, "next": following}, text)


def _hop(hop: Any, i: int) -> tuple[list[str], str, set[str] | None]:
    at = f"path[{i}]"
    if not isinstance(hop, dict) or "rel" not in hop or not set(hop) <= {"rel", "dir", "kind"}:
        raise ContractError([{"at": at, "msg": "a hop is {rel, dir?, kind?}"}])
    rels = [hop["rel"]] if isinstance(hop["rel"], str) else hop["rel"]
    if not isinstance(rels, list) or not rels or any(r not in RELS for r in rels):
        raise ContractError([{"at": f"{at}.rel", "msg": f"relationship types among {', '.join(RELS)}"}])
    direction = hop.get("dir", "out")
    if direction not in ("out", "in", "both"):
        raise ContractError([{"at": f"{at}.dir", "msg": "out, in or both"}])
    kinds = hop.get("kind")
    if kinds is None:
        return rels, direction, None
    kinds = [kinds] if isinstance(kinds, str) else kinds
    allowed: set[str] = set()
    for k in kinds:
        if k in KIND_SPECS or k in ARTIFACT_TYPES:
            allowed.add(k)
        elif k in FAMILIES:
            allowed.update(s for s, spec in KIND_SPECS.items() if spec.family == k)
        elif k == ARTIFACT:
            allowed.update(ARTIFACT_TYPES)
        else:
            raise ContractError([{"at": f"{at}.kind", "msg": f"unknown kind {k}"}])
    return rels, direction, allowed


def _step(
    store: Store, frontier: list[str], rels: list[str], direction: str, kinds: set[str] | None
) -> tuple[list[str], dict[str, dict[str, dict[str, Any]]]]:
    pattern = {"out": "(a)-[r:{t}]->(b)", "in": "(a)<-[r:{t}]-(b)", "both": "(a)-[r:{t}]-(b)"}[direction]
    rows = store.query(
        f"""UNWIND $ids AS id MATCH (a {{id: id}}) MATCH {pattern.format(t='|'.join(rels))}
            WHERE b.id IS NOT NULL AND (b:Searchable)
              AND ($kinds IS NULL OR any(l IN labels(b) WHERE l IN $kinds) OR b.op IN $kinds)
            RETURN a.id AS a, type(r) AS type, b.id AS b, properties(r) AS props""",
        ids=frontier,
        kinds=sorted(kinds) if kinds is not None else None,
    )
    via: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for r in rows:
        props = {k: v for k, v in r["props"].items() if k not in _HIDDEN}
        via[r["b"]].setdefault(r["a"], {})[r["type"]] = props or None
    return sorted(via), via


TRAVERSE = db_operator(
    name="traverse",
    parameters=schema(
        {
            "start": STRINGS,
            "path": {
                "type": "array",
                "items": schema(
                    {"rel": {"anyOf": [{"type": "string"}, STRINGS]}, "dir": {"type": "string"}, "kind": STRINGS},
                    ["rel"],
                ),
            },
            "limit": {"type": "integer"},
            "offset": {"type": "integer"},
        },
        ["start"],
    ),
    run=traverse,
)

__all__ = ["TRAVERSE", "traverse"]
