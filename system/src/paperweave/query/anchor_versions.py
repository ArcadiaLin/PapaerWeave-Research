"""锚点所在的论文版本已被取代时的只读字段 ``_anchor_version``：在读取时推算，不存在节点上。

锚点自带来源 ID（``2205.08897v3::120:135``），版本先后从 ID 读出（:mod:`paperweave.query.sources`）。库中有 Paper
声明了同一 arXiv 编号的更新版本时，写在旧版本上的锚点仍按旧版本的行读，读者不会自己去比较版本，所以随记录给出：
哪些锚点写在旧版本上、更新的版本是哪个。改写锚点（写成新版本的行）即换到新版本。
"""

from __future__ import annotations

from collections.abc import Iterable

from ..model.refs import parse_ref
from ..store import Store
from ..store.sources import declared, newer

QUERY = """
UNWIND $ids AS id
MATCH (c:Searchable {id: id})
RETURN id, 'anchor' AS what, coalesce(c.anchor, []) AS anchor
UNION ALL
UNWIND $ids AS id
MATCH (c:Searchable {id: id})-[r]->(x) WHERE r.anchor IS NOT NULL
RETURN id, type(r) + ' ' + x.id AS what, r.anchor AS anchor
"""


def anchor_versions(store: Store, ids: Iterable[str]) -> dict[str, str]:
    """``ids`` 中锚点写在旧版本上的节点 → 一句说明；锚点都在最新版本上的不出现。"""
    rows = store.query(QUERY, ids=sorted(set(ids)))
    if not any(r["anchor"] for r in rows):
        return {}
    sources = declared(store)
    groups: dict[str, dict[tuple[str, str], list[str]]] = {}
    for row in rows:
        anchors = row["anchor"] if isinstance(row["anchor"], list) else [row["anchor"]]
        for head in dict.fromkeys(r.head for r in map(parse_ref, map(str, anchors)) if r is not None and r.external):
            later = newer(head, sources)
            if later is not None:
                whats = groups.setdefault(row["id"], {}).setdefault((head, later), [])
                if row["what"] not in whats:
                    whats.append(row["what"])
    out: dict[str, str] = {}
    for node_id, by_version in groups.items():
        parts = [
            f"{', '.join(whats)} cite {old}; {', '.join(sources[new])} now also has the newer version {new} "
            f"(the lines of {old} still read as written; rewriting the anchor in {new} moves it)"
            for (old, new), whats in by_version.items()
        ]
        out[node_id] = "; ".join(parts)
    return out


__all__ = ["anchor_versions"]
