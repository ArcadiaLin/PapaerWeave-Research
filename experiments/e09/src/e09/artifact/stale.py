"""Artifact 的文档与可能过期（docs/designs/v2/operators.md §5.6）。

过期在读取时计算，不存状态，只是提示，不修改、不删除。``_stale`` 逐项列出原因 ``{ref, reason}``：

- ``document``：Artifact 的文档文件不在，或内容与登记的哈希不同；
- ``removed``：文档头部 ``nodes_used`` 中的对象（或记录所属的 Artifact、来源引用的材料）已不在库中。删除节点时
  graph-doc 一并删掉指向它的 ``USED`` 边，所以按不可变的文档头部核对，而不是看现存的边；
- ``material``：所用材料的文件不在，或哈希与登记的不同；
- ``revised``：所用的有据层或解释层记录在产物形成之后被修订过（改了内容、标签或出边），另带 ``commit`` 指出
  最早的那次提交，可以用 Show 查看改了什么。增删改出边时，agent 的正反关系不算；别人给解释层记录新增出边也不算。
  实体与概念的改动（如补别名、描述）不算，否则提示会被噪声淹没；
- ``stale input``：所用的 Artifact 本身可能过期。
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from typing import Any

from graph_vc import Changeset

from ..commit.revision import content_changed, layer
from ..model.refs import parse_ref
from ..model.schema import ARTIFACT, STANCE_RELS, kind_of
from ..query.materials import load_lines, materials
from ..store.store import Store
from .document import header_of


def documents(store: Store, ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    """库中的 Artifact → ``{op, material}``；``material`` 是 ``{id, path, content_hash}``，没有登记时为 ``None``。"""
    rows = store.query(
        """UNWIND $ids AS id MATCH (a:Artifact {id: id})
           OPTIONAL MATCH (m:Material)-[:MATERIAL_OF]->(a)
           RETURN a.id AS id, a.op AS op, m.id AS mid, m.path AS path, m.content_hash AS content_hash""",
        ids=sorted(set(ids)),
    )
    return {
        r["id"]: {
            "op": r["op"],
            "material": None
            if r["mid"] is None
            else {"id": r["mid"], "path": r["path"], "content_hash": r["content_hash"]},
        }
        for r in rows
    }


def document_text(store: Store, material: dict[str, Any]) -> str | None:
    """文档全文；文件不在或哈希与登记的不同时为 ``None``。"""
    file = store.material_root / material["path"]
    if not file.is_file():
        return None
    data = file.read_bytes()
    return data.decode("utf-8") if hashlib.sha256(data).hexdigest() == material["content_hash"] else None


def stale(store: Store, ids: Iterable[str]) -> dict[str, list[dict[str, str]]]:
    """每个 Artifact 可能过期的原因；空列表表示没有发现。沿所用的 Artifact 递归。"""
    memo: dict[str, list[dict[str, str]]] = {}

    def visit(art_id: str) -> list[dict[str, str]]:
        if art_id in memo:
            return memo[art_id]
        memo[art_id] = []  # Artifact 只能用已有的 Artifact，不会成环；以防万一
        info = documents(store, [art_id]).get(art_id)
        material = info["material"] if info else None
        text = document_text(store, material) if material else None
        if text is None:
            memo[art_id] = [{"ref": material["id"] if material else art_id, "reason": "document"}]
            return memo[art_id]
        refs = [r for r in (parse_ref(str(t)) for t in header_of(text).get("nodes_used") or []) if r is not None]
        heads = {r.head for r in refs}
        kinds = store.kinds(heads)
        found = materials(store, {r.head for r in refs if r.kind == "source"})
        lines: dict[str, bool] = {}
        reasons: list[dict[str, str]] = []
        for ref in refs:
            if ref.kind == "source":
                head = found.get(ref.head)
                if head is None:
                    reasons.append({"ref": ref.text, "reason": "removed"})
                    continue
                if head["id"] not in lines:
                    lines[head["id"]] = load_lines(store, head) is not None
                if not lines[head["id"]]:
                    reasons.append({"ref": ref.text, "reason": "material"})
            elif ref.head not in kinds:
                reasons.append({"ref": ref.text, "reason": "removed"})
            elif kinds[ref.head] == ARTIFACT and visit(ref.head):
                reasons.append({"ref": ref.text, "reason": "stale input"})
        used = [r.head for r in refs if r.kind != "source" and kinds.get(r.head) not in (None, ARTIFACT)]
        reasons += [{"ref": head, "reason": "revised", "commit": commit} for head, commit in revised(store, art_id, used)]
        memo[art_id] = reasons
        return reasons

    return {art_id: visit(art_id) for art_id in dict.fromkeys(ids)}


def revised(store: Store, art_id: str, ids: Iterable[str]) -> list[tuple[str, str]]:
    """``ids`` 中在 ``art_id`` 形成之后被修订过的有据层与解释层记录 → 最早的那次提交，按 ``ids`` 的顺序。"""
    rows = store.query(
        """UNWIND $ids AS id MATCH (n {id: id})
           RETURN n.id AS id, labels(n) AS labels, n.stated_by AS stated_by""",
        ids=sorted(set(ids)),
    )
    layers = {r["id"]: layer(kind_of(frozenset(r["labels"])), {"stated_by": r["stated_by"]}) for r in rows}
    layers = {k: v for k, v in layers.items() if v is not None}
    if not layers:
        return []
    later = store.query(
        """MATCH (f:Commit)-[:TOUCHED {op: 'create'}]->(:Artifact {id: $art})
           UNWIND $ids AS id MATCH (c:Commit {branch: f.branch})-[:TOUCHED]->({id: id}) WHERE c.seq > f.seq
           RETURN DISTINCT c.id AS id, c.seq AS seq ORDER BY seq""",
        art=art_id,
        ids=sorted(layers),
    )
    first: dict[str, str] = {}
    for row in later:
        changeset = store.graph.get_commit(row["id"]).changeset
        for node_id in _revised_in(changeset, layers):
            first.setdefault(node_id, row["id"])
    return [(i, first[i]) for i in dict.fromkeys(ids) if i in first]


def _revised_in(changeset: Changeset, layers: dict[str, str]) -> set[str]:
    """一次提交中被修订的记录（``layers``：记录 → 所在的层）。被删除的记录由 ``removed`` 报告，这里不算。"""
    deleted = {n.id for n in changeset.nodes if n.after is None}
    out = {
        n.id
        for n in changeset.nodes
        if n.id in layers
        and n.before is not None
        and n.after is not None
        and (n.labels_before != n.labels_after or content_changed(n.before, n.after))
    }
    for e in changeset.edges:
        src = e.key.src
        if src not in layers or src in deleted or e.key.dst in deleted:
            continue
        if e.key.type in STANCE_RELS and "agent" in ((e.before or {}).get("stated_by"), (e.after or {}).get("stated_by")):
            continue
        if e.before is None and layers[src] != "grounded":
            continue  # 别人给解释层记录新增出边，不是修订
        if e.before is None or e.after is None or content_changed(e.before, e.after):
            out.add(src)
    return out


def readonly(store: Store, ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    """读视图中 Artifact 另有的只读字段：``_document``（文档路径）与 ``_stale``。"""
    ids = list(dict.fromkeys(ids))
    docs = documents(store, ids)
    reasons = stale(store, docs)
    out: dict[str, dict[str, Any]] = {}
    for art_id, info in docs.items():
        material = info["material"]
        out[art_id] = {"_document": material["path"] if material else None, "_stale": reasons[art_id]}
    return out


__all__ = ["document_text", "documents", "readonly", "revised", "stale"]
