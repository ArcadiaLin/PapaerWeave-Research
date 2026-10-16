"""search：一个查询覆盖全部节点、产物与带说明的关系（docs/designs/v3/tools.md）。

    search(query, kind?, paper?, topn?: 10) -> 带注释的 YAML：id → 紧凑投影

检索在 :mod:`paperweave.query.search`（精确命中在前，其余四路 RRF），投影在 :mod:`paperweave.query.view`。
产物另带 ``_stale``（可能过期的原因）。
"""

from __future__ import annotations

from typing import Any

from ...artifact.stale import readonly
from ...query.read import search_view
from ...query.search import DEFAULT_TOPN, find
from ...store.store import ContractError, Store
from ..base import STRING, STRINGS, Rendered, db_operator, schema


def search(
    store: Store, query: str, kind: list[str] | str | None = None, paper: list[str] | str | None = None, topn: int = DEFAULT_TOPN
) -> Rendered:
    kinds = _strings(kind, "kind")
    papers = _strings(paper, "paper")
    found = find(store, query, kinds, papers, topn)
    arts = [e.id for e in found.entries if e.id.startswith("art_")]
    extra = {i: {"_stale": v["_stale"]} for i, v in readonly(store, arts).items() if v.get("_stale")} if arts else {}
    view = search_view(store, found, extra)
    header = [f"search {query!r}: {len(view.data)} result(s); exact name or identity matches first, then by relevance"]
    if found.more_artifacts:
        header.append(f"{found.more_artifacts} more artifact(s) match; search with kind: [<artifact type>] to list them")
    for channel, why in found.failed.items():
        header.append(f"note: {channel} search unavailable ({why})")
    if not view.data:
        header.append("nothing found; try other words, a broader kind, or no filters")
    else:
        header.append("get <ids> returns full nodes; read_evidence reads the paper lines of an anchor")
    details: dict[str, Any] = {"results": view.data, "more_artifacts": found.more_artifacts, "failed": found.failed}
    return Rendered(details, view.text(header))


def _strings(value: Any, at: str) -> list[str]:
    if value is None:
        return []
    values = [value] if isinstance(value, str) else value
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        raise ContractError([{"at": at, "msg": "a list of strings"}])
    return values


SEARCH = db_operator(
    name="search",
    parameters=schema(
        {"query": STRING, "kind": STRINGS, "paper": STRINGS, "topn": {"type": "integer"}},
        ["query"],
    ),
    run=search,
)

__all__ = ["SEARCH", "search"]
