"""固定材料（产物文档）：按引用开头找到材料，按登记的哈希读出它的行。read_evidence、产物的写入与过期共用；锚点的章节按来源目录求。"""

from __future__ import annotations

import hashlib
from typing import Any

from graph_vc import GraphState

from ..model.refs import parse_ref
from ..model.schema import PAPER_SOURCE
from ..store.store import Store
from .sections import cached_headings, section_at


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
    """锚点 → 所在的章节：按锚点开头的来源 ID 读来源目录中的论文，按标题行求章节；代码与读不到的来源不算。"""
    sources = store.sources

    def find(anchors: list[str]) -> list[str]:
        out: list[str] = []
        for anchor in anchors:
            ref = parse_ref(anchor) if isinstance(anchor, str) else None
            if ref is None or not PAPER_SOURCE.fullmatch(ref.head) or ref.lines is None:
                continue
            lines = sources.lines(ref.head)
            heads = cached_headings(ref.head, ref.head, "\n".join(lines)) if lines is not None else ()
            title = section_at(list(heads), ref.lines[0])
            if title and title not in out:
                out.append(title)
        return out

    return find


__all__ = ["load_lines", "materials", "materials_at", "section_finder"]
