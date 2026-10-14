"""读视图：把库中状态渲染成 graph-doc（docs/experiments/e09/operators/commit.md §6 R）。

读写同形：视图中的节点原样交回 Commit 应当是 ``noop``。为此每个节点带上它**全部**的模型出边
（graph-doc 中一个关系键列出的是该类型出边的完整集合，只列一部分交回时会删掉其余的边），
系统维护的内容按写入时的拼写还原：

- Label → ``kind``；指向它的 NameKey → ``aliases``（不含与 ``name`` 规范化后相同的键）；
- Paper 的 Material → ``material``（路径）与只读的 ``_material``；
- 边上的 ``material_ref`` 等系统属性不出现，``FROM`` 的材料以只读的 ``_material`` 给出；
- 自然键（``exp_key``、``content_key``）与检索用的派生属性不出现。

入边不出现在节点上；需要时经 Traverse 沿入边走到对方节点，对方节点的出边里就有这条边。

Artifact 只经 ``CheckIn`` 写入（库中可能还有已下线的旧版 Agent 算子写的，带 ``_params``），视图中的字段全部
只读（以 ``_`` 开头）：``_op``、``_title``、``_abs``、形成信息、``_material`` 与 ``_document``（文档）、``_stale``
（可能过期的原因，见 :mod:`e09.artifact.stale`）、``_USED``（用到的对象）。原样交回 Commit 时被忽略。
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

from graph_vc import EdgeKey, GraphState

from ..model.namekey import normalize
from ..model.schema import (
    ARTIFACT,
    NAMED,
    RELATIONSHIPS,
    STANCE_RELS,
    SYSTEM_FIELDS,
    SYSTEM_REL_PROPS,
    TRAVERSABLE,
    kind_of,
)
from ..yamlfmt import dump

VERSION = "v0.1"

# 属性的显示顺序；其余属性（开放 kind 的额外字段）按字母序排在后面
_PROP_ORDER = (
    "stub",
    "name",
    "aliases",
    "identifiers",
    "year",
    "material",
    "definition",
    "description",
    "text",
    "anchors",
    "stated_by",
    "note",
)


# ── 只读字段：由库中状态算出，写入时也用来核对交回的只读字段，保证读写一致 ──────────────


def material_of(node_id: str, state: GraphState) -> str | None:
    """节点（Paper 或 Artifact）当前的材料 id：经 ``MATERIAL_OF`` 指向它、且没有被新版本取代（``superseded_by``）的
    Material。"""
    owners = sorted(
        k.src
        for k in state.edges
        if k.dst == node_id
        and k.type == "MATERIAL_OF"
        and not (k.src in state.nodes and state.nodes[k.src].props.get("superseded_by"))
    )
    return owners[0] if owners else None


def node_readonly(node_id: str, state: GraphState) -> dict[str, Any]:
    """节点的只读字段：``_material``（有材料的节点）、``_formed_by``、``_formed_at``（Agent 形成的记录）。"""
    node = state.nodes[node_id]
    view: dict[str, Any] = {}
    material = material_of(node_id, state)
    if material is not None:
        view["_material"] = material
    for key in ("formed_by", "formed_at"):
        if key in node.props:
            view[f"_{key}"] = node.props[key]
    return view


def edge_readonly(rel_type: str, props: dict[str, Any]) -> dict[str, Any]:
    """关系的只读字段：``FROM`` 的 ``_material``，Agent 判断的正反关系的 ``_formed_by``、``_formed_at``。"""
    view: dict[str, Any] = {}
    if rel_type == "FROM" and "material_ref" in props:
        view["_material"] = props["material_ref"]
    if rel_type in STANCE_RELS:
        for key in ("formed_by", "formed_at"):
            if key in props:
                view[f"_{key}"] = props[key]
    return view


# ── 读视图 ──────────────────────────────────────────────────────────────


def render(
    state: GraphState,
    ids: Iterable[str],
    meta: dict[str, Any],
    extra: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """``ids`` 中节点的读视图。``state`` 须包含这些节点的全部关系及关系另一端的节点（``local_state``）；
    ``extra`` 是需要另外读取的只读字段（Artifact 的 ``_document`` 与 ``_stale``，有据层记录的 ``_revised``），
    按节点 id 给出。"""
    out_edges = _out_edges(state)
    extra = extra or {}
    nodes = {}
    for node_id in dict.fromkeys(ids):
        if ARTIFACT in state.nodes[node_id].labels:
            nodes[node_id] = artifact_view(node_id, state, extra.get(node_id))
        else:
            nodes[node_id] = node_view(node_id, state, out_edges.get(node_id, []))
            nodes[node_id].update(extra.get(node_id) or {})
    return {"graph-doc": VERSION, "meta": meta, "nodes": nodes}


def artifact_view(node_id: str, state: GraphState, extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    props = state.nodes[node_id].props
    view: dict[str, Any] = {f"_{k}": props[k] for k in ("op", "title", "abs") if k in props}
    if isinstance(props.get("params"), str):
        view["_params"] = json.loads(props["params"])
    view.update((f"_{k}", props[k]) for k in ("formed_by", "formed_at", "session") if k in props)
    material = material_of(node_id, state)
    if material is not None:
        view["_material"] = material
    view.update(extra or {})
    used = sorted((k for k in state.edges if k.src == node_id and k.type == "USED"), key=_order)
    if used:
        view["_USED"] = [edge_view(k, state.edges[k]) for k in used]
    return view


def node_view(node_id: str, state: GraphState, out_edges: list[EdgeKey] | None = None) -> dict[str, Any]:
    node = state.nodes[node_id]
    kind = kind_of(node.labels)
    if kind is None:
        raise ValueError(f"{node_id} is not an object of the graph model")
    props = {k: v for k, v in node.props.items() if k not in SYSTEM_FIELDS}
    if kind in NAMED:
        props["aliases"] = aliases_of(node_id, state)
    material = material_of(node_id, state)
    if material is not None:
        props["material"] = state.nodes[material].props["path"]

    view: dict[str, Any] = {"kind": kind}
    view.update((k, props.pop(k)) for k in _PROP_ORDER if k in props)
    view.update(sorted(props.items()))
    view.update(node_readonly(node_id, state))

    if out_edges is None:
        out_edges = [k for k in state.edges if k.src == node_id]
    by_type: dict[str, list[EdgeKey]] = defaultdict(list)
    for key in out_edges:
        if key.type in RELATIONSHIPS:
            by_type[key.type].append(key)
    for rel_type in RELATIONSHIPS:  # 按图模型中的顺序
        if rel_type in by_type:
            view[rel_type] = [edge_view(key, state.edges[key]) for key in sorted(by_type[rel_type], key=_order)]
    return view


def edge_view(key: EdgeKey, props: dict[str, Any]) -> str | dict[str, Any]:
    """没有属性的边写成终点 id，否则写成 ``{to, <属性>…, <只读字段>…}``。"""
    shown = {k: v for k, v in props.items() if k not in SYSTEM_REL_PROPS}
    shown.update(edge_readonly(key.type, props))
    if key.type == "USED" and "material_ref" in props:
        shown["_material"] = props["material_ref"]
    return {"to": key.dst, **shown} if shown else key.dst


def aliases_of(node_id: str, state: GraphState) -> list[str]:
    """指向节点的 NameKey 中，除名称本身以外的写法；按键排序（与写入时比对名称的顺序相同）。"""
    name = state.nodes[node_id].props.get("name")
    keys = sorted(k.src for k in state.edges if k.dst == node_id and k.type == "NAMES")
    raws = [state.nodes[k].props.get("raw") for k in keys if k in state.nodes]
    return [raw for raw in raws if isinstance(raw, str) and normalize(raw) != normalize(name or "")]


def source_refs_of(node_id: str, state: GraphState) -> list[str]:
    """节点出边上的来源引用（按图模型中的关系顺序）：``FROM``、``USED`` 的每个定位拼上材料 id，以及边上的
    ``source_refs``。"""
    refs: list[str] = []
    rank = {rel_type: i for i, rel_type in enumerate(TRAVERSABLE)}
    edges = [k for k in state.edges if k.src == node_id and k.type in TRAVERSABLE]
    for key in sorted(edges, key=lambda k: (rank[k.type], k.dst)):
        props = state.edges[key]
        material = props.get("material_ref")
        if key.type in ("FROM", "USED") and isinstance(material, str):
            refs += [f"{material}::{locator}" for locator in props.get("locators") or []]
        refs += list(props.get("source_refs") or [])
    return refs


def _order(key: EdgeKey) -> tuple[str, str, str]:
    return key.src, key.type, key.dst


def _out_edges(state: GraphState) -> dict[str, list[EdgeKey]]:
    out: dict[str, list[EdgeKey]] = defaultdict(list)
    for key in state.edges:
        out[key.src].append(key)
    return out


__all__ = [
    "VERSION",
    "aliases_of",
    "artifact_view",
    "dump",
    "edge_readonly",
    "edge_view",
    "material_of",
    "node_readonly",
    "node_view",
    "render",
    "source_refs_of",
]
