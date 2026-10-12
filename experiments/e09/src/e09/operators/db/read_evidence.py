"""ReadEvidence：按来源引用读取固定材料中的行（docs/designs/v2/operators.md §3.4）。

    read_evidence(source_refs, at?) -> {evidence: v0.1, items, missing, coverage}

来源引用写作 ``<材料 id>::<章节>::<start>:<end>``，与读视图 ``meta.source_refs`` 中的写法相同；材料 id 也可以换成
带材料的节点（论文）id，与 graph-doc 中 ``source_refs`` 的写法相同。只定位与读取，不解释内容。逐项记录状态：

- ``available``：读到，且文件哈希与入库时一致；``text`` 中每行带行号，便于引用其中更小的范围；
- ``missing``：引用格式不对、库中没有该材料，或文件不在；
- ``error``：文件哈希变了，或行号越界；不返回可能错位的文本。

``missing`` 列出状态为 ``missing`` 的引用；各状态的数量在 ``coverage`` 中。

``artifacts_only`` 为真时只读 Artifact 的文档：引用落到论文材料时记为 ``missing``，并说明这里没有原文。T1 中
只读库的读者（``store_only``）就是这样：库的内容（图与产物文档）都能读，论文原文不能读。是否为产物文档按当前库中
材料是否 ``MATERIAL_OF`` 一个 Artifact 判断。

``at``（提交 id 或分支名）给出时，按该提交时的状态解析引用（docs/designs/v2/versioning_interfaces.md §6.2）：
AsOf 给出的旧视图中的材料，即使之后材料节点或它的归属关系被删除，也能读到；文件仍按登记的哈希核对。
``coverage.at`` 给出固定下来的提交。
"""

from __future__ import annotations

from typing import Any

from ...model.refs import normalize_ref
from ...model.schema import LOCATOR
from ...query.materials import load_lines, materials, materials_at
from ...query.versions import pin
from ...store.store import ContractError, Store
from ..base import STRING, STRINGS, db_operator, schema

VERSION = "v0.1"


def read_evidence(
    store: Store, source_refs: list[str] | str, at: str | None = None, *, artifacts_only: bool = False
) -> dict[str, Any]:
    refs = [source_refs] if isinstance(source_refs, str) else source_refs
    if not isinstance(refs, list) or not refs or not all(isinstance(r, str) for r in refs):
        raise ContractError([{"at": "source_refs", "msg": "a non-empty list of source references"}])
    refs = list(dict.fromkeys(refs))
    heads = {normalize_ref(r).partition("::")[0] for r in refs}
    pinned = pin(store, at, at="at") if at is not None else None
    if pinned is None:
        found = materials(store, heads)
    else:
        found = materials_at(store.graph.state_at(pinned.commit, branch=pinned.branch), heads)
    if artifacts_only:
        documents = _documents(store, {m["id"] for m in found.values()})
        found = {h: m if m["id"] in documents else {**m, "paper": True} for h, m in found.items()}
    texts: dict[str, list[str] | None] = {}
    items = [_read(store, ref, found, texts) for ref in refs]
    states = [item["state"] for item in items]
    coverage = {s: states.count(s) for s in ("available", "missing", "error")}
    return {
        "evidence": VERSION,
        "items": items,
        "missing": [item["ref"] for item in items if item["state"] == "missing"],
        "coverage": {"requested": len(refs), **coverage, **({"at": pinned.commit} if pinned else {})},
    }


def _read(
    store: Store, ref: str, found: dict[str, dict[str, Any]], texts: dict[str, list[str] | None]
) -> dict[str, Any]:
    head, sep, locator = normalize_ref(ref).partition("::")
    match = LOCATOR.fullmatch(locator) if sep else None
    if match is None:
        return {"ref": ref, "state": "missing", "reason": "not <material>::<section>::<start>:<end>"}
    material = found.get(head)
    if material is None:
        return {"ref": ref, "state": "missing", "reason": f"{head} is not a material or a node with a material"}
    if material.get("paper"):
        return {"ref": ref, "state": "missing", "reason": "only artifact documents can be read here; source papers are not available"}
    start, end = int(match["start"]), int(match["end"])
    item: dict[str, Any] = {
        "ref": ref,
        "state": "available",
        "material": material["id"],
        "path": material["path"],
        "section": match["section"],
        "lines": [start, end],
    }
    if material["id"] not in texts:
        texts[material["id"]] = load_lines(store, material)
    lines = texts[material["id"]]
    if lines is None:
        file = store.material_root / material["path"]
        if not file.is_file():
            return {**item, "state": "missing", "reason": f"{material['path']} is not in the material root"}
        return {**item, "state": "error", "reason": "the file changed since it was registered (sha256 differs)"}
    if not 1 <= start <= end <= len(lines):
        return {**item, "state": "error", "reason": f"lines {start}:{end} are outside the material (1:{len(lines)})"}
    item["text"] = "\n".join(f"{n}| {lines[n - 1]}".rstrip() for n in range(start, end + 1)) + "\n"
    return item


def _documents(store: Store, ids: set[str]) -> set[str]:
    """``ids`` 中属于某个 Artifact 的材料（产物文档）。"""
    rows = store.query(
        "MATCH (m:Material)-[:MATERIAL_OF]->(:Artifact) WHERE m.id IN $ids RETURN DISTINCT m.id AS id", ids=sorted(ids)
    )
    return {r["id"] for r in rows}


READ_EVIDENCE = db_operator(
    name="ReadEvidence",
    parameters=schema(
        {"source_refs": STRINGS, "at": STRING},
        ["source_refs"],
    ),
    run=read_evidence,
)


__all__ = ["READ_EVIDENCE", "VERSION", "read_evidence"]
