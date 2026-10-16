"""get：按 id 读出节点的全部字段与出边（docs/designs/v3/tools.md）。

    get(ids) -> 带注释的 YAML：id → 节点，形状与 commit 中 set 下的节点相同

原样贴进 ``set`` 没有改动；改其中几个值就是修改。入边只给各类的条数（``_edges_in``），要看就用 ``traverse``。
产物给出类型、标题、摘要与 ``_stale``，文档用 ``checkout`` 取出。
"""

from __future__ import annotations

from typing import Any

from ...artifact.stale import readonly
from ...query.read import get_view
from ...store.store import ContractError, Store
from ..base import STRINGS, Rendered, db_operator, schema

MAX_IDS = 20


def get(store: Store, ids: list[str] | str) -> Rendered:
    wanted = [ids] if isinstance(ids, str) else ids
    if not isinstance(wanted, list) or not wanted or not all(isinstance(i, str) for i in wanted):
        raise ContractError([{"at": "ids", "msg": "a list of node ids, such as [method_0021]"}])
    if len(wanted) > MAX_IDS:
        raise ContractError([{"at": "ids", "msg": f"at most {MAX_IDS} ids per call"}])
    wanted = list(dict.fromkeys(i.strip() for i in wanted))
    arts = [i for i in wanted if i.startswith("art_")]
    extra: dict[str, dict[str, Any]] = {}
    if arts:
        for art_id, info in readonly(store, arts).items():
            extra[art_id] = {"_stale": info["_stale"]} if info.get("_stale") else {}
            extra[art_id]["_document"] = "checkout this id to read or edit the document"
    view, missing = get_view(store, wanted, extra)
    header = []
    if missing:
        header.append(f"not in the store: {', '.join(missing)}")
    if view.data:
        header.append("fields and outgoing edges; paste a node under set to change it, add edges under create")
    return Rendered({"nodes": view.data, "missing": missing}, view.text(header))


GET = db_operator(name="get", parameters=schema({"ids": STRINGS}, ["ids"]), run=get)

__all__ = ["GET", "get"]
