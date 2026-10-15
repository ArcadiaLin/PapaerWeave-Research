"""旧状态的读视图与变更视图（docs/designs/v2/versioning_interfaces.md §2.3、§6.2）。

**旧视图。** 由某个状态（:meth:`graph_vc.VersionedGraph.state_at`）渲染，与 :mod:`paperweave.query.view` 的读视图同形；
只读字段都从这个状态求得：别名、材料、Artifact 的 ``_document``（文档路径）。``_stale`` 是相对当前状态的判断，
不提供。

**变更视图。** 比较一个对象在两个状态中的读视图，逐节点给出：

    {id, kind, op, fields?: {字段: [改前, 改后]}, edges?: {added, removed, changed}}

``op`` 为 ``create``、``update``、``delete``，或 ``edges``（字段没变，只有出边变了）。字段与关系的拼写与读视图
相同，所以别名（``NAMES``）的变化显示为 ``aliases`` 的变化，材料（``MATERIAL_OF``）的变化显示为 ``material``
（Artifact 为 ``_document``）的变化。关系挂在起点一侧；Artifact 的 ``_USED`` 按关系比较。
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from typing import Any

from graph_vc import GraphState

from ..model.schema import ARTIFACT, PREFIX, RELATIONSHIPS, kind_of
from .view import artifact_view, material_of, node_view

USED = "_USED"
PREVIEW = 20  # 摘要中列表的预览项数
_OBJECT_ID = re.compile(rf"^({'|'.join(sorted({*PREFIX.values(), 'art'}))})_\d+$")


def is_object(node_id: str, state: GraphState) -> bool:
    """图模型中的对象或 Artifact（不是 NameKey、Material 这类系统节点）。"""
    labels = state.nodes[node_id].labels
    return kind_of(labels) is not None or ARTIFACT in labels


def object_ids(ids: Iterable[str]) -> list[str]:
    """其中图模型对象与 Artifact 的 id（按 id 的写法判断，已删除的也算）；NameKey、Material 这类系统节点不在内，
    它们的变化显示在所属对象的 ``aliases`` 与 ``material`` 上。"""
    return [i for i in ids if _OBJECT_ID.match(i)]


def old_view(node_id: str, state: GraphState) -> dict[str, Any]:
    """对象在 ``state`` 中的读视图；Artifact 的 ``_document`` 由该状态中的材料求得，不带 ``_stale``。"""
    if ARTIFACT not in state.nodes[node_id].labels:
        return node_view(node_id, state)
    material = material_of(node_id, state)
    document = state.nodes[material].props.get("path") if material is not None else None
    return artifact_view(node_id, state, {"_document": document})


def affected(ids: Iterable[str], *states: GraphState) -> list[str]:
    """候选节点（提交的 ``touched`` 与 ``removed``）对应的对象：系统节点换成它在各状态中经 ``NAMES``、
    ``MATERIAL_OF`` 所指的对象；按 id 排序。"""
    out: set[str] = set()
    for node_id in ids:
        for state in states:
            if node_id not in state.nodes:
                continue
            if is_object(node_id, state):
                out.add(node_id)
            else:
                out |= {k.dst for k in state.edges if k.src == node_id and k.type in ("NAMES", "MATERIAL_OF")}
    return sorted(i for i in out if any(i in s.nodes and is_object(i, s) for s in states))


def change(node_id: str, before: GraphState, after: GraphState) -> dict[str, Any] | None:
    """对象从 ``before`` 到 ``after`` 的变更视图；没有变化时为 ``None``。"""
    old = old_view(node_id, before) if node_id in before.nodes else None
    new = old_view(node_id, after) if node_id in after.nodes else None
    if old == new:
        return None
    old_fields, old_edges = _split(old or {})
    new_fields, new_edges = _split(new or {})
    fields = {
        k: [old_fields.get(k), new_fields.get(k)]
        for k in dict.fromkeys([*old_fields, *new_fields])
        if old_fields.get(k) != new_fields.get(k) and (k != "kind" or (old and new))  # 新建与删除时 kind 在外层
    }
    edges = _edge_changes(old_edges, new_edges)
    op = "create" if old is None else "delete" if new is None else "update" if fields else "edges"
    out: dict[str, Any] = {"id": node_id, "kind": _kind(new or old or {}), "op": op}
    if fields:
        out["fields"] = fields
    if edges:
        out["edges"] = edges
    return out


def changes(ids: Iterable[str], before: GraphState, after: GraphState) -> list[dict[str, Any]]:
    """``ids`` 中有变化的对象的变更视图，按 id 排序。"""
    return [c for i in affected(ids, before, after) if (c := change(i, before, after)) is not None]


def summary(views: list[dict[str, Any]]) -> dict[str, Any]:
    """变更视图的摘要：按 kind 与 ``op`` 计数，以及对象 id 的预览（前 :data:`PREVIEW` 个）与总数。"""
    counts: dict[str, Counter[str]] = {}
    for view in views:
        counts.setdefault(view["kind"], Counter())[view["op"]] += 1
    out: dict[str, Any] = {"counts": {k: dict(sorted(c.items())) for k, c in sorted(counts.items())}}
    out.update(preview("ids", [v["id"] for v in views]))
    return out


def preview(name: str, items: list[Any]) -> dict[str, Any]:
    """``{name: 前 PREVIEW 项}``，多于此时另给 ``<name>_total``。"""
    out: dict[str, Any] = {name: items[:PREVIEW]}
    if len(items) > PREVIEW:
        out[f"{name}_total"] = len(items)
    return out


# ── 内部 ──────────────────────────────────────────────────────────────


def _split(view: dict[str, Any]) -> tuple[dict[str, Any], dict[tuple[str, str], dict[str, Any]]]:
    """读视图分成字段与出边 ``{(关系, 终点): 边上的字段}``。"""
    fields: dict[str, Any] = {}
    edges: dict[tuple[str, str], dict[str, Any]] = {}
    for key, value in view.items():
        if key in RELATIONSHIPS or key == USED:
            for entry in value:
                to, props = (entry, {}) if isinstance(entry, str) else (entry["to"], _without(entry, "to"))
                edges[(key, to)] = props
        else:
            fields[key] = value
    return fields, edges


def _edge_changes(
    old: dict[tuple[str, str], dict[str, Any]], new: dict[tuple[str, str], dict[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    added = [{"rel": r, "to": t, **new[(r, t)]} for r, t in new if (r, t) not in old]
    removed = [{"rel": r, "to": t, **old[(r, t)]} for r, t in old if (r, t) not in new]
    changed = []
    for key in old.keys() & new.keys():
        before, after = old[key], new[key]
        if before != after:
            diff = {k: [before.get(k), after.get(k)] for k in dict.fromkeys([*before, *after])}
            changed.append({"rel": key[0], "to": key[1], "fields": {k: v for k, v in diff.items() if v[0] != v[1]}})
    out = {"added": added, "removed": removed, "changed": sorted(changed, key=lambda e: (e["rel"], e["to"]))}
    return {k: v for k, v in out.items() if v}


def _kind(view: dict[str, Any]) -> str:
    return view.get("kind") or ARTIFACT


def _without(entry: dict[str, Any], key: str) -> dict[str, Any]:
    return {k: v for k, v in entry.items() if k != key}


__all__ = ["affected", "change", "changes", "is_object", "object_ids", "old_view", "preview", "summary"]
