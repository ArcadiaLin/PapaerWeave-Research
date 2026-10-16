"""固定材料：按引用开头找到材料，按登记的哈希读出它的行，按标题行求锚点的章节。read_evidence、读取投影、产物的写入与过期共用。"""

from __future__ import annotations

import hashlib
from typing import Any

from graph_vc import GraphState

from ..store.store import Store
from .sections import cached_headings, sections


def materials(store: Store, heads: set[str]) -> dict[str, dict[str, Any]]:
    """引用开头（材料 id 或带材料的节点 id）→ 材料 ``{id, path, content_hash, owner, superseded_by}``。

    ``owner`` 是材料所属的节点：开头是节点时就是它；开头是材料时取 ``MATERIAL_OF`` 指向的节点（内容相同的
    Artifact 文档只存一份，可能有多个，取 id 最小的）；材料不属于任何节点时为 ``None``。"""
    rows = store.query(
        """UNWIND $heads AS head
           OPTIONAL MATCH (m:Material {id: head})
           OPTIONAL MATCH (owned:Material)-[:MATERIAL_OF]->({id: head}) WHERE owned.superseded_by IS NULL
           WITH head, coalesce(m, owned) AS material, CASE WHEN m IS NULL THEN head END AS node
           WHERE material IS NOT NULL
           OPTIONAL MATCH (material)-[:MATERIAL_OF]->(o)
           WITH head, material, node, min(o.id) AS first
           RETURN head, material.id AS id, material.path AS path, material.content_hash AS content_hash,
                  coalesce(node, first) AS owner, material.superseded_by AS superseded_by""",
        heads=sorted(heads),
    )
    return {r["head"]: {k: r[k] for k in ("id", "path", "content_hash", "owner", "superseded_by")} for r in rows}


class _NoNode:
    props: dict[str, Any] = {}


_NONE = _NoNode()


def materials_at(state: GraphState, heads: set[str]) -> dict[str, dict[str, Any]]:
    """与 :func:`materials` 相同，但按某个提交时的状态解析（``VersionedGraph.state_at``），用于读取旧视图中的材料。"""
    out: dict[str, dict[str, Any]] = {}
    for head in heads:
        node = state.nodes.get(head)
        if node is None:
            continue
        owned = sorted(
            k.src
            for k in state.edges
            if k.dst == head and k.type == "MATERIAL_OF" and not state.nodes.get(k.src, _NONE).props.get("superseded_by")
        )
        material = head if "Material" in node.labels else (owned[0] if owned else None)
        if material is None:
            continue
        owners = sorted(k.dst for k in state.edges if k.src == material and k.type == "MATERIAL_OF")
        props = state.nodes[material].props
        owner = head if material != head else (owners[0] if owners else None)
        out[head] = {"id": material, "owner": owner, **{k: props.get(k) for k in ("path", "content_hash", "superseded_by")}}
    return out


def load_lines(store: Store, material: dict[str, Any]) -> list[str] | None:
    """材料的行；文件不在或哈希与登记的不一致时为 ``None``。"""
    file = store.material_root / material["path"]
    if not file.is_file():
        return None
    data = file.read_bytes()
    if hashlib.sha256(data).hexdigest() != material["content_hash"]:
        return None
    return data.decode("utf-8").splitlines()


def section_finder(store: Store):
    """锚点 → 章节：按材料 id 读出材料（核对哈希），按标题行求章节；同一份材料只解析一次。"""
    known: dict[str, tuple[tuple[int, str], ...]] = {}

    def find(material_id: str, anchors: list[str]) -> list[str]:
        if material_id not in known:
            rows = store.query(
                "MATCH (m:Material {id: $id}) RETURN m.path AS path, m.content_hash AS content_hash", id=material_id
            )
            lines = load_lines(store, rows[0]) if rows else None
            known[material_id] = (
                cached_headings(rows[0]["path"], rows[0]["content_hash"], "\n".join(lines)) if lines else ()
            )
        return sections(list(known[material_id]), anchors)

    return find


__all__ = ["load_lines", "materials", "materials_at", "section_finder"]
