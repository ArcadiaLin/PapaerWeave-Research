"""Traverse：从已确认的引用出发，沿声明的关系走到相关对象，保留路径（docs/designs/v2/operators.md §3.3）。

    traverse(start, path=[], budget=50, continuation?) -> 读视图
    hop = {rel, dir: out | in | both, kinds?, where?, edge?, depth?: 1–3}

- 路径为空时只返回起点（按 id 读取）。
- 每一跳先按图模型的端点表检查：从上一跳可能的 kind 出发，沿 ``rel`` 与 ``dir`` 能否到达某个 kind（再与 ``kinds``
  取交集）；不能成立是契约错误，例如从 Method 沿出边走 ``EVALUATES``。对称关系 ``OVERLAPS_WITH`` 忽略方向。
- ``depth`` 只用于传递性关系（``BROADER``、``PART_OF``、``HAS_PART``、``DERIVED_FROM``），取 1 到 ``depth`` 步的
  全部路径，同一路径不重复走同一条边。``kinds`` 与 ``where`` 约束这一跳的终点，``edge`` 约束这一跳走过的每条边。
- 预算按路径计，结果另有容量上限（与 Search 相同，见 :mod:`e09.query.excerpts`）：对象视图要原样交回 Commit，
  不能截断字段，所以放不下时从本页末尾去掉路径，续取位置随之前移，``meta.size`` 给出上限与实际大小。
- 返回读视图：``nodes`` 是本页路径上的全部节点（起点、中间节点与终点），``meta.items`` 是终点，
  ``meta.bindings`` 是路径，如 ``[method_0028, <-EVALUATES-, exp_0001, -USES->, dataset_0006]``。边上的属性在
  起点一侧节点的出边里。

``USED`` 是 Artifact 的使用关系：出边是产物用到的对象，入边是用过某个对象的产物（``kinds: [Artifact]``）。
系统关系 ``NAMES``、``MATERIAL_OF`` 不对外开放：别名在视图中，文档在 Artifact 视图的 ``_document`` 中。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from ...artifact.stale import readonly
from ...query.revisions import latest_revisions
from ...model.schema import ARTIFACT, DERIVED_FIELDS, FAMILY, TRAVERSABLE
from ...query.conditions import compile_where
from ...query.excerpts import LIMIT
from ...query.view import dump, render, source_refs_of
from ...store.store import ContractError, Store
from ..base import STRINGS, db_operator, schema

TRANSITIVE = frozenset({"BROADER", "PART_OF", "HAS_PART", "DERIVED_FROM"})
NODE_KINDS = frozenset(FAMILY) | {ARTIFACT}
DIRS = ("out", "in", "both")
HOP_KEYS = frozenset({"rel", "dir", "kinds", "where", "edge", "depth"})
MAX_HOPS = 3
MAX_DEPTH = 3
DEFAULT_BUDGET = 50
MAX_BUDGET = 500


@dataclass(frozen=True, slots=True)
class _Hop:
    rels: tuple[str, ...]
    dir: str
    kinds: frozenset[str] | None
    where: Mapping[str, Any]
    edge: Mapping[str, Any]
    depth: int


@dataclass(frozen=True, slots=True)
class _Path:
    start: int  # 起点在 start 中的位置，用于排序
    steps: tuple[str, ...]  # 节点 id 与方向标记交替：(n0, "-REL->", n1, ...)
    edges: frozenset[str] = frozenset()  # 本跳已走过的边（elementId）
    end_kind: str | None = None

    @property
    def end(self) -> str:
        return self.steps[-1]

    def nodes(self) -> list[str]:
        return list(self.steps[::2])


def traverse(
    store: Store,
    start: list[str] | str,
    path: list[Mapping[str, Any]] | None = None,
    budget: int = DEFAULT_BUDGET,
    continuation: int | None = None,
) -> dict[str, Any]:
    request = {"op": "Traverse", "start": start, "path": path or [], "budget": budget}
    if continuation is not None:
        request["continuation"] = continuation
    problems: list[dict[str, str]] = []
    before = store.snapshot()
    starts = _starts(start, problems)
    hops = [_hop(i, hop, problems) for i, hop in enumerate(path or [])]
    if len(hops) > MAX_HOPS:
        problems.append({"at": "path", "msg": f"at most {MAX_HOPS} hops"})
    offset = _paging(budget, continuation, problems)
    if problems:
        raise ContractError(problems)

    kinds = store.kinds(starts)
    not_model = [s for s in starts if s in kinds and kinds[s] is None]
    if not_model:
        raise ContractError([{"at": "start", "msg": f"not objects of the graph model: {not_model}"}])
    missing = [{"ref": s, "param": "start", "missing_in": "store"} for s in starts if s not in kinds]
    present = [s for s in starts if s in kinds]

    # 先按端点表检查整条路径，再执行
    frontier = frozenset(k for s in present if (k := kinds[s]) is not None)
    compiled = []
    for i, hop in enumerate(hops):
        if not frontier:  # 起点都不在库中：无从检查，也不会有结果
            break
        reached = _reach(frontier, hop)
        if not reached:
            target = f" to {sorted(hop.kinds)}" if hop.kinds else ""
            msg = f"no {'|'.join(hop.rels)} {hop.dir} from {sorted(frontier)}{target} in the graph model"
            raise ContractError([{"at": f"path[{i}]", "msg": msg}])
        where = compile_where(store, hop.where, reached, at=f"path[{i}].where", prefix=f"h{i}_")
        missing += where.missing
        compiled.append((hop, reached, where))
        frontier = reached

    paths = [_Path(i, (s,)) for i, s in enumerate(present)]
    for hop, reached, where in compiled:
        if where.missing:
            paths = []
        paths = _walk(store, paths, hop, reached, where.predicate, where.params)

    paths.sort(key=lambda p: (p.start, p.steps))
    page = paths[offset : offset + budget]
    shown = list(dict.fromkeys(n for p in page for n in p.nodes()))
    state = store.graph.local_state(shown)
    artifacts = readonly(store, [n for n in shown if ARTIFACT in state.nodes[n].labels])
    artifacts |= {k: {"_revised": v} for k, v in latest_revisions(store, shown).items()}
    snapshot, changed = store.stable(before)

    def view(count: int) -> dict[str, Any]:
        """本页前 ``count`` 条路径的读视图。"""
        kept = page[:count]
        end = offset + count
        more = end < len(paths)
        items = list(dict.fromkeys(p.end for p in kept))
        coverage = {
            "start": len(starts),
            "hops": len(hops),
            "budget": budget,
            "matched": len(paths),
            "returned": count,
            "truncated": more,
            "snapshot": snapshot,
        }
        meta = {
            "query": request,
            "items": items,
            "bindings": [list(p.steps) for p in kept],
            "source_refs": list(dict.fromkeys(r for i in items for r in source_refs_of(i, state))),
            "missing": missing,
            "coverage": coverage,
            "continuation": end if more else None,
            "diagnostics": changed,
            "size": {"limit": LIMIT, "used": LIMIT},  # 占位：位数不少于实际
        }
        nodes = list(dict.fromkeys(n for p in kept for n in p.nodes()))
        return render(state, nodes, meta, artifacts)

    out = view(_fit(view, len(page)))
    for _ in range(2):  # 写入 used 本身后的大小；第二次计入位数的变化
        out["meta"]["size"]["used"] = _size(out)
    return out


def _fit(view: Callable[[int], dict[str, Any]], total: int) -> int:
    """放得下的最多路径数（视图大小随路径数单调不减，二分查找）；一条也放不下时仍返回一条。"""
    if total == 0 or _size(view(total)) <= LIMIT:
        return total
    low, high = 1, total - 1  # view(low) 不一定放得下；high 之后的都放不下
    while low < high:
        mid = (low + high + 1) // 2
        if _size(view(mid)) <= LIMIT:
            low = mid
        else:
            high = mid - 1
    return low


def _size(view: dict[str, Any]) -> int:
    return len(dump(view).encode("utf-8"))


# ── 参数 ──────────────────────────────────────────────────────────────


def _starts(start: Any, problems: list[dict[str, str]]) -> list[str]:
    starts = [start] if isinstance(start, str) else start
    if not isinstance(starts, list) or not starts or not all(isinstance(s, str) and s for s in starts):
        problems.append({"at": "start", "msg": "a non-empty list of ids"})
        return []
    return list(dict.fromkeys(starts))


def _hop(i: int, hop: Any, problems: list[dict[str, str]]) -> _Hop:
    at = f"path[{i}]"
    if not isinstance(hop, Mapping):
        problems.append({"at": at, "msg": "a hop is {rel, dir, kinds?, where?, edge?, depth?}"})
        return _Hop((), "out", None, {}, {}, 1)
    if unknown := set(hop) - HOP_KEYS:
        problems.append({"at": at, "msg": f"unknown keys {sorted(unknown)}; a hop has {sorted(HOP_KEYS)}"})
    rels = hop.get("rel")
    rels = [rels] if isinstance(rels, str) else rels
    if not isinstance(rels, list) or not rels:
        problems.append({"at": f"{at}.rel", "msg": "a relationship type or a list of them"})
        rels = []
    for rel in rels:
        if rel not in TRAVERSABLE:
            problems.append({"at": f"{at}.rel", "msg": f"{rel!r} cannot be traversed; one of {sorted(TRAVERSABLE)}"})
    direction = hop.get("dir", "out")
    if direction not in DIRS:
        problems.append({"at": f"{at}.dir", "msg": f"one of {list(DIRS)}"})
    kinds = hop.get("kinds")
    if kinds is not None:
        kinds = [kinds] if isinstance(kinds, str) else kinds
        if not isinstance(kinds, list) or not kinds or not set(kinds) <= NODE_KINDS:
            problems.append({"at": f"{at}.kinds", "msg": "a non-empty list of kinds"})
            kinds = None
    where, edge = hop.get("where") or {}, hop.get("edge") or {}
    if not isinstance(where, Mapping):
        problems.append({"at": f"{at}.where", "msg": "a mapping of conditions"})
        where = {}
    if not isinstance(edge, Mapping):
        problems.append({"at": f"{at}.edge", "msg": "a mapping of edge properties"})
        edge = {}
    depth = hop.get("depth", 1)
    if not isinstance(depth, int) or isinstance(depth, bool) or not 1 <= depth <= MAX_DEPTH:
        problems.append({"at": f"{at}.depth", "msg": f"an integer from 1 to {MAX_DEPTH}"})
        depth = 1
    elif depth > 1 and not set(rels) <= TRANSITIVE:
        problems.append({"at": f"{at}.depth", "msg": f"depth only applies to {sorted(TRANSITIVE)}"})
    return _Hop(tuple(rels), direction, frozenset(kinds) if kinds else None, where, edge, depth)


def _paging(budget: Any, continuation: Any, problems: list[dict[str, str]]) -> int:
    if not isinstance(budget, int) or isinstance(budget, bool) or not 1 <= budget <= MAX_BUDGET:
        problems.append({"at": "budget", "msg": f"an integer from 1 to {MAX_BUDGET}"})
    if continuation is None:
        return 0
    if not isinstance(continuation, int) or isinstance(continuation, bool) or continuation < 0:
        problems.append({"at": "continuation", "msg": "the continuation returned by the previous call"})
        return 0
    return continuation


# ── 端点表 ────────────────────────────────────────────────────────────


def _reach(frontier: frozenset[str], hop: _Hop) -> frozenset[str]:
    """从 ``frontier`` 中的 kind 出发走这一跳（1 到 ``depth`` 步）可能到达的 kind。"""
    reached: set[str] = set()
    current = set(frontier)
    for _ in range(hop.depth):
        step: set[str] = set()
        for rel in hop.rels:
            spec = TRAVERSABLE[rel]
            for srcs, dsts in spec.ends:
                if hop.dir in ("out", "both") or spec.symmetric:
                    step |= dsts if srcs & current else set()
                if hop.dir in ("in", "both") or spec.symmetric:
                    step |= srcs if dsts & current else set()
        reached |= step
        current = step
    reached &= NODE_KINDS
    return frozenset(reached & hop.kinds if hop.kinds else reached)


# ── 执行 ──────────────────────────────────────────────────────────────


def _walk(
    store: Store, paths: list[_Path], hop: _Hop, reached: frozenset[str], predicate: str, params: dict[str, Any]
) -> list[_Path]:
    results: list[_Path] = []
    current = [_Path(p.start, p.steps) for p in paths]
    for _ in range(hop.depth):
        steps = _steps(store, {p.end for p in current}, hop)
        current = [
            _Path(p.start, (*p.steps, label, dst), p.edges | {eid}, kind)
            for p in current
            for label, dst, eid, kind, props in steps.get(p.end, [])
            if kind is not None and eid not in p.edges and _edge_matches(props, hop.edge)
        ]
        results += current
    candidates = [p for p in results if p.end_kind in reached]
    if predicate != "true" and candidates:
        rows = store.query(
            f"MATCH (x) WHERE x.id IN $ids AND {predicate} RETURN x.id AS id",
            ids=sorted({p.end for p in candidates}),
            **params,
        )
        keep = {r["id"] for r in rows}
        candidates = [p for p in candidates if p.end in keep]
    return list({p.steps: p for p in candidates}.values())


def _edge_matches(props: Mapping[str, Any], wanted: Mapping[str, Any]) -> bool:
    """边属性条件：给列表时取析取；边上的属性是列表时（如 ``USED.role``），有一个取值匹配即可。"""
    for key, value in wanted.items():
        values = value if isinstance(value, list) else [value]
        actual = props.get(key)
        if not any(v in values for v in (actual if isinstance(actual, list) else [actual])):
            return False
    return True


def _steps(store: Store, ids: set[str], hop: _Hop) -> dict[str, list[tuple[str, str, str, str | None, dict]]]:
    """``ids`` 沿这一跳的关系走一步：起点 → [(方向标记, 终点, 边, 终点 kind, 边属性)]。"""
    if not ids:
        return {}
    directions = set()
    for rel in hop.rels:
        both = hop.dir == "both" or TRAVERSABLE[rel].symmetric
        directions |= {"out", "in"} if both else {hop.dir}
    out: dict[str, list[tuple[str, str, str, str | None, dict]]] = {}
    for direction in sorted(directions):
        pattern = "(a)-[r]->(b)" if direction == "out" else "(a)<-[r]-(b)"
        rows = store.query(
            f"""MATCH {pattern} WHERE a.id IN $ids AND type(r) IN $rels AND b.id IS NOT NULL
                RETURN a.id AS a, type(r) AS rel, b.id AS b, labels(b) AS labels, elementId(r) AS eid,
                       [k IN keys(r) WHERE NOT k IN $hidden | [k, r[k]]] AS props""",
            ids=sorted(ids),
            rels=list(hop.rels),
            hidden=sorted(DERIVED_FIELDS),
        )
        for r in rows:
            label = f"-{r['rel']}->" if direction == "out" else f"<-{r['rel']}-"
            kind = next((label_ for label_ in r["labels"] if label_ in FAMILY), None)
            kind = kind or (ARTIFACT if ARTIFACT in r["labels"] else None)
            out.setdefault(r["a"], []).append((label, r["b"], r["eid"], kind, dict(r["props"])))
    return out


TRAVERSE = db_operator(
    name="Traverse",
    parameters=schema(
        {
            "start": STRINGS,
            "path": {"type": "array", "items": {"type": "object"}},
            "budget": {"type": "integer"},
            "continuation": {"type": "integer"},
        },
        ["start"],
    ),
    run=traverse,
)


__all__ = ["DEFAULT_BUDGET", "TRAVERSE", "traverse"]
