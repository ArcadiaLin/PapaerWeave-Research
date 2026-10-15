"""Diff：两个状态之间变了什么（docs/designs/v2/versioning_interfaces.md §5）。

    Diff(from, to="main", node?, field?, offset?, continuation?) -> {summary, changes, meta}

净差异：只比较两端的状态，中间改了又改回的不出现。``from`` 须是 ``to`` 所在分支上不晚于 ``to`` 的提交。比较只在
``(from, to]`` 之间各提交触及与删除的节点上进行，两端的状态由完整状态的逆向重放求得
（:meth:`graph_vc.VersionedGraph.state_at`）。先给摘要（按 kind 与操作计数、对象 id 的预览），再按节点分页给变更视图。
"""

from __future__ import annotations

from typing import Any

from ..operators.base import STRING, STRINGS, interface, schema
from ..query.capacity import field_view, paged
from ..query.changes import changes, summary
from ..query.excerpts import LIMIT
from ..query.versions import continue_at, id_list, pin, resume
from ..store.store import ContractError, Store


def diff(
    store: Store,
    from_: str,
    to: str = "main",
    node: list[str] | str | None = None,
    field: str | None = None,
    offset: int | None = None,
    continuation: str | None = None,
) -> dict[str, Any]:
    resumed = resume(continuation, {"from": from_, "to": to}, pins=2)
    old = pin(store, resumed[1][0] if resumed else from_, at="from")
    new = pin(store, resumed[1][1] if resumed else to, at="to")
    seqs = {r.id: r.seq for r in new.history}
    if old.commit not in seqs:
        raise ContractError([{"at": "from", "msg": f"{old.commit} is not {new.commit} or one of its ancestors"}])
    nodes = id_list(node, at="node")
    if field is not None and (nodes is None or len(nodes) != 1):
        raise ContractError([{"at": "node", "msg": "give exactly one node with field"}])
    between = [r for r in new.history if r.seq > seqs[old.commit]]
    candidates = {i for r in between for i in (*r.touched, *r.removed)}
    if nodes is not None:
        candidates &= set(nodes)
    before = store.graph.state_at(old.commit, branch=old.branch)
    after = store.graph.state_at(new.commit, branch=new.branch)
    views = changes(candidates, before, after)
    pins = {"from": old.commit, "to": new.commit}
    if field is not None:
        if not views:
            raise ContractError([{"at": "node", "msg": f"{nodes[0]} did not change between {old.commit} and {new.commit}"}])
        return field_view(views[0]["id"], views[0], field, offset, pins)
    start = resumed[0] if resumed else 0
    page = views[start:]
    head = {"commits": len(between), **summary(views)}

    def view(count: int) -> dict[str, Any]:
        end = start + count
        meta = {
            **pins,
            "returned": count,
            "matched": len(views),
            "continuation": continue_at(end, old.commit, new.commit) if end < len(views) else None,
            "size": {"limit": LIMIT, "used": LIMIT},
        }
        return {"summary": head, "changes": page[:count], "meta": meta}

    return paged(view, len(page), "changes")


def _run(store: Store, **params: Any) -> dict[str, Any]:
    """``from`` 是 Python 的保留字，参数改名后交给 :func:`diff`。"""
    if "from" in params:
        params["from_"] = params.pop("from")
    return diff(store, **params)


DIFF = interface(
    name="Diff",
    parameters=schema(
        {
            "from": STRING,
            "to": STRING,
            "node": STRINGS,
            "field": STRING,
            "offset": {"type": "integer"},
            "continuation": STRING,
        },
        ["from"],
    ),
    run=_run,
)


__all__ = ["DIFF", "diff"]
