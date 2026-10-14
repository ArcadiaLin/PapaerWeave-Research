"""结构条件 ``where`` 与引用条件的放宽 ``expand``（docs/designs/v2/operators.md §3.1），Search 与 Traverse 共用。

条件编译成作用于变量 ``x`` 的 Cypher 谓词。多个条件取合取，同一条件给列表时取析取；条件都作用于同一个 ``x``。
引用条件的终点类型按图模型的端点表检查，不成立是契约错误；引用不在库中是数据缺失，记入 ``missing``。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ..artifact.types import identity_key
from ..model.schema import (
    ARTIFACT,
    ARTIFACT_TYPES,
    CONCEPT,
    CONTENT,
    ENTITY,
    EVALUATES_ROLES,
    FAMILY,
    STATED_BY,
    TRAVERSABLE,
)
from ..store.store import ContractError, Store


@dataclass(frozen=True, slots=True)
class Condition:
    """``rel`` 给出时是引用条件 ``(x)-[rel {edge}]->(ref)``，否则是属性条件 ``x.prop``。"""

    subjects: frozenset[str]  # 能带这个条件的 kind
    rel: str | None = None
    prop: str | None = None
    values: frozenset[Any] | None = None  # 属性条件允许的取值；None 表示任意字符串
    edge: Mapping[str, str] = field(default_factory=dict)  # 引用条件固定的边属性


_EXPERIMENT = frozenset({"Experiment"})
_ARTIFACT = frozenset({ARTIFACT})

CONDITIONS = {
    "part_of": Condition(ENTITY, rel="PART_OF"),
    "for_task": Condition(frozenset({"Dataset", "Benchmark"}), rel="FOR_TASK"),
    "broader": Condition(CONCEPT, rel="BROADER"),
    "about": Condition(CONTENT, rel="ABOUT"),
    "from": Condition(CONTENT, rel="FROM"),
    "evaluates": Condition(_EXPERIMENT, rel="EVALUATES"),
    "uses": Condition(_EXPERIMENT, rel="USES", edge={"role": "evaluation_data"}),
    "on_task": Condition(_EXPERIMENT, rel="ON_TASK"),
    "evaluated_on": Condition(_EXPERIMENT, rel="EVALUATED_ON"),
    "supported_by": Condition(frozenset({"Claim"}), rel="SUPPORTED_BY"),
    "stub": Condition(ENTITY | CONCEPT, prop="stub", values=frozenset({True, False})),
    "stated_by": Condition(frozenset({"Contribution"}), prop="stated_by", values=STATED_BY),
    "formed_by": Condition(CONTENT | _ARTIFACT, prop="formed_by"),
    "op": Condition(_ARTIFACT, prop="op", values=frozenset(ARTIFACT_TYPES)),
    "session": Condition(_ARTIFACT, prop="session"),
    # 共同产物的身份：给 {type, <身份字段>...}，换成检入时存在 key 上的规范化身份键后精确匹配
    "key": Condition(_ARTIFACT, prop="key"),
    "used": Condition(_ARTIFACT, rel="USED"),
}
ROLE = "role"  # 只随 evaluates 出现：EVALUATES 边的 role
EXPAND = {"narrower": "Concept", "parts": "Entity"}  # 放宽方式 → 适用的引用类别
MAX_DEPTH = 3


@dataclass(frozen=True, slots=True)
class Compiled:
    predicate: str  # 作用于 x 的谓词；没有条件时为 "true"
    params: dict[str, Any]
    missing: list[dict[str, str]]  # 不在库中的引用：{ref, param, missing_in}
    expanded: dict[str, list[str]]  # 放宽后加入的引用：原引用 → 加入的引用
    refs: dict[str, list[str]]  # 各引用条件最终使用的引用（含放宽加入的）


def compile_where(
    store: Store,
    where: Mapping[str, Any] | None,
    subjects: frozenset[str],
    *,
    expand: Mapping[str, Any] | None = None,
    at: str = "where",
    expand_at: str = "expand",
    prefix: str = "w",
) -> Compiled:
    """把 ``where`` 编译成谓词。``subjects`` 是 ``x`` 可能的 kind；``at`` / ``expand_at`` 是出错时报告的参数位置，
    ``prefix`` 区分同一查询中多组条件的参数名。"""
    problems: list[dict[str, str]] = []
    where = dict(where or {})
    depths = _expand_depths(expand, problems, expand_at)
    role = where.pop(ROLE, None)
    if role is not None and "evaluates" not in where:
        problems.append({"at": f"{at}.{ROLE}", "msg": "role only qualifies evaluates"})

    clauses: list[str] = []
    params: dict[str, Any] = {}
    missing: list[dict[str, str]] = []
    expanded: dict[str, list[str]] = {}
    used: dict[str, list[str]] = {}
    for i, (name, value) in enumerate(where.items()):
        cond_at = f"{at}.{name}"
        cond = CONDITIONS.get(name)
        if cond is None:
            problems.append({"at": cond_at, "msg": f"unknown condition; one of {sorted([*CONDITIONS, ROLE])}"})
            continue
        if not subjects <= cond.subjects:
            msg = f"applies to {sorted(cond.subjects)}, not {sorted(subjects - cond.subjects)}; restrict kinds"
            problems.append({"at": cond_at, "msg": msg})
            continue
        values = value if isinstance(value, list) else [value]
        if not values:
            problems.append({"at": cond_at, "msg": "an empty list matches nothing"})
            continue
        param = f"{prefix}{i}"
        if name == "key":
            try:
                values = [
                    identity_key(v, at=cond_at if len(values) == 1 else f"{cond_at}[{j}]") for j, v in enumerate(values)
                ]
            except ContractError as exc:
                problems += exc.errors
                continue
        if cond.prop is not None:
            clause = _prop_clause(cond, values, param, cond_at, problems)
            if clause is not None:
                clauses.append(clause)
                params[param] = values
            continue

        assert cond.rel is not None
        if not all(isinstance(v, str) for v in values):
            problems.append({"at": cond_at, "msg": "references must be ids"})
            continue
        kinds = store.kinds(values)
        allowed = _targets(cond.rel, subjects)
        present = []
        for ref in values:
            if ref not in kinds:
                missing.append({"ref": ref, "param": cond_at, "missing_in": "store"})
            elif kinds[ref] not in allowed:
                msg = f"{ref} is a {kinds[ref]}; {cond.rel} leads to {sorted(allowed)}"
                problems.append({"at": cond_at, "msg": msg})
            else:
                present.append(ref)
        refs = list(present)
        for ref in present:
            added = _expand(store, ref, FAMILY.get(kinds[ref] or "", ""), depths)
            if added:
                expanded[ref] = added
                refs += [r for r in added if r not in refs]
        edge = dict(cond.edge)
        edge_clause = "".join(f" AND r.{k} = ${param}_{k}" for k in edge)
        params.update({f"{param}_{k}": v for k, v in edge.items()})
        if name == "evaluates" and role is not None:
            roles = role if isinstance(role, list) else [role]
            if not roles or not set(roles) <= EVALUATES_ROLES:
                problems.append({"at": f"{at}.{ROLE}", "msg": f"one of {sorted(EVALUATES_ROLES)}"})
            edge_clause += f" AND r.role IN ${param}_role"
            params[f"{param}_role"] = roles
        clauses.append(f"EXISTS {{ MATCH (x)-[r:{cond.rel}]->(t) WHERE t.id IN ${param}{edge_clause} }}")
        params[param] = refs
        used[name] = refs

    if problems:
        raise ContractError(problems)
    return Compiled(" AND ".join(clauses) or "true", params, missing, expanded, used)


def _prop_clause(cond: Condition, values: list[Any], param: str, at: str, problems: list[dict[str, str]]) -> str | None:
    allowed = cond.values
    if allowed is not None and not all(any(v == a and type(v) is type(a) for a in allowed) for v in values):
        problems.append({"at": at, "msg": f"one of {sorted(allowed, key=str)}"})
        return None
    if allowed is None and not all(isinstance(v, str) for v in values):
        problems.append({"at": at, "msg": "values must be strings"})
        return None
    if cond.prop == "stub":  # 非桩节点没有 stub 属性
        return f"coalesce(x.stub, false) IN ${param}"
    return f"x.{cond.prop} IN ${param}"


def _targets(rel: str, subjects: frozenset[str]) -> frozenset[str]:
    """从 ``subjects`` 沿 ``rel`` 出边能到达的 kind（含 ``Artifact``）。"""
    out: set[str] = set()
    for srcs, dsts in TRAVERSABLE[rel].ends:
        if srcs & subjects:
            out |= dsts
    return frozenset(out & (set(FAMILY) | {ARTIFACT}))


def _expand_depths(expand: Mapping[str, Any] | None, problems: list[dict[str, str]], at: str) -> dict[str, int]:
    depths: dict[str, int] = {}
    for key, depth in (expand or {}).items():
        if key not in EXPAND:
            problems.append({"at": f"{at}.{key}", "msg": f"one of {sorted(EXPAND)}"})
        elif not isinstance(depth, int) or isinstance(depth, bool) or not 1 <= depth <= MAX_DEPTH:
            problems.append({"at": f"{at}.{key}", "msg": f"depth is an integer from 1 to {MAX_DEPTH}"})
        else:
            depths[EXPAND[key]] = depth
    return depths


def _expand(store: Store, ref: str, family: str, depths: Mapping[str, int]) -> list[str]:
    """Concept 加上更窄的概念（反向 BROADER），Entity 加上组成部分（反向 PART_OF）。"""
    depth = depths.get(family)
    if depth is None:
        return []
    rel = "BROADER" if family == "Concept" else "PART_OF"
    rows = store.query(
        f"MATCH (n)-[:{rel}*1..{depth}]->({{id: $ref}}) WHERE n.id IS NOT NULL RETURN DISTINCT n.id AS id ORDER BY id",
        ref=ref,
    )
    return [r["id"] for r in rows]


__all__ = ["CONDITIONS", "EXPAND", "Compiled", "Condition", "compile_where"]
