"""从库中读出投影：取局部现状，按 :mod:`.view` 投影，补上产物的只读字段。``get``、``search``、``traverse`` 共用。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from graph_vc import GraphState

from ..model.schema import ARTIFACT, kind_of
from ..store.store import ContractError, Store
from .anchor_versions import anchor_versions
from .materials import section_finder
from .revisions import latest_revisions
from .search import Found
from .view import View, compact, edge_hit, full, label, merge_into

Extra = Mapping[str, Mapping[str, Any]]  # 节点 id → 另外读取的只读字段（如产物的 _stale）


def state_of(store: Store, ids: Iterable[str]) -> GraphState:
    return store.graph.local_state(list(dict.fromkeys(ids)))


def get_view(
    store: Store, ids: list[str], extra: Extra | None = None, window: tuple[int, int] | None = None
) -> tuple[View, list[str]]:
    """``ids`` 的全量投影；返回投影与不存在的 id。修订过的有据层记录带 ``_revised``（最近一次修订），锚点写在论文旧材料上的
    带 ``_anchor_version``。"""
    kinds = store.kinds(ids)
    missing = [i for i in ids if i not in kinds]
    system = [i for i in ids if i in kinds and kinds[i] is None]
    if system:
        raise ContractError([{"at": "ids", "msg": f"{', '.join(system)} are system records, not nodes"}])
    present = [i for i in ids if i in kinds]
    state = state_of(store, present)
    sections = section_finder(store)
    revised = latest_revisions(store, present)
    old_anchors = anchor_versions(store, present)
    view = View()
    for node_id in present:
        view.data[node_id] = full(node_id, state, view, sections, window)
        if node_id in revised:
            view.data[node_id]["_revised"] = revised[node_id]
        if node_id in old_anchors:
            view.data[node_id]["_anchor_version"] = old_anchors[node_id]
        view.data[node_id].update((extra or {}).get(node_id, {}))
    return view, missing


def compact_view(store: Store, ids: list[str], extra: Extra | None = None) -> View:
    state = state_of(store, ids)
    sections = section_finder(store)
    view = View()
    for node_id in ids:
        if node_id in state.nodes:
            view.data[node_id] = compact(node_id, state, view, sections)
            view.data[node_id].update((extra or {}).get(node_id, {}))
    return view


def search_view(store: Store, found: Found, extra: Extra | None = None) -> View:
    """检索结果：节点命中给紧凑投影；关系命中挂在起点下，只列命中的那几条关系。"""
    ids = [e.id for e in found.entries] + [k.dst for e in found.entries for k in e.edges]
    state = state_of(store, ids)
    sections = section_finder(store)
    view = View()
    for entry in found.entries:
        if entry.id not in state.nodes:
            continue
        if entry.node_hit:
            out = compact(entry.id, state, view, sections)
        else:
            node = state.nodes[entry.id]
            out = {"_type": node.props.get("op")} if ARTIFACT in node.labels else {"kind": kind_of(node.labels)}
            view.names[entry.id] = label(entry.id, state)
        if entry.match:
            out = {"_match": entry.match, **out}
        for key in entry.edges:
            if key in state.edges:
                merge_into(out, edge_hit(key, state, view, sections))
        out.update((extra or {}).get(entry.id, {}))
        view.data[entry.id] = out
    return view


__all__ = ["compact_view", "get_view", "search_view", "state_of"]
