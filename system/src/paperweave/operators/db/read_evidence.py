"""read_evidence：按来源引用读取来源或产物文档中的行（docs/designs/v3/tools.md；f3 设计 §4 第 4 条）。

    read_evidence(source_refs, at?) -> {items, missing, coverage}

来源引用写作 ``<来源 ID>::<start>:<end>``：论文 ``2205.13504v2::120:135``（中间可以带章节，只作提示），代码
``<仓库>@<commit>::<文件>::<start>:<end>``；文字取自只读来源目录中的固定副本（:mod:`paperweave.query.sources`），目录中
只有已开放的来源，所以这里能读的不多于 read_source。产物文档写作 ``<产物 id>::<start>:<end>``（或以材料 id 开头），
这只是读取的输入，不能写进锚点。只定位与读取，不解释内容。逐项记录状态：

- ``available``：读到；``text`` 中每行带行号，便于引用其中更小的范围；
- ``missing``：引用格式不对、来源未开放、库中没有该产物，或文件不在；
- ``error``：产物文件的哈希变了，或行号越界；不返回可能错位的文本。

``missing`` 列出状态为 ``missing`` 的引用；各状态的数量在 ``coverage`` 中。

``scope`` 为 ``artifacts`` 时只读 Artifact 的文档，来源引用记为 ``missing``，并说明这里没有原文（只读库的读者）。

``at``（提交 id 或分支名）给出时，产物文档按该提交时的状态解析（docs/designs/v2/versioning_interfaces.md §6.2）：
AsOf 给出的旧视图中的文档，即使之后被取代，也能读到；文件仍按登记的哈希核对。来源 ID 本身固定版本，不随 ``at`` 变。
``coverage.at`` 给出固定下来的提交。
"""

from __future__ import annotations

from typing import Any

from ...model.refs import Ref, normalize_ref, parse_ref
from graph_vc import GraphState

from ...model.schema import ARTIFACT, CODE_SOURCE, LOCATOR
from ...query.materials import load_lines, materials, materials_at
from ...query.sections import headings, section_at
from ...store.sources import SourceDir
from ...query.versions import pin
from ...store.store import ContractError, Store
from ..base import STRING, STRINGS, db_operator, schema

SCOPES = (None, "artifacts")
MAX_LINES = 400  # 一次读取的行数上限：整篇论文读进上下文不是这个工具的用途
FORM = "write <source id>::<start>:<end>, like 2205.13504v2::120:135 (code: <repo>@<commit>::<file>::<start>:<end>)"


def read_evidence(
    store: Store, source_refs: list[str] | str, at: str | None = None, *, scope: str | None = None
) -> dict[str, Any]:
    refs = [source_refs] if isinstance(source_refs, str) else source_refs
    if not isinstance(refs, list) or not refs or not all(isinstance(r, str) for r in refs):
        raise ContractError([{"at": "source_refs", "msg": "a non-empty list of source references"}])
    if scope not in SCOPES:
        raise ValueError(f"scope must be one of {SCOPES}")
    refs = list(dict.fromkeys(refs))
    parsed = {r: parse_ref(r) for r in refs}
    heads = {p.head for p in parsed.values() if p is not None and p.kind == "source" and not p.external}
    pinned = pin(store, at, at="at") if at is not None else None
    if pinned is None:
        found = materials(store, heads)
        documents = _documents(store, {m["id"] for m in found.values()})
        found = {h: m for h, m in found.items() if m["id"] in documents}
        papers = _paper_sources(store, heads - set(found))
    else:  # 按该提交时的状态：产物与论文都从这个状态读
        state = store.graph.state_at(pinned.commit, branch=pinned.branch)
        found = {h: m for h, m in materials_at(state, heads).items() if _labels(state, m["owner"]) & {ARTIFACT}}
        papers = {
            h: list(state.nodes[h].props.get("source") or []) for h in heads - set(found) if "Paper" in _labels(state, h)
        }
    texts: dict[str, list[str] | None] = {}
    sources = store.sources
    items = []
    for ref in refs:
        p = parsed[ref]
        if p is not None and p.external:
            if scope == "artifacts":
                items.append({"ref": ref, "state": "missing", "reason": "only artifact documents can be read here; sources are not available"})
            else:
                items.append(_read_source(sources, ref, p))
        else:
            items.append(_read_document(store, ref, found, texts, papers))
    states = [item["state"] for item in items]
    coverage = {s: states.count(s) for s in ("available", "missing", "error")}
    return {
        "items": items,
        "missing": [item["ref"] for item in items if item["state"] == "missing"],
        "coverage": {"requested": len(refs), **coverage, **({"at": pinned.commit} if pinned else {})},
    }


def _read_source(sources: SourceDir, ref: str, p: Ref) -> dict[str, Any]:
    code = CODE_SOURCE.fullmatch(p.head) is not None
    if p.lines is None or (code and p.file is None):
        return {"ref": ref, "state": "missing", "reason": FORM}
    if not sources.available(p.head):
        return {"ref": ref, "state": "missing", "reason": f"{p.head} is not an available source (fetch sources with read_source)"}
    start, end = p.lines
    item: dict[str, Any] = {"ref": ref, "state": "available", "source": p.head}
    if code:
        item["file"] = p.file
    item["lines"] = [start, end]
    lines = sources.lines(p.head, p.file if code else None)
    if lines is None:
        return {**item, "state": "missing", "reason": f"{p.file} is not a text file in {p.head}" if code else f"{p.head} cannot be read"}
    return _cut(item, lines, start, end, sections=not code)


def _read_document(
    store: Store, ref: str, found: dict[str, dict[str, Any]], texts: dict[str, list[str] | None], papers: dict[str, list[str]]
) -> dict[str, Any]:
    head, sep, locator = normalize_ref(ref).partition("::")
    match = LOCATOR.fullmatch(locator) if sep else None
    if head in papers:
        listed = ", ".join(papers[head]) or "none recorded"
        return {"ref": ref, "state": "missing", "reason": f"read a paper by its source id (the source of {head}: {listed}); {FORM}"}
    if match is None:
        return {"ref": ref, "state": "missing", "reason": f"{FORM}; an artifact document is <artifact id>::<start>:<end>"}
    material = found.get(head)
    if material is None:
        return {"ref": ref, "state": "missing", "reason": f"{head} is not an artifact or a source id; {FORM}"}
    start, end = int(match["start"]), int(match["end"])
    item: dict[str, Any] = {"ref": ref, "state": "available", "material": material["id"], "path": material["path"], "lines": [start, end]}
    if material["id"] not in texts:
        texts[material["id"]] = load_lines(store, material)
    lines = texts[material["id"]]
    if lines is None:
        file = store.material_root / material["path"]
        if not file.is_file():
            return {**item, "state": "missing", "reason": f"{material['path']} is not in the material root"}
        return {**item, "state": "error", "reason": "the file changed since it was registered (sha256 differs)"}
    return _cut(item, lines, start, end, sections=True)


def _cut(item: dict[str, Any], lines: list[str], start: int, end: int, *, sections: bool) -> dict[str, Any]:
    if end - start + 1 > MAX_LINES:
        return {**item, "state": "error", "reason": f"at most {MAX_LINES} lines per reference; split the range"}
    if not 1 <= start <= end <= len(lines):
        return {**item, "state": "error", "reason": f"lines {start}:{end} are outside 1:{len(lines)}"}
    section = section_at(headings(lines), start) if sections else None
    if section:
        item["section"] = section
    item["text"] = "\n".join(f"{n}| {lines[n - 1]}".rstrip() for n in range(start, end + 1)) + "\n"
    return item


def _documents(store: Store, ids: set[str]) -> set[str]:
    """``ids`` 中属于某个 Artifact 的材料（产物文档）。"""
    rows = store.query(
        "MATCH (m:Material)-[:MATERIAL_OF]->(:Artifact) WHERE m.id IN $ids RETURN DISTINCT m.id AS id", ids=sorted(ids)
    )
    return {r["id"] for r in rows}


def _labels(state: GraphState, node_id: str | None) -> frozenset[str]:
    node = state.nodes.get(node_id) if node_id is not None else None
    return node.labels if node is not None else frozenset()


def _paper_sources(store: Store, heads: set[str]) -> dict[str, list[str]]:
    """``heads`` 中的 Paper → 它声明的来源：用论文的库内 id 读时，提示改写来源 ID。"""
    if not heads:
        return {}
    rows = store.query(
        "UNWIND $ids AS id MATCH (p:Paper {id: id}) RETURN p.id AS id, coalesce(p.source, []) AS source", ids=sorted(heads)
    )
    return {r["id"]: list(r["source"]) for r in rows}


READ_EVIDENCE = db_operator(
    name="read_evidence",
    parameters=schema(
        {"source_refs": STRINGS, "at": STRING},
        ["source_refs"],
    ),
    run=read_evidence,
)


__all__ = ["READ_EVIDENCE", "read_evidence"]
