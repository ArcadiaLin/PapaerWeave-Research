"""Log：发生过哪些写入（docs/designs/v2/versioning_interfaces.md §3）。

    Log(branch="main", node?, by?, source?, since?, until?, budget=50, continuation?) -> {commits, meta}

从新到旧列出分支上的提交：头信息、按操作的计数，以及触及与删除的对象（各给前 20 个与总数；NameKey、Material
这类系统节点不列，它们的变化显示在所属对象上）。不给内容，内容用
Show。``node`` 只列触及这些节点的提交（新建、修改、删除了它，或增删改了它的关系）；``source`` 按前缀匹配；
``since`` / ``until`` 是提交 id（``since`` 不含本身）或 ISO 时间（只给日期时 ``until`` 含当天）。
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from graph_vc import CommitRecord

from ..operators.base import STRING, STRINGS, interface, schema
from ..query.capacity import paged
from ..query.changes import object_ids, preview
from ..query.excerpts import LIMIT
from ..query.versions import COMMIT, continue_at, id_list, paging, pin, resume
from ..store.store import ContractError, Store

DEFAULT_BUDGET = 50


def log(
    store: Store,
    branch: str = "main",
    node: list[str] | str | None = None,
    by: str | None = None,
    source: str | None = None,
    since: str | None = None,
    until: str | None = None,
    budget: int = DEFAULT_BUDGET,
    continuation: str | None = None,
) -> dict[str, Any]:
    budget = paging(budget, at="budget", low=1)
    resumed = resume(continuation, {"branch": branch})
    pinned = pin(store, resumed[1][0] if resumed else branch, at="branch")
    offset = resumed[0] if resumed else 0
    records = pinned.history
    nodes = id_list(node, at="node")
    matched = [
        r
        for r in reversed(records)
        if (nodes is None or set(nodes) & {*r.touched, *r.removed})
        and (by is None or r.author == by)
        and (source is None or r.source.startswith(source))
        and _within(r, records, since, until)
    ]
    page = matched[offset : offset + budget]

    def view(count: int) -> dict[str, Any]:
        end = offset + count
        more = end < len(matched)
        meta = {
            "at": pinned.commit,
            "returned": count,
            "matched": len(matched),
            "continuation": continue_at(end, pinned.commit) if more else None,
            "size": {"limit": LIMIT, "used": LIMIT},
        }
        return {"commits": [entry(r) for r in page[:count]], "meta": meta}

    return paged(view, len(page), "commits")


def entry(record: CommitRecord) -> dict[str, Any]:
    """Log 中一个提交的条目（Show 的摘要也用它）。"""
    out = {
        "id": record.id,
        "at": record.at,
        "by": record.author,
        "source": record.source,
        "message": record.message,
        "counts": counts(record),
    }
    out.update(preview("touched", object_ids(record.touched)))
    if removed := object_ids(record.removed):
        out.update(preview("removed", removed))
    return out


def counts(record: CommitRecord) -> dict[str, dict[str, int]]:
    """按操作的计数：``{nodes: {create: n, …}, edges: {…}}``。"""
    out = {}
    for name, items in (("nodes", record.changeset.nodes), ("edges", record.changeset.edges)):
        if items:
            out[name] = dict(sorted(Counter(c.op for c in items).items()))
    return out


def _within(record: CommitRecord, records: list[CommitRecord], since: Any, until: Any) -> bool:
    return (since is None or _after(record, records, since, "since")) and (
        until is None or not _after(record, records, until, "until")
    )


def _after(record: CommitRecord, records: list[CommitRecord], bound: Any, at: str) -> bool:
    """``record`` 是否在界限之后：界限为提交时按序号，为时间时按写入时间（``until`` 只给日期时取当天结束）。"""
    if isinstance(bound, str) and COMMIT.match(bound):
        seqs = {r.id: r.seq for r in records}
        if bound not in seqs:
            raise ContractError([{"at": at, "msg": f"{bound} is not on this branch up to the pinned commit"}])
        return record.seq > seqs[bound]
    moment = _moment(bound, at)
    if at == "until" and isinstance(bound, str) and len(bound) == 10:
        return _moment(record.at, at) >= moment + timedelta(days=1)
    return _moment(record.at, at) > moment if at == "until" else _moment(record.at, at) >= moment


def _moment(value: Any, at: str) -> datetime:
    try:
        moment = datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        moment = None
    if moment is None:
        raise ContractError([{"at": at, "msg": "a commit id, or an ISO date or time such as 2026-10-06T14:00"}])
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


LOG = interface(
    name="Log",
    parameters=schema(
        {
            "branch": STRING,
            "node": STRINGS,
            "by": STRING,
            "source": STRING,
            "since": STRING,
            "until": STRING,
            "budget": {"type": "integer"},
            "continuation": STRING,
        }
    ),
    run=log,
)


__all__ = ["DEFAULT_BUDGET", "LOG", "counts", "entry", "log"]
