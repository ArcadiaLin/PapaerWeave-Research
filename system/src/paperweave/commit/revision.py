"""有据层的修订与解释层的并存：写入时按改前状态分层把关（commit_contract.md §5）。

- **有据层**：Experiment，以及 ``stated_by: paper`` 的 Claim、Contribution 与正反关系。改动或删除它们是一次修订，
  文档要在 ``confirm.<id>.revise`` 中给出 ``reason``；改动时还要给出 ``anchor``，即该记录所属论文中支持新内容的
  行范围（``<section>::<start>:<end>``）。锚点与理由记入提交的 ``meta.revisions``，旧值留在版本历史中。
- **解释层**：Observation、``stated_by: agent`` 的 Contribution 与正反关系。别人形成的记录可以读、可以增加出边
  （如补一条 ``ABOUT``），但只有形成者能改它的内容、删它的边或删除它；对别人的判断有不同意见，就写一条自己的
  记录（如 ``OPPOSES``），两者并存。新增 agent 的正反关系不算修订它的起点。

``note`` 是批注，不算内容，改它不受限。删除另一端节点时连带删除的边，由 ``delete-impact`` 提示，不算修订。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from graph_doc import Document
from graph_vc import Changeset, GraphState

from ..model.schema import LOCATOR, STANCE_RELS, kind_of
from ..query.view import material_of
from .problems import Problem
from .reader import Reader

REVISE_KEYS = frozenset({"anchor", "reason"})
_FREE = frozenset({"note"})  # 批注字段：不算内容


def layer(kind: str | None, props: Mapping[str, Any]) -> str | None:
    """记录所在的层：``grounded``、``interpretive``，或 ``None``（实体、概念等不在两层之内）。"""
    stated_by = props.get("stated_by")
    if kind == "Experiment" or (kind in ("Claim", "Contribution") and stated_by != "agent"):
        return "grounded"
    if kind == "Observation" or (kind == "Contribution" and stated_by == "agent"):
        return "interpretive"
    return None


def check_revisions(
    doc: Document,
    changeset: Changeset,
    before: GraphState,
    reader: Reader,
    material_root: Path,
    ref: Callable[[str], str] = str,
) -> tuple[list[Problem], dict[str, dict[str, str]]]:
    """按改前状态检查本次改动。返回问题，以及要记入提交的修订（节点 id → ``{anchor?, reason}``）。"""
    problems: list[Problem] = []
    revisions: dict[str, dict[str, str]] = {}
    grounded: set[str] = set()  # 改动过的有据层记录在文档中的引用
    for node_id, change in sorted(_changed(changeset, before, doc, ref, problems).items()):
        node = before.nodes[node_id]
        which, at = layer(kind_of(node.labels), node.props), f"nodes.{ref(node_id)}"
        if which == "interpretive" and change != "add" and node.props.get("formed_by") != doc.by:
            problems.append(Problem("coexist", at, _COEXIST.format(owner=node.props.get("formed_by"))))
        elif which == "grounded":
            grounded.add(ref(node_id))
            entry = _revise(doc.confirm.get(ref(node_id)))
            problem = _check_revise(entry, change == "delete", ref(node_id), node_id, before, reader, material_root)
            if problem is not None:
                problems.append(problem)
            else:
                assert entry is not None
                revisions[node_id] = entry
    for key, value in doc.confirm.items():
        if _revise(value) is not None and key not in grounded:
            msg = "nothing source-grounded changes here"
            problems.append(Problem("revision", f"confirm.{key}.revise", msg, "warning"))
    return problems, revisions


_COEXIST = (
    "this record was formed by {owner}; you may add relations to it, but interpretations coexist, so write "
    "your own record (for example an Observation, or OPPOSES between claims) instead of changing theirs"
)


def _changed(
    changeset: Changeset, before: GraphState, doc: Document, ref: Callable[[str], str], problems: list[Problem]
) -> dict[str, str]:
    """改动过的已有节点 → 改动程度：``delete``、``edit``（改内容或改、删出边），或 ``add``（只新增出边）。

    agent 的正反关系按边的形成者单独检查，不算起点的改动。"""
    deleted = {n.id for n in changeset.nodes if n.after is None}
    changed = {
        n.id: "delete" if n.after is None else "edit"
        for n in changeset.nodes
        if n.before is not None
        and (n.after is None or n.labels_before != n.labels_after or content_changed(n.before, n.after))
    }
    for e in changeset.edges:
        if e.key.dst in deleted or e.key.src in deleted or e.key.src not in before.nodes:
            continue
        if e.key.type in STANCE_RELS:
            stance = before.edges.get(e.key, e.before) if e.before is not None else e.after or {}
            if e.before is not None:  # 变更集中的改前值只列改动的属性，所以取改前状态中的完整属性
                problems += _stance(doc, e.key, stance, ref)
            if stance.get("stated_by") != "paper":
                continue
        if e.before is None:
            changed.setdefault(e.key.src, "add")
        elif e.after is None or content_changed(e.before, e.after):
            if changed.get(e.key.src) != "delete":
                changed[e.key.src] = "edit"
    return changed


def _check_revise(
    entry: dict[str, str] | None,
    is_delete: bool,
    key: str,
    node_id: str,
    before: GraphState,
    reader: Reader,
    material_root: Path,
) -> Problem | None:
    if entry is None or not entry.get("reason"):
        return Problem(
            "revision",
            f"nodes.{key}",
            "this record states what a paper says; changing or deleting it is a revision and needs "
            f"confirm.{key}.revise with reason (and anchor, the paper lines that support the change)",
        )
    at = f"confirm.{key}.revise.anchor"
    if "anchor" in entry:
        return _check_anchor(at, entry["anchor"], node_id, before, reader, material_root)
    return None if is_delete else Problem("revision", at, "a revision needs an anchor")


def content_changed(before: Mapping[str, Any], after: Mapping[str, Any]) -> bool:
    """属性有改动（``note`` 不算）。"""
    keys = (before.keys() | after.keys()) - _FREE
    return any(before.get(k) != after.get(k) for k in keys)


def _stance(doc: Document, key: Any, before: Mapping[str, Any], ref: Callable[[str], str]) -> list[Problem]:
    owner = before.get("formed_by")
    if before.get("stated_by") == "agent" and owner != doc.by:
        at = f"nodes.{ref(key.src)}.{key.type}[{ref(key.dst)}]"
        msg = f"this {key.type} was stated by {owner}; write your own instead of changing theirs"
        return [Problem("coexist", at, msg)]
    return []


def _revise(entry: Any) -> dict[str, str] | None:
    if isinstance(entry, Mapping) and isinstance(entry.get("revise"), Mapping):
        return {k: v for k, v in entry["revise"].items() if isinstance(v, str) and v}
    return None


def _check_anchor(
    at: str, anchor: str, node_id: str, before: GraphState, reader: Reader, material_root: Path
) -> Problem | None:
    m = LOCATOR.fullmatch(anchor)
    if m is None:
        return Problem("locator", at, f"{anchor!r} is not <section>::<start>:<end>")
    papers = sorted(k.dst for k in before.edges if k.src == node_id and k.type == "FROM")
    near = reader.local_state(papers)
    material = next((mat for p in papers if (mat := material_of(p, near)) is not None), None)
    path = near.nodes[material].props.get("path") if material is not None else None
    file = material_root / path if isinstance(path, str) else None
    if file is None or not file.is_file():
        return Problem("locator", at, "the record's paper has no readable material to anchor the revision in")
    total = len(file.read_text(encoding="utf-8").splitlines())
    start, end = int(m["start"]), int(m["end"])
    if not 1 <= start <= end <= total:
        return Problem("locator", at, f"lines {start}:{end} are outside {material} (1:{total})")
    return None


__all__ = ["REVISE_KEYS", "check_revisions", "layer"]
