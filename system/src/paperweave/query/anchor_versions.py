"""锚点所对的论文版本已被取代时的只读字段 ``_anchor_version``：在读取时推算，不存在节点上。

写入时，Content 的 ``FROM`` 边与带锚点的边记下论文当时的材料（``material_ref``）。论文换了新材料后，这些锚点仍是
旧材料的行号，按论文 id 读（``paper_0001::120:135``）会读到新材料的行。读者不会去比较材料版本，所以随记录给出：
哪些锚点写在旧材料上、论文现在的材料、怎样读旧行（``<旧材料 id>::<起>:<止>``）。改写锚点即换到新材料。
"""

from __future__ import annotations

from collections.abc import Iterable

from ..store import Store

QUERY = """
UNWIND $ids AS id
MATCH (c:Searchable {id: id})-[r]->(x) WHERE r.material_ref IS NOT NULL
OPTIONAL MATCH (c)-[:FROM]->(own:Paper)
WITH id, r, x, CASE WHEN type(r) = 'FROM' THEN x.id WHEN c:Paper THEN c.id
                    WHEN r.paper IS NOT NULL THEN r.paper ELSE own.id END AS paper
OPTIONAL MATCH (m:Material)-[:MATERIAL_OF]->(:Paper {id: paper}) WHERE m.superseded_by IS NULL
WITH id, type(r) AS rel, x.id AS dst, r.material_ref AS ref, paper, m.id AS current
WHERE current IS NOT NULL AND ref <> current
RETURN id, rel, dst, ref, paper, current ORDER BY id, rel, dst
"""


def anchor_versions(store: Store, ids: Iterable[str]) -> dict[str, str]:
    """``ids`` 中锚点写在旧材料上的节点 → 一句说明；锚点都在当前材料上的不出现。"""
    groups: dict[str, dict[tuple[str, str, str], list[str]]] = {}
    for row in store.query(QUERY, ids=sorted(set(ids))):
        what = "anchor" if row["rel"] == "FROM" else f"{row['rel']} {row['dst']}"
        groups.setdefault(row["id"], {}).setdefault((row["ref"], row["paper"], row["current"]), []).append(what)
    out: dict[str, str] = {}
    for node_id, by_version in groups.items():
        parts = [
            f"{', '.join(whats)} written against {ref}; {paper} now has {current} "
            f"(read the old lines as {ref}::<start>:<end>; rewriting the anchor moves it to {current})"
            for (ref, paper, current), whats in by_version.items()
        ]
        out[node_id] = "; ".join(parts)
    return out


__all__ = ["anchor_versions"]
