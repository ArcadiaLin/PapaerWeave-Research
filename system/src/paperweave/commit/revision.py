"""有据层的修订：Content（Experiment、Claim、Contribution）都来自论文、都带锚点，改动它们要说明依据。

按改前状态判断，作用于本次改动的已有 Content 节点（它的字段与它的出边）：

- **补边**（只新增出边）：新边带自己的 ``anchor``，或在 ``confirm.<id>.revise`` 中给出 ``anchor``；不要求理由。
- **改动**（改字段、改或删出边）：``confirm.<id>.revise`` 给出 ``reason`` 与 ``anchor``。
- **删除**：``confirm.<id>.revise`` 给出 ``reason``。

``anchor`` 是支持改动的来源行，写法与记录的锚点相同（``<来源 ID>::<起>:<止>``），须在所属论文声明的来源中（同一提交中
改了论文的 ``source`` 时按改后的）。理由与锚点记入提交的
``meta.revisions``，旧值留在版本历史中。Entity 与 Concept 不在两层之内，改动不要求理由。删除另一端节点时连带删除的
边由 ``delete-impact`` 提示，不算修订。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from graph_doc import Document
from graph_vc import Changeset, GraphState

from ..model.schema import CONTENT, FROM, kind_of
from ..store.sources import SourceDir
from .anchors import check
from .problems import Problem
from .reader import Reader
from .review import revise_of

_FREE = frozenset({"exp_key"})  # 系统随字段改动更新的键，不算内容


def check_revisions(
    doc: Document,
    changeset: Changeset,
    before: GraphState,
    added: Mapping[str, list[tuple[str, str, bool]]],
    reader: Reader,
    sources: SourceDir,
    ref: Callable[[str], str] = str,
) -> tuple[list[Problem], dict[str, dict[str, Any]]]:
    """按改前状态检查本次改动。返回问题，以及要记入提交的修订（节点 id → ``{reason?, anchor?}``）。"""
    problems: list[Problem] = []
    revisions: dict[str, dict[str, Any]] = {}
    changed = _changed(changeset, before)
    revised: set[str] = set()
    for node_id, change in sorted(changed.items()):
        node = before.nodes[node_id]
        if kind_of(node.labels) not in CONTENT:
            continue
        key = ref(node_id)
        revised.add(key)
        entry = revise_of(doc.confirm.get(key)) or {}
        at = _section_at(doc, key)
        if change == "add":
            unanchored = [f"{t} {ref(d)}" for t, d, anchored in added.get(node_id, []) if not anchored]
            if unanchored and not entry.get("anchor"):
                problems.append(Problem("revision", at, _ADD.format(key=key, edges=", ".join(unanchored))))
                continue
        elif not entry.get("reason") or (change == "edit" and not entry.get("anchor")):
            need = "reason" if change == "delete" else "reason and anchor"
            problems.append(Problem("revision", at, _EDIT.format(key=key, what=change, need=need)))
            continue
        if entry.get("anchor"):
            problem = _check_anchor(
                f"confirm.{key}.revise.anchor", entry["anchor"], node_id, before, changeset, reader, sources
            )
            if problem is not None:
                problems.append(problem)
                continue
        if entry:
            revisions[node_id] = entry
    for key, value in doc.confirm.items():
        if revise_of(value) and key not in revised:
            problems.append(Problem("revision", f"confirm.{key}.revise", "nothing source-grounded changes here", "warning"))
    return problems, revisions


_ADD = (
    "{key} records what a paper says; a new edge on it needs the paper lines that support it: add anchor to "
    "the edge, or confirm.{key}.revise.anchor (new edges without anchor: {edges})"
)
_EDIT = (
    "{key} records what a paper says; this {what} is a revision and needs confirm.{key}.revise with {need} "
    "(the paper lines that support the change)"
)


def _section_at(doc: Document, key: str) -> str:
    for section in ("set", "delete", "create"):
        if key in getattr(doc, section):
            return f"{section}.{key}"
    return key


def _changed(changeset: Changeset, before: GraphState) -> dict[str, str]:
    """改动过的已有节点 → ``delete``、``edit``（改内容，或改、删出边）或 ``add``（只新增出边）。"""
    deleted = {n.id for n in changeset.nodes if n.after is None}
    changed = {
        n.id: "delete" if n.after is None else "edit"
        for n in changeset.nodes
        if n.before is not None and (n.after is None or _content_changed(n.before, n.after))
    }
    for e in changeset.edges:
        if e.key.src in deleted or e.key.dst in deleted or e.key.src not in before.nodes:
            continue
        if e.key.type in ("NAMES", "MATERIAL_OF"):
            continue
        if e.before is None:
            changed.setdefault(e.key.src, "add")
        elif changed.get(e.key.src) != "delete":
            changed[e.key.src] = "edit"
    return changed


def _content_changed(before: Mapping[str, Any], after: Mapping[str, Any]) -> bool:
    keys = (before.keys() | after.keys()) - _FREE
    return any(before.get(k) != after.get(k) for k in keys)


def _check_anchor(
    at: str,
    anchor: list[str],
    node_id: str,
    before: GraphState,
    changeset: Changeset,
    reader: Reader,
    sources: SourceDir,
) -> Problem | None:
    """修订依据：所属论文（本次提交后）声明的来源中的行范围，与记录自身的 ``anchor`` 规则相同。"""
    moved = sorted(e.key.dst for e in changeset.edges if e.key.src == node_id and e.key.type == FROM and e.after is not None)
    papers = moved or sorted(k.dst for k in before.edges if k.src == node_id and k.type == FROM)  # 同一提交换了论文时按新论文
    if not papers:
        return Problem("anchor", at, "the record has no paper to anchor the revision in")
    allowed = _sources_after(papers[0], changeset, reader)
    listed = ", ".join(allowed) if allowed else "none yet"
    whose = f"a source of {papers[0]} (its source: {listed})"
    for i, item in enumerate(anchor if isinstance(anchor, list) else [anchor]):
        _, problem = check(item, sources, allowed, whose, grounded=True)
        if problem is not None:
            return Problem("anchor", f"{at}[{i}]", problem)
    return None


def _sources_after(paper: str, changeset: Changeset, reader: Reader) -> list[str]:
    """论文在本次提交后声明的来源：同一提交中改了 ``source`` 时按改后的。"""
    node = next((n for n in changeset.nodes if n.id == paper and n.after is not None), None)
    if node is not None and "source" in node.after:
        return list(node.after.get("source") or [])
    state = reader.local_state([paper])
    return list(state.nodes[paper].props.get("source") or []) if paper in state.nodes else []


__all__ = ["check_revisions"]
