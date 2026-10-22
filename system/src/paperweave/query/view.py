"""读取投影：把库中状态写成 graph-doc 同形的节点（docs/designs/v3/tools.md）。

**读写同形。** ``get`` 返回的节点就是 ``set`` 下的一个节点：原样贴进 ``set`` 没有改动，改其中几个值就是修改。
为此系统维护的内容按写入时的拼写还原：Label → ``kind``，NameKey → ``alias``，``FROM`` → ``paper``，``extra`` 的
JSON → 映射；系统字段与检索用的派生字段不出现。

**只读字段**（``_`` 开头，写入时忽略）：``_formed_by``、``_formed_at``、``_edges_in``（各类入边的条数）、Claim 的
``_supported_by`` 与 ``_opposed_by``、``_used_by``（用到它的产物）。检索结果中的描述摘录叫 ``_excerpt``，不叫
``description``：误贴回 ``set`` 也不会把描述改成截断的半句。

**两种投影。** :func:`full` 给出节点的全部字段与全部出边（``get``）。:func:`compact` 按 kind 只给辨认它所需的部分
（``search``、``traverse``）：有名称的节点给名称与入边计数；Experiment 给每类参与关系的前几个；Claim 给支持与反对它的
证据；产物给类型、标题与摘要。截掉的条数在 ``_more`` 中。

**注释。** id 的名称、锚点的章节写在行末注释里（:mod:`paperweave.query.render`），不进数据。
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from graph_vc import EdgeKey, GraphState, NodeState

from ..model.namekey import normalize
from ..model.schema import (
    ARTIFACT,
    CONTENT,
    DERIVED_FIELDS,
    FROM,
    RELATIONSHIPS,
    SYSTEM_FIELDS,
    SYSTEM_REL_PROPS,
    USED,
    kind_of,
)
from .render import render

EXCERPT = 280  # 摘录的字数上限
PARTICIPANTS = 4  # 紧凑投影中每类关系最多列出的终点
USED_BY = 3
_ORDER = ("kind", "name", "alias", "identities", "year", "source", "paper", "anchor", "figures", "description", "extra", "stub")
_HIDDEN_EDGE = SYSTEM_REL_PROPS | DERIVED_FIELDS | {"search_text"}

Sections = Callable[[list[str]], list[str]]  # 锚点 → 所在的章节


@dataclass
class View:
    """一组投影与渲染它们所需的注释。``data`` 按给出的顺序。"""

    data: dict[str, Any] = field(default_factory=dict)
    names: dict[str, str] = field(default_factory=dict)
    notes: dict[tuple, str] = field(default_factory=dict)
    edge_totals: dict[str, dict[str, int]] = field(default_factory=dict)  # 分页时：节点 → 超出一页的关系 → 总条数

    def subset(self, ids: Iterable[str]) -> View:
        """只含 ``ids`` 的投影（按预算截短时用）；注释与总条数照搬，渲染时只用到数据中出现的。"""
        keep = list(ids)
        totals = {i: t for i, t in self.edge_totals.items() if i in keep}
        return View({i: self.data[i] for i in keep}, self.names, self.notes, totals)

    def text(self, header: Iterable[str] = ()) -> str:
        lines = "".join(f"# {line}\n" for line in header)
        return lines + (render(self.data, self.names, self.notes) if self.data else "")


def label(node_id: str, state: GraphState) -> str:
    """注释中的名称：有名称的用名称，产物用标题，其余是“kind: 描述的开头”。"""
    node = state.nodes.get(node_id)
    if node is None:
        return node_id
    props = node.props
    if props.get("name"):
        return str(props["name"])
    if ARTIFACT in node.labels:
        return f"{props.get('op', 'Artifact')}: {props.get('title', '')}"
    kind = kind_of(node.labels) or "?"
    words = str(props.get("description", "")).split()
    return f"{kind}: {' '.join(words[:10])}{' …' if len(words) > 10 else ''}"


def excerpt(text: Any, limit: int = EXCERPT) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + " …"


# ── 全量投影（get）────────────────────────────────────────────────────


def full(
    node_id: str,
    state: GraphState,
    view: View,
    sections: Sections | None = None,
    window: tuple[int, int] | None = None,
) -> dict[str, Any]:
    """全部字段与出边。``window`` 为 ``(offset, limit)`` 时，每种出边按终点 id 只列这一段，总数记在
    ``view.edge_totals``（``get`` 分页；``checkout`` 不分页）。"""
    node = state.nodes[node_id]
    if ARTIFACT in node.labels:
        out = artifact(node_id, state, view, full_abs=True)
        if uses := _uses(node_id, state, view, window):
            out["_uses"] = uses
        return out
    kind = kind_of(node.labels)
    if kind is None:
        raise ValueError(f"{node_id} is not an evidence node")
    out = _fields(node_id, node, kind, state, view, sections)
    for rel_type in RELATIONSHIPS:
        edges = _out(state, node_id, rel_type)
        if window is not None:
            offset, limit = window
            if offset or len(edges) > limit:
                view.edge_totals.setdefault(node_id, {})[rel_type] = len(edges)
            edges = edges[offset : offset + limit]
        if edges:
            out[rel_type] = {}
            for key in edges:
                out[rel_type][key.dst] = _edge_props(key, state, view, sections, node_id)
                view.names[key.dst] = label(key.dst, state)
    out.update(_readonly(node_id, node, kind, state, view, limit=None))
    return out


def _fields(
    node_id: str, node: NodeState, kind: str, state: GraphState, view: View, sections: Sections | None
) -> dict[str, Any]:
    props = {k: v for k, v in node.props.items() if k not in SYSTEM_FIELDS and k != "search_text"}
    if "extra" in props:
        props["extra"] = json.loads(props["extra"]) if isinstance(props["extra"], str) else props["extra"]
    alias = aliases_of(node_id, state)
    if alias:
        props["alias"] = alias
    if kind in CONTENT:
        source = _paper_edge(node_id, state)
        if source is not None:
            props["paper"] = source.dst
            view.names[source.dst] = label(source.dst, state)
        anchors = props.get("anchor") or []
        if sections and anchors:
            found = sections(anchors)
            if found:
                view.notes[(node_id, "anchor")] = "; ".join(found)
    out: dict[str, Any] = {"kind": kind}
    out.update((k, props.pop(k)) for k in _ORDER if k in props)
    out.update(sorted(props.items()))
    return out


def _edge_props(
    key: EdgeKey, state: GraphState, view: View, sections: Sections | None, src: str
) -> dict[str, Any] | None:
    props = {k: v for k, v in state.edges[key].items() if k not in _HIDDEN_EDGE}
    if isinstance(props.get("extra"), str):
        props["extra"] = json.loads(props["extra"])
    if sections and props.get("anchor"):
        found = sections(props["anchor"])
        if found:
            view.notes[(src, key.type, key.dst, "anchor")] = "; ".join(found)
    return props or None


def _readonly(
    node_id: str, node: NodeState, kind: str, state: GraphState, view: View, limit: int | None
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in ("formed_by", "formed_at"):
        if key in node.props and limit is None:
            out[f"_{key}"] = node.props[key]
    incoming = [k for k in state.edges if k.dst == node_id and k.type in RELATIONSHIPS]
    if kind == "Claim":
        for rel_type, field_name in (("SUPPORTS", "_supported_by"), ("OPPOSES", "_opposed_by")):
            ids = sorted(k.src for k in incoming if k.type == rel_type)
            if ids:
                out[field_name] = ids[:limit] if limit else ids
                view.names.update((i, label(i, state)) for i in out[field_name])
                if limit and len(ids) > limit:
                    out.setdefault("_more", {})[field_name] = len(ids) - limit
        incoming = [k for k in incoming if k.type not in ("SUPPORTS", "OPPOSES")]
    counts = Counter(k.type for k in incoming)
    if counts:
        out["_edges_in"] = dict(sorted(counts.items()))
    used = sorted({k.src for k in state.edges if k.dst == node_id and k.type == USED})
    if used:
        shown = used[:USED_BY] if limit else used
        out["_used_by"] = shown
        view.names.update((i, label(i, state)) for i in shown)
        if len(used) > len(shown):
            out.setdefault("_more", {})["_used_by"] = len(used) - len(shown)
    return out


# ── 紧凑投影（search、traverse）──────────────────────────────────────


def compact(node_id: str, state: GraphState, view: View, sections: Sections | None = None) -> dict[str, Any]:
    node = state.nodes[node_id]
    if ARTIFACT in node.labels:
        return artifact(node_id, state, view)
    kind = kind_of(node.labels)
    if kind is None:
        raise ValueError(f"{node_id} is not an evidence node")
    out: dict[str, Any] = {"kind": kind}
    props = node.props
    view.names[node_id] = label(node_id, state)
    if kind in CONTENT:
        source = _paper_edge(node_id, state)
        if source is not None:
            out["paper"] = source.dst
            view.names[source.dst] = label(source.dst, state)
        if props.get("anchor"):
            out["anchor"] = props["anchor"]
            if sections:
                found = sections(props["anchor"])
                if found:
                    view.notes[(node_id, "anchor")] = "; ".join(found)
    else:
        out["name"] = props.get("name")
        alias = aliases_of(node_id, state)
        if alias:
            out["alias"] = alias
        if kind == "Paper":
            out.update((k, props[k]) for k in ("identities", "year", "source") if k in props)
        if props.get("stub"):
            out["stub"] = True
    if props.get("description"):
        out["_excerpt"] = excerpt(props["description"])
    shown = {"Experiment": ("EVALUATES", "USES", "ON_TASK"), "Contribution": ("ABOUT",), "Claim": ("ABOUT",)}
    for rel_type in shown.get(kind, ()):
        edges = _out(state, node_id, rel_type)
        if not edges:
            continue
        out[rel_type] = {}
        for key in edges[:PARTICIPANTS]:
            props_ = {k: v for k, v in state.edges[key].items() if k in ("role", "result")}
            out[rel_type][key.dst] = props_ or None
            view.names[key.dst] = label(key.dst, state)
        if len(edges) > PARTICIPANTS:
            out.setdefault("_more", {})[rel_type] = len(edges) - PARTICIPANTS
    out.update(_readonly(node_id, node, kind, state, view, limit=PARTICIPANTS))
    return out


def artifact(node_id: str, state: GraphState, view: View, *, full_abs: bool = False) -> dict[str, Any]:
    props = state.nodes[node_id].props
    view.names[node_id] = label(node_id, state)
    out: dict[str, Any] = {"_type": props.get("op"), "_title": props.get("title")}
    if props.get("abs"):
        out["_abs" if full_abs else "_excerpt"] = props["abs"] if full_abs else excerpt(props["abs"])
    for key in ("formed_by", "formed_at"):
        if key in props and full_abs:
            out[f"_{key}"] = props[key]
    used = [k for k in state.edges if k.src == node_id and k.type == USED]
    if used:
        out["_uses"] = len(used)
    return out


def _uses(node_id: str, state: GraphState, view: View, window: tuple[int, int] | None) -> dict[str, list[str]]:
    """产物用到的节点（``USED`` 边），按在文档中的位置（``role``，如 method、paper、dataset）分组、按 id 排序；与节点的
    出边一样按 ``window`` 分页，总数记为 ``_uses.<role>``。"""
    groups: dict[str, list[str]] = defaultdict(list)
    for key in sorted((k for k in state.edges if k.src == node_id and k.type == USED), key=lambda k: k.dst):
        roles = state.edges[key].get("role") or ["other"]
        for role in [roles] if isinstance(roles, str) else roles:
            groups[role].append(key.dst)
    out: dict[str, list[str]] = {}
    for role in sorted(groups):
        ids = groups[role]
        if window is not None:
            offset, limit = window
            if offset or len(ids) > limit:
                view.edge_totals.setdefault(node_id, {})[f"_uses.{role}"] = len(ids)
            ids = ids[offset : offset + limit]
        if ids:
            out[role] = ids
            view.names.update((i, label(i, state)) for i in ids)
    return out


def edge_hit(key: EdgeKey, state: GraphState, view: View, sections: Sections | None = None) -> dict[str, Any]:
    """一条命中的关系：``{<关系类型>: {<终点>: <边属性>}}``，挂在起点的投影下。"""
    view.names[key.src] = label(key.src, state)
    view.names[key.dst] = label(key.dst, state)
    return {key.type: {key.dst: _edge_props(key, state, view, sections, key.src)}}


# ── 共用 ──────────────────────────────────────────────────────────────


def aliases_of(node_id: str, state: GraphState) -> list[str]:
    """指向节点的 NameKey 中，除名称本身以外的写法；按键排序（与写入时比对名称的顺序相同）。"""
    name = state.nodes[node_id].props.get("name")
    keys = sorted(k.src for k in state.edges if k.dst == node_id and k.type == "NAMES")
    raws = [state.nodes[k].props.get("raw") for k in keys if k in state.nodes]
    return [raw for raw in raws if isinstance(raw, str) and normalize(raw) != normalize(name or "")]


def current_material(node_id: str, state: GraphState) -> str | None:
    """产物当前的文档：经 ``MATERIAL_OF`` 指向它、没有被新版本取代的 Material。"""
    owners = sorted(
        k.src
        for k in state.edges
        if k.dst == node_id
        and k.type == "MATERIAL_OF"
        and not (k.src in state.nodes and state.nodes[k.src].props.get("superseded_by"))
    )
    return owners[0] if owners else None


def _paper_edge(node_id: str, state: GraphState) -> EdgeKey | None:
    edges = sorted(k for k in state.edges if k.src == node_id and k.type == FROM)
    return edges[0] if edges else None


def _out(state: GraphState, node_id: str, rel_type: str) -> list[EdgeKey]:
    return sorted((k for k in state.edges if k.src == node_id and k.type == rel_type), key=lambda k: k.dst)


def by_source(keys: Iterable[EdgeKey]) -> dict[str, list[EdgeKey]]:
    out: dict[str, list[EdgeKey]] = defaultdict(list)
    for key in keys:
        out[key.src].append(key)
    return out


def merge_into(target: dict[str, Any], addition: Mapping[str, Any]) -> None:
    """把一条命中的关系并进起点的投影：同类关系的终点合在一起。"""
    for rel_type, edges in addition.items():
        target.setdefault(rel_type, {})
        if isinstance(target[rel_type], dict):
            target[rel_type].update(edges)


__all__ = [
    "EXCERPT",
    "View",
    "aliases_of",
    "artifact",
    "by_source",
    "compact",
    "current_material",
    "edge_hit",
    "excerpt",
    "full",
    "label",
    "merge_into",
]
