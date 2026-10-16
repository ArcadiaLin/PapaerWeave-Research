"""AsOf：某个时刻是什么样（docs/designs/v2/versioning_interfaces.md §6）。

    AsOf(at, ids, field?, offset?, continuation?) -> graph-doc

对象在提交 ``at`` 写入后的读视图，与 Traverse（``path`` 为空）同形：字段、全部出边、别名、Artifact 的只读字段。
状态由完整状态的逆向重放求得（:meth:`graph_vc.VersionedGraph.state_at`）；只读字段都从这个状态求得，不提供
``_stale``（:mod:`paperweave.query.changes`）。那时还不存在或已被删除的对象记入 ``meta.missing``。只按 id 读取，不沿关系走。
按节点分页；``field``（与一个 id）分块读取被截短的值。
"""

from __future__ import annotations

from typing import Any

from ..operators.base import STRING, STRINGS, interface, schema
from ..query.capacity import LIMIT, field_view, paged
from ..query.changes import is_object, old_view
from ..query.versions import continue_at, id_list, pin, resume
from ..store.store import ContractError, Store


def as_of(
    store: Store,
    at: str,
    ids: list[str] | str,
    field: str | None = None,
    offset: int | None = None,
    continuation: str | None = None,
) -> dict[str, Any]:
    ids = id_list(ids, at="ids")
    if ids is None:
        raise ContractError([{"at": "ids", "msg": "required"}])
    if field is not None and len(ids) != 1:
        raise ContractError([{"at": "ids", "msg": "give exactly one id with field"}])
    resumed = resume(continuation, {"at": at})
    pinned = pin(store, resumed[1][0] if resumed else at, at="at")
    state = store.graph.state_at(pinned.commit, branch=pinned.branch)
    system = [i for i in ids if i in state.nodes and not is_object(i, state)]
    if system:
        raise ContractError([{"at": "ids", "msg": f"not objects of the graph model: {system}"}])
    present = [i for i in ids if i in state.nodes]
    missing = [{"ref": i, "missing_in": pinned.commit} for i in ids if i not in state.nodes]
    if field is not None:
        if not present:
            raise ContractError([{"at": "ids", "msg": f"{ids[0]} does not exist in {pinned.commit}"}])
        return field_view(ids[0], old_view(ids[0], state), field, offset, {"at": pinned.commit})
    start = resumed[0] if resumed else 0
    page = present[start:]

    def view(count: int) -> dict[str, Any]:
        end = start + count
        meta = {
            "at": pinned.commit,
            "returned": count,
            "requested": len(ids),
            "missing": missing,
            "continuation": continue_at(end, pinned.commit) if end < len(present) else None,
            "size": {"limit": LIMIT, "used": LIMIT},
        }
        return {"meta": meta, "nodes": {i: old_view(i, state) for i in page[:count]}}

    return paged(view, len(page), "nodes")


AS_OF = interface(
    name="as_of",
    parameters=schema(
        {
            "at": STRING,
            "ids": STRINGS,
            "field": STRING,
            "offset": {"type": "integer"},
            "continuation": STRING,
        },
        ["at", "ids"],
    ),
    run=as_of,
)


__all__ = ["AS_OF", "as_of"]
