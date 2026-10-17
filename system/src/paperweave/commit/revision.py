"""有据层的修订：Content（Experiment、Claim、Contribution）都来自论文、都带锚点，改动它们要说明依据。

按改前状态判断，作用于本次改动的已有 Content 节点（它的字段与它的出边）：

- **补边**（只新增出边）：新边带自己的 ``anchor``，或在 ``confirm.<id>.revise`` 中给出 ``anchor``；不要求理由。
- **改动**（改字段、改或删出边）：``confirm.<id>.revise`` 给出 ``reason`` 与 ``anchor``。
- **删除**：``confirm.<id>.revise`` 给出 ``reason``。

``anchor`` 是该记录所属论文中支持改动的行范围，按论文的当前材料检查不越界（同一提交换了新材料时按新材料）。理由与锚点记入提交的
``meta.revisions``，旧值留在版本历史中。Entity 与 Concept 不在两层之内，改动不要求理由。删除另一端节点时连带删除的
边由 ``delete-impact`` 提示，不算修订。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from graph_doc import Document
from graph_vc import Changeset, GraphState

from ..model.schema import ANCHOR, CONTENT, FROM, kind_of
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
    material_root: Path,
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
                f"confirm.{key}.revise.anchor", entry["anchor"], node_id, before, changeset, reader, material_root
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
    material_root: Path,
) -> Problem | None:
    papers = sorted(k.dst for k in before.edges if k.src == node_id and k.type == FROM)
    near = reader.local_state(papers)
    path = _attached_path(changeset, papers, near)
    if path is None:
        materials = sorted(
            k.src
            for k in near.edges
            if k.type == "MATERIAL_OF" and k.dst in papers and not near.nodes[k.src].props.get("superseded_by")
        )
        path = near.nodes[materials[0]].props.get("path") if materials else None
    file = material_root / path if isinstance(path, str) else None
    if file is None or not file.is_file():
        return Problem("anchor", at, "the record's paper has no readable material to anchor the revision in")
    total = len(file.read_text(encoding="utf-8").splitlines())
    for item in anchor:
        m = ANCHOR.fullmatch(item)
        if m is None or not 1 <= int(m["start"]) <= int(m["end"]) <= total:
            return Problem("anchor", at, f"lines {item} are outside the paper (1:{total})")
    return None


def _attached_path(changeset: Changeset, papers: list[str], near: GraphState) -> str | None:
    """本次提交给论文换上的新材料的路径：同一提交中改写的锚点按新版本检查，与记录自身的 ``anchor`` 一致。"""
    attached = sorted(
        e.key.src
        for e in changeset.edges
        if e.key.type == "MATERIAL_OF" and e.key.dst in papers and e.before is None and e.after is not None
    )
    if not attached:
        return None
    node = next((n for n in changeset.nodes if n.id == attached[0] and n.after is not None), None)
    props = node.after if node is not None else near.nodes[attached[0]].props if attached[0] in near.nodes else {}
    path = props.get("path")
    return path if isinstance(path, str) else None


__all__ = ["check_revisions"]
