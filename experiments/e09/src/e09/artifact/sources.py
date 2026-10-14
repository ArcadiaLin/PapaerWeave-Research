"""共同产物的轻度规则与附注所需的来源：来源引用 → 所指的材料及所引的行（e09.artifact.types.Lookup）。

文档按原样保存，来源引用常以论文 id 开头（如 ``paper_0001::5.2::10:12``）。它在写入时指论文当时的版本，``USED``
边上的 ``material_ref`` 记下了这个版本（:func:`pins`）；读取已保存的产物时按它解析，论文有了新版本时才能看出
“这一行引的是旧版本”。检入校验时按库中当前的版本解析，即写者刚读到的版本。
"""

from __future__ import annotations

from collections.abc import Mapping

from ..model.refs import parse_ref
from ..model.schema import LOCATOR
from ..query.materials import load_lines, materials
from ..store.store import Store
from .types import Lookup, Source


def lookup(store: Store, pinned: Mapping[str, str] | None = None) -> Lookup:
    """来源引用的解析；``pinned`` 是节点 → 固定的材料 id，以节点 id 开头的引用按它解析。结果缓存在返回的函数中。"""
    pinned = dict(pinned or {})
    found: dict[str, dict | None] = {}
    lines: dict[str, list[str] | None] = {}

    def get(text: str) -> Source | None:
        ref = parse_ref(text)
        if ref is None or ref.kind != "source":
            return None
        head = pinned.get(ref.head, ref.head)
        if head not in found:
            found[head] = materials(store, {head}).get(head)
        material = found[head]
        match = LOCATOR.fullmatch(ref.locator or "")
        if material is None or match is None:
            return None
        if material["id"] not in lines:
            lines[material["id"]] = load_lines(store, material)
        text_lines = lines[material["id"]]
        cited = None if text_lines is None else text_lines[int(match["start"]) - 1 : int(match["end"])]
        return Source(material["id"], material["owner"], material["superseded_by"], cited)

    return get


def pins(store: Store, art_id: str) -> dict[str, str]:
    """产物当前版本的 ``USED`` 边上记下的材料：论文等节点 → 写入时所读的材料 id（不含所引的产物）。"""
    rows = store.query(
        """MATCH (:Artifact {id: $id})-[u:USED]->(x) WHERE u.material_ref IS NOT NULL AND NOT x:Artifact
           RETURN x.id AS id, u.material_ref AS material""",
        id=art_id,
    )
    return {r["id"]: r["material"] for r in rows}


__all__ = ["lookup", "pins"]
