"""一次写入：解析 → 翻译 → 查重 → 求差 → 写入后状态检查 → 修订检查 →（apply 时）分配 id 并提交。

:func:`prepare` 只读不写，对应 dry_run，其中按层检查修订与并存（:mod:`.revision`）；:func:`apply` 先做一遍 dry_run，没有错误时为临时引用分配 id，
用真实 id 重新准备一遍，再经 graph-vc 在单事务中提交。返回给 Agent 的 graph-plan / graph-result 格式另行定义。
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Protocol

from graph_doc import DiffError, DocError, Document, diff, is_temp, parse
from graph_vc import Changeset, ChangesetError, CommitRecord, ConflictError, GraphState, VersionedGraph

from ..model.schema import DERIVED_FIELDS, NODE_LABELS, PREFIX, REL_TYPES
from .checks import check_state, touched
from .problems import Problem
from .review import delete_impact, review
from .revision import check_revisions
from .translate import Context, translate


class IdAllocator(Protocol):
    def allocate_ids(self, prefix: str, count: int = 1) -> list[str]: ...


@dataclass(frozen=True, slots=True)
class Prepared:
    """准备结果。``changeset`` 为 ``None`` 表示在得到变更集之前就有错误；空变更集表示无需写入。"""

    document: Document | None
    changeset: Changeset | None
    problems: tuple[Problem, ...] = ()
    ids: dict[str, str] = field(default_factory=dict)  # $ 名 → id；dry_run 中为空
    revisions: dict[str, dict[str, Any]] = field(default_factory=dict)  # 有据层修订：节点 id → {reason?, anchor?}

    @property
    def errors(self) -> list[Problem]:
        return [p for p in self.problems if p.severity == "error"]

    @property
    def ok(self) -> bool:
        return self.changeset is not None and not self.errors


def prepare(text: str, ctx: Context, ids: Mapping[str, str] | None = None) -> Prepared:
    """只读地准备一次写入，报告全部问题。"""
    try:
        doc = parse(text)
    except DocError as exc:
        return Prepared(None, None, tuple(_doc_problem(p) for p in exc.problems))

    ids = dict(ids or {})
    translation = translate(doc, ctx, ids)
    problems = list(translation.problems) + review(doc, ctx.deduper)
    if any(p.severity == "error" for p in problems):
        return Prepared(doc, None, tuple(problems), ids)

    try:
        changeset = diff(translation.fragment, translation.local)
    except DiffError as exc:
        return Prepared(doc, None, tuple(problems + [Problem("reference", "", p) for p in exc.problems]), ids)
    changeset = replace(changeset, files=translation.files)
    # 写入后检查要看到触及节点的全部关系（如删除一个节点后，它的邻居是否还有必需的边），所以补取它们的邻域。
    nearby = ctx.reader.local_state(touched(changeset))
    local = GraphState({**nearby.nodes, **translation.local.nodes}, {**nearby.edges, **translation.local.edges})
    try:
        changeset.validate(node_labels=NODE_LABELS, rel_types=REL_TYPES, unversioned_props=DERIVED_FIELDS)
        after = local.apply(changeset)
    except ChangesetError as exc:
        return Prepared(doc, None, tuple(problems + [Problem("value", "", p) for p in exc.problems]), ids)
    except ConflictError as exc:  # 求差与现状不一致：写入路径自身的缺陷
        raise AssertionError(f"diff produced a changeset that does not apply: {exc}") from exc

    refs = translation.refs
    problems += check_state(after, touched(changeset), lambda node_id: refs.get(node_id, node_id))
    problems += delete_impact(changeset, {node_id: node.labels for node_id, node in local.nodes.items()})
    revision_problems, revisions = check_revisions(
        doc,
        changeset,
        local,
        translation.added_edges,
        ctx.reader,
        ctx.material_root,
        lambda node_id: refs.get(node_id, node_id),
    )
    problems += revision_problems
    return Prepared(doc, changeset, tuple(problems), ids, revisions)


def apply(
    text: str,
    graph: VersionedGraph,
    ctx: Context,
    *,
    message: str = "",
    base: str | None = None,
    meta: Mapping[str, Any] | None = None,
) -> tuple[Prepared, CommitRecord | None]:
    """准备并提交。有错误或无需写入时不提交，返回 ``None``。``meta`` 另记入提交的 ``meta``（如草稿文件）。"""
    dry = prepare(text, ctx)
    if not dry.ok or not dry.changeset:
        return dry, None
    assert dry.document is not None
    ids = allocate_ids(dry.document, graph)
    prepared = prepare(text, ctx, ids)
    if not prepared.ok or not prepared.changeset:
        return prepared, None
    record = graph.commit(
        prepared.changeset,
        author=ctx.user or "",
        message=message,
        source=ctx.source,
        base=base,
        input=text,
        meta={"ids": ids, "dedup": ctx.deduper is not None, "revisions": prepared.revisions}
        | ({"agent": ctx.agent} if ctx.agent else {})
        | dict(meta or {}),
    )
    return prepared, record


def allocate_ids(doc: Document, graph: IdAllocator) -> dict[str, str]:
    """按 kind 的 id 前缀为 ``$`` 名分配 id，保持文档中的顺序。"""
    by_prefix: dict[str, list[str]] = defaultdict(list)
    for ref, node in doc.create.items():
        if is_temp(ref):
            by_prefix[PREFIX[node.props["kind"]]].append(ref)
    ids: dict[str, str] = {}
    for prefix, refs in by_prefix.items():
        ids.update(zip(refs, graph.allocate_ids(prefix, len(refs)), strict=True))
    return ids


def _doc_problem(problem: str) -> Problem:
    at, sep, msg = problem.partition(": ")
    return Problem("format", at if sep else "", msg if sep else problem)


__all__ = ["IdAllocator", "Prepared", "allocate_ids", "apply", "prepare"]
