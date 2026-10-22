"""需要写者判断的检查：新建的 Entity / Concept 查重与 ``confirm``，以及删除的影响面。

查重只给候选，不判断是不是同一对象（中间件不做语义判断）：新节点有未判定的候选时阻塞，由写者二选一——是同一对象，
就删掉这个 ``$`` 节点、在引用处改用候选 id；不是，就在 ``confirm.<$ 名>.distinct_from`` 中列出它。

查重的实现（名称、标识、描述的多路检索）在读取层，由算子注入（:class:`Deduper`），写入管线不依赖它。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from graph_doc import Document, is_temp
from graph_vc import Changeset

from ..model.refs import normalize_ref
from ..model.schema import ARTIFACT, NAMED, kind_of
from .problems import Problem

CONFIRM_KEYS = frozenset({"distinct_from", "revise"})
REVISE_KEYS = frozenset({"reason", "anchor"})


@dataclass(frozen=True, slots=True)
class Candidate:
    id: str
    channels: tuple[str, ...]  # identity、name、text、vector


@dataclass(frozen=True, slots=True)
class Lookup:
    candidates: tuple[Candidate, ...]
    errors: tuple[str, ...] = ()  # 执行失败的通道；候选可能不全


class Deduper(Protocol):
    def lookup(
        self, kind: str, *, name: str | None, identities: list[str], description: str | None, stub: bool
    ) -> Lookup: ...


def review(doc: Document, deduper: Deduper | None) -> list[Problem]:
    """检查 ``confirm`` 的格式，并为文档中新建的 Entity / Concept 查重。``deduper`` 为 ``None`` 时不查重。"""
    problems = _check_confirm(doc)
    if deduper is None:
        return problems
    deleted = set(doc.deleted_nodes())
    for ref, node in doc.create.items():
        kind = node.props.get("kind")
        if not is_temp(ref) or kind not in NAMED:
            continue
        name, description = node.props.get("name"), node.props.get("description")
        identities = node.props.get("identities")
        lookup = deduper.lookup(
            kind,
            name=name if isinstance(name, str) else None,
            identities=[i for i in identities if isinstance(i, str)] if isinstance(identities, list) else [],
            description=description if isinstance(description, str) else None,
            stub=node.props.get("stub") is True,
        )
        at = f"create.{ref}"
        if lookup.errors:
            problems.append(Problem("dedup", at, "some dedup channels failed: " + "; ".join(lookup.errors), "warning"))
        confirmed = set(distinct_from(doc.confirm.get(ref)))
        open_ = [c for c in lookup.candidates if c.id not in confirmed and c.id not in deleted]
        if open_:
            problems.append(
                Problem(
                    "dedup",
                    at,
                    f"{len(open_)} existing {kind} node(s) may be the same as {ref}; judge each one",
                    candidates=tuple(c.id for c in open_),
                    evidence={c.id: c.channels for c in open_},
                )
            )
    return problems


def delete_impact(changeset: Changeset, before_labels: Mapping[str, frozenset[str]]) -> list[Problem]:
    """删除节点时一并删除的、来自其他证据节点与产物的入边：提示影响面，不阻塞（可以回退）。"""
    deleted = {n.id for n in changeset.nodes if n.op == "delete"}
    problems = []
    for node_id in sorted(deleted):
        if kind_of(before_labels.get(node_id, frozenset())) is None:
            continue
        sources = sorted(
            f"{e.key.src} {e.key.type}"
            for e in changeset.edges
            if e.op == "delete"
            and e.key.dst == node_id
            and e.key.src not in deleted
            and _is_object(before_labels.get(e.key.src, frozenset()))
        )
        if sources:
            msg = f"also removes {len(sources)} incoming edge(s): {', '.join(sources)}"
            if any(s.endswith(" USED") for s in sources):
                msg += "; artifacts that used it will read as possibly stale"
            problems.append(Problem("delete-impact", f"delete.{node_id}", msg, "warning"))
    return problems


def _is_object(labels: frozenset[str]) -> bool:
    return kind_of(labels) is not None or ARTIFACT in labels


def _check_confirm(doc: Document) -> list[Problem]:
    problems = []
    refs = set(doc.refs())
    for ref, entry in doc.confirm.items():
        at = f"confirm.{ref}"
        if ref not in refs:
            problems.append(Problem("format", at, f"{ref} is not a node under create, set or delete in this file"))
        elif not isinstance(entry, Mapping) or not set(entry) <= CONFIRM_KEYS:
            problems.append(Problem("format", at, "a confirmation has distinct_from and/or revise"))
        elif not _is_ids(entry.get("distinct_from", [])):
            problems.append(Problem("format", f"{at}.distinct_from", "distinct_from is a list of existing ids"))
        elif "revise" in entry and revise_of(entry) is None:
            problems.append(
                Problem("format", f"{at}.revise", "revise has reason (text) and anchor (source lines like [2205.13504v2::120:135])")
            )
    return problems


def distinct_from(entry: Any) -> list[str]:
    if isinstance(entry, Mapping) and _is_ids(entry.get("distinct_from", [])):
        return list(entry.get("distinct_from", []))
    return []


def revise_of(entry: Any) -> dict[str, Any] | None:
    """``confirm.<ref>.revise`` → ``{reason?, anchor?: [<来源 ID>::<start>:<end>…]}``（规范写法）；格式不对时为 ``None``。
    锚点是否可解析由 :func:`paperweave.commit.revision.check_revisions` 检查。"""
    if not isinstance(entry, Mapping) or not isinstance(entry.get("revise"), Mapping):
        return None
    revise = entry["revise"]
    if not set(revise) <= REVISE_KEYS:
        return None
    out: dict[str, Any] = {}
    reason = revise.get("reason")
    if reason is not None:
        if not isinstance(reason, str) or not reason.strip():
            return None
        out["reason"] = reason.strip()
    anchor = revise.get("anchor")
    if anchor is not None:
        anchor = [anchor] if isinstance(anchor, str) else anchor
        if not isinstance(anchor, list) or not anchor or not all(isinstance(a, str) and a.strip() for a in anchor):
            return None
        out["anchor"] = [normalize_ref(a) for a in anchor]
    return out


def _is_ids(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) and not is_temp(v) for v in value)


__all__ = ["Candidate", "Deduper", "Lookup", "delete_impact", "distinct_from", "review", "revise_of"]
