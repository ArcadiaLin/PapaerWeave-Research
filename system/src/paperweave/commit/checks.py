"""写入后状态的检查：在“应用变更集之后”的局部状态上核对模型规则。

检查范围是本次触及的节点：新建或修改的节点、增删改过关系的端点。它们的全部关系都在局部状态中，所以删掉一条边后，
起点是否还有必需的边也能核对。
"""

from __future__ import annotations

from collections.abc import Callable

from graph_vc import Changeset, EdgeKey, GraphState

from ..model.schema import (
    ARTIFACT,
    CONTENT,
    FROM,
    RELATIONSHIPS,
    REQUIRED_FIELDS,
    REQUIRED_RELS,
    SYSTEM_RELS,
    kind_of,
    labels_of,
)
from .problems import Problem

# RELATES_TO 的端点恰好符合某个具名类型时提示（data_model.md：写法 / RELATES_TO）
_NAMED_FOR = {
    rel_type: spec.ends for rel_type, spec in RELATIONSHIPS.items() if rel_type != "RELATES_TO"
}


def touched(changeset: Changeset) -> set[str]:
    """本次新建、修改的节点，以及增删改过关系的端点；不含删除的节点。"""
    deleted = {n.id for n in changeset.nodes if n.op == "delete"}
    ids = {n.id for n in changeset.nodes} | {end for e in changeset.edges for end in (e.key.src, e.key.dst)}
    return ids - deleted


def check_state(after: GraphState, ids: set[str], ref: Callable[[str], str] = str) -> list[Problem]:
    """核对 ``ids`` 中证据节点在 ``after`` 中的字段、必需关系，以及从它们出发的关系。"""
    problems: list[Problem] = []
    edges: set[EdgeKey] = set()
    for node_id in sorted(ids):
        node = after.nodes.get(node_id)
        kind = kind_of(node.labels) if node is not None else None
        if node is None or kind is None:
            continue
        edges |= {k for k in after.incident(node_id) if k.src == node_id}
        at = ref(node_id)
        if node.labels != labels_of(kind):
            problems.append(Problem("labels", at, f"expected labels {sorted(labels_of(kind))}, got {sorted(node.labels)}"))

        stub = node.props.get("stub") is True
        required = {"name"} if stub else set(REQUIRED_FIELDS[kind])
        if kind in CONTENT:
            required.discard("paper")  # paper 存为 FROM 边，下面另查
        for name in sorted(required - node.props.keys()):
            problems.append(Problem("required-field", f"{at}.{name}", f"a {kind} requires {name}"))

        outgoing = [k for k in after.edges if k.src == node_id]
        if kind in CONTENT:
            papers = [k for k in outgoing if k.type == FROM]
            if not papers:
                problems.append(Problem("required-field", f"{at}.paper", f"a {kind} requires paper"))
            elif len(papers) > 1:
                problems.append(Problem("field", f"{at}.paper", f"a {kind} comes from exactly one paper"))
        types = {k.type for k in outgoing}
        for rel_type in REQUIRED_RELS.get(kind, ()):
            if rel_type not in types and not stub:
                problems.append(Problem("required-edge", f"{at}.{rel_type}", f"a {kind} requires at least one {rel_type}"))

    for key in sorted(edges, key=str):
        problems += _check_edge(after, key, ref)
    return problems


def _check_edge(state: GraphState, key: EdgeKey, ref: Callable[[str], str]) -> list[Problem]:
    at = f"{ref(key.src)}.{key.type}.{ref(key.dst)}"
    if key.type in SYSTEM_RELS:
        return []
    spec = RELATIONSHIPS.get(key.type)
    if spec is None:
        return [Problem("relationship", at, f"{key.type} is not a relationship type")]
    src, dst = _kind(state, key.src), _kind(state, key.dst)
    problems = []
    if not any(src in srcs and dst in dsts for srcs, dsts in spec.ends):
        problems.append(Problem("endpoint", at, f"{key.type} cannot go from a {src} to a {dst}{_alternatives(src, dst)}"))
    elif spec.same_kind and src != dst:
        problems.append(Problem("endpoint", at, f"{key.type} connects two nodes of the same kind ({src} ≠ {dst})"))
    props = state.edges[key]
    for name in sorted(spec.required - props.keys()):
        problems.append(Problem("required-field", f"{at}.{name}", f"{key.type} requires {name}"))
    if key.type == "RELATES_TO":
        fits = [t for t, ends in _NAMED_FOR.items() if any(src in s and dst in d for s, d in ends)]
        if fits:
            msg = f"a {src} → {dst} relation may be {' or '.join(fits)}; use RELATES_TO only when none of them fits"
            problems.append(Problem("relationship", at, msg, "warning"))
    return problems


def _alternatives(src: str | None, dst: str | None) -> str:
    fits = [t for t, spec in RELATIONSHIPS.items() if any(src in s and dst in d for s, d in spec.ends)]
    return f"; types from {src} to {dst}: {', '.join(fits)}" if fits else ""


def _kind(state: GraphState, node_id: str) -> str | None:
    labels = state.nodes[node_id].labels if node_id in state.nodes else frozenset()
    return kind_of(labels) or (ARTIFACT if ARTIFACT in labels else None)


__all__ = ["check_state", "touched"]
