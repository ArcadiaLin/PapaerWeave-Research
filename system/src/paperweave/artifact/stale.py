"""Artifact 的文档与可能过期（docs/designs/v2/operators.md §5.6）。

过期在读取时计算，不存状态，只是提示，不修改、不删除。``_stale`` 逐项列出原因 ``{ref, reason}``：

- ``document``：Artifact 的文档文件不在，或内容与登记的哈希不同；
- ``removed``：文档中引用的对象（或记录所属的 Artifact）已不在库中。删除节点时 graph-doc 一并
  删掉指向它的 ``USED`` 边，所以按文档本身核对，而不是看现存的边。共同产物的引用由类型契约从当前版本的文档中
  找出（:func:`references`），旧版 Agent 算子的产物按文档头部的 ``nodes_used``；
- ``material``：来源引用解析不了：来源不在来源目录中、文件不在或行号越界，或不以来源 ID 开头；
- ``superseded``：所引的来源或产物有了新版本，另带 ``by`` 给出新版本。来源引用自带版本（``2205.08897v3::10:12``），
  库中有 Paper 声明了同一 arXiv 编号的更新版本即是（:func:`paperweave.query.sources.newer`）；所引的产物（``art_0003``、
  ``art_0003#<行键>``）按 ``USED`` 边上记下的 ``material_ref``（写入时所读的版本，:func:`pinned`）判断；
- ``revised``：所用的有据层记录（Content）在产物当前版本形成之后被修订过（改了内容或出边），另带 ``commit`` 指出
  最早的那次提交，可以用 show 查看改了什么。实体与概念的改动（如补别名、描述）不算，否则提示会被噪声淹没；
- ``stale input``：所用的 Artifact 本身可能过期。
- ``uncovered``（只对 Leaderboard）：库中有使用该表数据集的 Experiment，它的论文在表中任何地方都没有出现，另带
  ``paper``。有意不收的论文写进 “Papers covered” 并说明原因，提示即消失：不收也是一个留下记录的决定。表格引用的是
  论文行而不是实验，所以 Leaderboard 的输入另外推出：表中论文里使用该数据集的 Experiment 也按 ``revised`` 检查
  （它们的评测关系改了，表中的行可能随之要改）。
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from typing import Any

from graph_vc import Changeset

from ..model.refs import parse_ref
from ..model.schema import ARTIFACT, CONTENT, kind_of
from ..commit.anchors import check
from ..query.materials import materials
from ..store.sources import declared, newer
from ..store.store import Store
from .document import header_of, parse, strip_checkout
from .types import TYPES


def documents(store: Store, ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    """库中的 Artifact → ``{op, material}``；``material`` 是当前版本（没有被取代）的 ``{id, path, content_hash}``，
    没有登记时为 ``None``。"""
    rows = store.query(
        """UNWIND $ids AS id MATCH (a:Artifact {id: id})
           OPTIONAL MATCH (m:Material)-[:MATERIAL_OF]->(a) WHERE m.superseded_by IS NULL
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
        refs = [r for r in (parse_ref(t) for t in references(info["op"], text)) if r is not None]
        heads = {r.head for r in refs}
        kinds = store.kinds(heads)
        pins = pinned(store, art_id)
        owners = declared(store) if any(r.kind == "source" for r in refs) else {}
        versions = materials(store, {pins[h] for h in heads if kinds.get(h) == ARTIFACT and h in pins})
        reasons: list[dict[str, str]] = []
        for ref in refs:
            if ref.kind == "source":
                problem = None if ref.external else "not a source id"
                if problem is None:
                    _, problem = check(ref.text, store.sources, None, grounded=False, require_text=False)
                if problem is not None:
                    reasons.append({"ref": ref.text, "reason": "material"})
                elif later := newer(ref.head, owners):
                    reasons.append({"ref": ref.text, "reason": "superseded", "by": later})
            elif ref.head not in kinds:
                reasons.append({"ref": ref.text, "reason": "removed"})
            elif kinds[ref.head] == ARTIFACT:
                version = versions.get(pins.get(ref.head, ""))
                if version is not None and version.get("superseded_by"):
                    reasons.append({"ref": ref.text, "reason": "superseded", "by": version["superseded_by"]})
                if visit(ref.head):
                    reasons.append({"ref": ref.text, "reason": "stale input"})
        used = [r.head for r in refs if r.kind != "source" and kinds.get(r.head) not in (None, ARTIFACT)]
        uncovered: list[dict[str, str]] = []
        if info["op"] == "Leaderboard":
            covered = sorted({h for h in heads if kinds.get(h) == "Paper"})
            inputs, uncovered = _leaderboard_inputs(store, header_of(text).get("dataset"), covered)
            used += [e for e in inputs if e not in used]
        reasons += [
            {"ref": head, "reason": "revised", "commit": commit} for head, commit in revised(store, art_id, used)
        ]
        reasons += uncovered
        memo[art_id] = reasons
        return reasons

    return {art_id: visit(art_id) for art_id in dict.fromkeys(ids)}


def _leaderboard_inputs(store: Store, dataset: Any, covered: list[str]) -> tuple[list[str], list[dict[str, str]]]:
    """Leaderboard 的隐含输入（表中论文里使用该数据集的 Experiment），以及来自表外论文的这类 Experiment
    （``uncovered``，每篇论文列一次，带它的实验）。"""
    dataset_id = str(dataset).split()[0] if dataset else ""
    if not dataset_id:
        return [], []
    rows = store.query(
        """MATCH (e:Experiment)-[:USES]->(:Dataset {id: $dataset}) MATCH (e)-[:FROM]->(p:Paper)
           RETURN p.id AS paper, collect(e.id) AS experiments ORDER BY paper""",
        dataset=dataset_id,
    )
    inputs = [e for r in rows if r["paper"] in covered for e in sorted(r["experiments"])]
    uncovered = [
        {"ref": r["paper"], "reason": "uncovered", "experiments": ", ".join(sorted(r["experiments"]))}
        for r in rows
        if r["paper"] not in covered
    ]
    return inputs, uncovered


def pinned(store: Store, art_id: str) -> dict[str, str]:
    """产物 ``USED`` 边上记下的材料：终点 → 写入时所读的材料 id（所引产物的某个版本）。"""
    rows = store.query(
        """MATCH (:Artifact {id: $id})-[u:USED]->(x) WHERE u.material_ref IS NOT NULL
           RETURN x.id AS id, u.material_ref AS material""",
        id=art_id,
    )
    return {r["id"]: r["material"] for r in rows}


def references(op: str | None, text: str) -> list[str]:
    """产物文档中的引用：共同产物由类型契约找出，旧版 Agent 算子的产物取头部的 ``nodes_used``。"""
    kind = TYPES.get(op or "")
    if kind is None:
        return [str(t) for t in header_of(text).get("nodes_used") or []]
    try:
        doc = parse(strip_checkout(text))
    except ValueError:
        return []
    return list(dict.fromkeys(m.text for m in kind.mentions(doc)))


def revised(store: Store, art_id: str, ids: Iterable[str]) -> list[tuple[str, str]]:
    """``ids`` 中在 ``art_id`` 当前版本形成之后被修订过的有据层记录 → 最早的那次提交，按 ``ids`` 的顺序。

    当前版本形成的提交取产物节点与当前版本文档两者创建提交中较晚的一个：旧版产物只有一个版本，内容相同的文档
    可能沿用更早写入的 Material。"""
    rows = store.query(
        """UNWIND $ids AS id MATCH (n {id: id}) RETURN n.id AS id, labels(n) AS labels""",
        ids=sorted(set(ids)),
    )
    layers = {r["id"] for r in rows if kind_of(frozenset(r["labels"])) in CONTENT}  # 有据层：全部 Content
    if not layers:
        return []
    later = store.query(
        """MATCH (a:Artifact {id: $art})<-[:TOUCHED {op: 'create'}]-(created:Commit)
           OPTIONAL MATCH (a)<-[:MATERIAL_OF]-(m:Material) WHERE m.superseded_by IS NULL
           OPTIONAL MATCH (m)<-[:TOUCHED {op: 'create'}]-(written:Commit)
           WITH CASE WHEN written IS NOT NULL AND written.seq > created.seq THEN written ELSE created END AS f
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


def _revised_in(changeset: Changeset, layers: set[str]) -> set[str]:
    """一次提交中被修订的有据层记录。被删除的记录由 ``removed`` 报告，这里不算。"""
    deleted = {n.id for n in changeset.nodes if n.after is None}
    out = {
        n.id
        for n in changeset.nodes
        if n.id in layers
        and n.before is not None
        and n.after is not None
        and (n.labels_before != n.labels_after or _content_changed(n.before, n.after))
    }
    for e in changeset.edges:
        src = e.key.src
        if src not in layers or src in deleted or e.key.dst in deleted:
            continue
        if e.before is None or e.after is None or _content_changed(e.before, e.after):
            out.add(src)
    return out


def _content_changed(before: dict[str, Any], after: dict[str, Any]) -> bool:
    keys = (before.keys() | after.keys()) - {"exp_key"}
    return any(before.get(k) != after.get(k) for k in keys)


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


__all__ = ["document_text", "documents", "pinned", "readonly", "references", "revised", "stale"]
