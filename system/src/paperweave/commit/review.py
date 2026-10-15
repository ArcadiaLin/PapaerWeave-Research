"""需要外部判断的检查：新对象查重与 ``confirm``，以及删除的影响面。

查重只给候选，不判断是不是同一对象（middleware 不做语义判断）：新的 Entity / Concept 有未判定的候选时阻塞，
由 Agent 二选一——是同一对象，就把 ``$`` 引用换成候选 id；不是，就在 ``confirm.<引用>.distinct_from`` 中列出它。
语义通道没有阈值，只要库中有同类对象就会给出近邻，所以每个新对象都要有一次明确的判断（commit.md §5、§6 P）。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from graph_doc import Document, is_temp
from graph_vc import Changeset

from ..model.schema import ARTIFACT, CONCEPT, ENTITY, FAMILY, NAMESPACES, kind_of
from .problems import Problem

CONFIRM_KEYS = frozenset({"distinct_from", "revise"})  # revise 的含义见 revision.py


@dataclass(frozen=True, slots=True)
class Candidate:
    id: str
    channels: tuple[str, ...]  # identifier、name、lexical_name、lexical_text、semantic


@dataclass(frozen=True, slots=True)
class Lookup:
    candidates: tuple[Candidate, ...]
    errors: tuple[str, ...] = ()  # 执行失败的通道；候选可能不全


class Deduper(Protocol):
    def lookup(
        self, kind: str, *, name: str | None, identifier: str | None, text: str | None, stub: bool
    ) -> Lookup: ...


def review(doc: Document, deduper: Deduper | None) -> list[Problem]:
    """检查 ``confirm`` 的格式，并为文档中新建的 Entity / Concept 查重。``deduper`` 为 ``None`` 时不查重。"""
    problems = _check_confirm(doc)
    if deduper is None:
        return problems
    deleted = {ref for ref, node in doc.nodes.items() if node is None}
    for ref, node in doc.nodes.items():
        kind = node.props.get("kind") if node is not None and is_temp(ref) else None
        if kind not in ENTITY | CONCEPT:
            continue
        assert node is not None
        name, text = node.props.get("name"), node.props.get("description") or node.props.get("definition")
        lookup = deduper.lookup(
            kind,
            name=name if isinstance(name, str) else None,
            identifier=_identifier(node.props.get("identifiers")),
            text=text if isinstance(text, str) else node.props.get("text"),
            stub=node.props.get("stub") is True,
        )
        at = f"nodes.{ref}"
        if lookup.errors:
            problems.append(Problem("dedup", at, "some dedup channels failed: " + "; ".join(lookup.errors), "warning"))
        confirmed = set(_distinct_from(doc.confirm.get(ref)))
        open_ = [c for c in lookup.candidates if c.id not in confirmed and c.id not in deleted]
        if open_:
            problems.append(
                Problem(
                    "dedup",
                    at,
                    f"{len(open_)} possible duplicate(s) not yet judged",
                    candidates=tuple(c.id for c in open_),
                    evidence={c.id: c.channels for c in open_},
                )
            )
    return problems


def delete_impact(changeset: Changeset, before_labels: Mapping[str, frozenset[str]]) -> list[Problem]:
    """删除节点时一并删除的、来自其他模型节点与 Artifact 的入边：提示影响面，不阻塞（可经 Revert 撤销）。

    删掉 Artifact 的 ``USED`` 边后，该 Artifact 在读取时标为可能过期（按其文档头部的 ``nodes_used`` 核对）。"""
    deleted = {n.id for n in changeset.nodes if n.op == "delete"}
    problems = []
    for node_id in sorted(deleted):
        if kind_of(before_labels.get(node_id, frozenset())) is None:
            continue
        sources = sorted(
            str(e.key)
            for e in changeset.edges
            if e.op == "delete"
            and e.key.dst == node_id
            and e.key.src not in deleted
            and _is_object(before_labels.get(e.key.src, frozenset()))
        )
        if sources:
            msg = f"also removes {len(sources)} incoming relationship(s): {', '.join(sources)}"
            if any("-[USED]->" in s for s in sources):
                msg += "; artifacts that used it will read as possibly stale"
            problems.append(Problem("delete-impact", f"nodes.{node_id}", msg, "warning"))
    return problems


def _is_object(labels: frozenset[str]) -> bool:
    return kind_of(labels) is not None or ARTIFACT in labels


def _check_confirm(doc: Document) -> list[Problem]:
    problems = []
    for ref, entry in doc.confirm.items():
        at = f"confirm.{ref}"
        if ref not in doc.nodes:
            problems.append(Problem("format", at, f"{ref} is not a node in this document"))
        elif not isinstance(entry, Mapping) or not set(entry) <= CONFIRM_KEYS:
            problems.append(Problem("format", at, f"a confirmation has only {sorted(CONFIRM_KEYS)}"))
        elif not _is_ids(entry.get("distinct_from", [])):
            problems.append(Problem("format", f"{at}.distinct_from", "distinct_from is a list of existing ids"))
        elif "revise" in entry and not _is_revise(entry["revise"]):
            problems.append(
                Problem("format", f"{at}.revise", "revise is {reason: <why>, anchor: <section>::<start>:<end>}")
            )
    return problems


def _distinct_from(entry: Any) -> list[str]:
    if isinstance(entry, Mapping) and _is_ids(entry.get("distinct_from", [])):
        return list(entry.get("distinct_from", []))
    return []


def _is_revise(value: Any) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value) <= {"anchor", "reason"}
        and all(isinstance(v, str) and v.strip() for v in value.values())
    )


def _is_ids(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) and not is_temp(v) for v in value)


def _identifier(value: Any) -> str | None:
    """查重用的标识：优先唯一命名空间的，其次 url。"""
    identifiers = [v for v in value if isinstance(v, str)] if isinstance(value, list) else []
    unique = [v for v in identifiers if NAMESPACES.get(v.partition(":")[0])]
    return (unique or identifiers or [None])[0]


class ResolveDeduper:
    """经 Resolve 的写入模式查重：标识、名称精确命中，以及名称词面、文本、向量三路语义近邻。

    桩节点只开名称词面通道（commit_contract.md §4）。Resolve 连接 ``E09_NEO4J_URI`` 所指的库，
    应与写入的库相同。
    """

    def __init__(self, top_n: int | None = None):
        self._top_n = top_n

    def lookup(self, kind: str, *, name: str | None, identifier: str | None, text: str | None, stub: bool) -> Lookup:
        from ..query.fusion import TOP_N
        from ..query.resolve import resolve

        query = {k: v for k, v in {"mention": name, "identifier": identifier, "text": text}.items() if v}
        if not query or FAMILY[kind] not in ("Entity", "Concept"):
            return Lookup(())
        result = resolve(
            query,
            kind=kind,
            mode="write",
            n=self._top_n or TOP_N,
            channels={"lexical_name"} if stub else None,
        )
        found: dict[str, set[str]] = {}
        for step in result["match_trace"]:
            if step["stage"] in ("id", "alias"):
                for hit in step["hits"]:
                    found.setdefault(hit, set()).add("identifier" if step["stage"] == "id" else "name")
            elif step["stage"] == "semantic":
                for candidate in step["candidates"]:
                    found.setdefault(candidate["id"], set()).update(candidate["evidence"])
        candidates = tuple(Candidate(i, tuple(sorted(found[i]))) for i in found)
        return Lookup(candidates, tuple(result["states"]["errors"]))


__all__ = ["Candidate", "Deduper", "Lookup", "ResolveDeduper", "delete_impact", "review"]
