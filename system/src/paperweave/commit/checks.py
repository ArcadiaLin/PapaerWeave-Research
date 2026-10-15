"""写入后状态的检查：在“应用变更集之后”的局部状态上核对模型规则。

检查范围是本次触及的节点：新建或修改的节点、增删改过关系的端点。它们的全部关系都在局部状态中，
所以改 kind 之后原有的边也会按新的 kind 复核（commit.md §5）。
"""

from __future__ import annotations

from collections.abc import Callable

from graph_vc import Changeset, EdgeKey, GraphState

from ..model.schema import (
    ARTIFACT,
    EVALUATES_ROLES,
    FAMILY,
    RELATIONSHIPS,
    REQUIRED_FIELDS,
    REQUIRED_RELS,
    STANCE_RELS,
    STATED_BY,
    STUB_KINDS,
    SYSTEM_RELS,
    USES_ROLES,
    kind_of,
)
from .problems import Problem

# 带原文锚点的 Content：FROM 必须给出定位（§4.2：stated_by: paper 必须带原文锚点）
_LOCATED = frozenset({"Claim", "Experiment"})


def touched(changeset: Changeset) -> set[str]:
    """本次新建、修改的节点，以及增删改过关系的端点；不含删除的节点。"""
    deleted = {n.id for n in changeset.nodes if n.op == "delete"}
    ids = {n.id for n in changeset.nodes} | {end for e in changeset.edges for end in (e.key.src, e.key.dst)}
    return ids - deleted


def check_state(after: GraphState, ids: set[str], ref: Callable[[str], str] = str) -> list[Problem]:
    """核对 ``ids`` 中模型节点在 ``after`` 中的字段、必需关系，以及与它们相连的关系。"""
    problems: list[Problem] = []
    edges: set[EdgeKey] = set()
    for node_id in sorted(ids):
        node = after.nodes.get(node_id)
        kind = kind_of(node.labels) if node is not None else None
        if node is None or kind is None:
            continue
        edges |= after.incident(node_id)
        at = f"nodes.{ref(node_id)}"
        if node.labels != {FAMILY[kind], kind}:
            problems.append(
                Problem("labels", at, f"expected labels {FAMILY[kind]} and {kind}, got {sorted(node.labels)}")
            )

        stub = node.props.get("stub") is True
        if stub and kind not in STUB_KINDS:
            problems.append(Problem("field", f"{at}.stub", f"{kind} cannot be a stub"))
        required = {"name"} if stub else REQUIRED_FIELDS[kind]
        for name in sorted(required - node.props.keys()):
            problems.append(Problem("required-field", f"{at}.{name}", f"{kind} requires {name}"))

        stated_by = node.props.get("stated_by")
        if kind == "Contribution" and stated_by in STATED_BY:
            if stated_by == "agent" and "formed_by" not in node.props:
                problems.append(Problem("field", at, "a contribution stated by an agent records formed_by"))
        if kind == "Observation" and "formed_by" not in node.props:
            problems.append(Problem("field", at, "an observation records formed_by"))

        outgoing = {k.type for k in after.edges if k.src == node_id}
        for rel_type in REQUIRED_RELS.get(kind, ()):
            if rel_type not in outgoing:
                problems.append(Problem("required-edge", f"{at}.{rel_type}", f"{kind} requires {rel_type}"))
        if kind in _LOCATED or (kind == "Contribution" and stated_by == "paper"):
            sources = [k for k in after.edges if k.src == node_id and k.type == "FROM"]
            if sources and not any(after.edges[k].get("locators") for k in sources):
                problems.append(Problem("required-edge", f"{at}.FROM", f"{kind} from a paper needs locators"))

    for key in sorted(edges, key=str):
        problems += _check_edge(after, key, ref)
    return problems


def _check_edge(state: GraphState, key: EdgeKey, ref: Callable[[str], str]) -> list[Problem]:
    at = f"nodes.{ref(key.src)}.{key.type}[{ref(key.dst)}]"
    if key.type in SYSTEM_RELS:
        return []
    spec = RELATIONSHIPS.get(key.type)
    if spec is None:
        return [Problem("relationship", at, f"relationship type {key.type} is not in the graph model")]
    src, dst = _kind(state, key.src), _kind(state, key.dst)
    problems = []
    if not any(src in srcs and dst in dsts for srcs, dsts in spec.ends):
        problems.append(Problem("endpoint", at, f"{key.type} cannot go from {src} to {dst}"))
    elif spec.same_kind and src != dst:
        problems.append(Problem("endpoint", at, f"{key.type} connects concepts of the same kind ({src} ≠ {dst})"))
    if spec.symmetric and EdgeKey(key.dst, key.type, key.src) in state.edges:
        problems.append(Problem("endpoint", at, f"{key.type} is symmetric; keep only one direction"))

    props = state.edges[key]
    for name in sorted(spec.required - props.keys()):
        problems.append(Problem("required-field", f"{at}.{name}", f"{key.type} requires {name}"))
    if key.type == "EVALUATES" and props.get("role") not in EVALUATES_ROLES | {None}:
        problems.append(Problem("field", f"{at}.role", f"role is one of {sorted(EVALUATES_ROLES)}"))
    if key.type == "USES" and props.get("role") not in USES_ROLES | {None}:
        problems.append(Problem("field", f"{at}.role", f"role is one of {sorted(USES_ROLES)}"))
    if key.type in STANCE_RELS:
        if props.get("stated_by") == "agent" and "formed_by" not in props:
            problems.append(Problem("field", at, "a stance stated by an agent records formed_by"))
        if props.get("stated_by") == "paper" and not props.get("source_refs"):
            problems.append(
                Problem("required-field", f"{at}.source_refs", "a stance stated by the paper needs source_refs")
            )
    if key.type == "FROM" and props.get("locators") and "material_ref" not in props:
        problems.append(Problem("locator", at, f"{ref(key.dst)} has no material"))
    return problems


def _kind(state: GraphState, node_id: str) -> str | None:
    labels = state.nodes[node_id].labels if node_id in state.nodes else frozenset()
    return kind_of(labels) or (ARTIFACT if ARTIFACT in labels else None)


__all__ = ["check_state", "touched"]
