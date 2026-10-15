"""Show：一次写入做了什么、依据什么（docs/designs/v2/versioning_interfaces.md §4）。

    Show(commit, part=summary | input | changes, node?, field?, offset?, continuation?)

- ``summary``：头信息、计数、触及与删除的节点、同一性判断 ``confirm``、临时引用到 id 的映射 ``ids``、``input`` 的大小；
- ``input``：交上来的原文（Commit 的 graph-doc，CheckIn 的修改说明与交上来的文档；旧提交中还有已下线的 Agent
  算子的调用参数），按行分页，单行放不下时在行内断开；
- ``changes``：变更视图（:mod:`paperweave.query.changes`），按节点分页。它就是父提交与本提交之间的净差异，与
  ``Diff(parent, commit)`` 相同。``node`` 只看这些节点；``field``（与一个 ``node``）分块读取被截短的值。
"""

from __future__ import annotations

from typing import Any

import yaml

from graph_vc import CommitRecord

from ..operators.base import STRING, STRINGS, interface, schema
from ..query.capacity import chunk, field_view, finish, fit, paged, size
from ..query.changes import changes, object_ids, preview
from ..query.excerpts import LIMIT
from ..query.versions import Pinned, continue_at, id_list, pin, resume
from ..store.store import ContractError, Store
from .log import counts

PARTS = ("summary", "input", "changes")


def show(
    store: Store,
    commit: str,
    part: str = "summary",
    node: list[str] | str | None = None,
    field: str | None = None,
    offset: int | None = None,
    continuation: str | None = None,
) -> dict[str, Any]:
    if part not in PARTS:
        raise ContractError([{"at": "part", "msg": f"one of {list(PARTS)}"}])
    if (field is not None or offset is not None) and part != "changes":
        raise ContractError([{"at": "field", "msg": "field and offset read a cut value of part: changes"}])
    resumed = resume(continuation, {"commit": commit})
    pinned = pin(store, resumed[1][0] if resumed else commit, at="commit")
    start = resumed[0] if resumed else 0
    if part == "summary":
        return finish({"commit": summary(pinned.record), "meta": {"at": pinned.commit}})
    if part == "input":
        return _input(pinned, start)
    return _changes(store, pinned, node, field, offset, start)


def summary(record: CommitRecord) -> dict[str, Any]:
    """提交的头信息与计数；``ids`` 与 ``touched``、``removed`` 只给预览与总数。"""
    out: dict[str, Any] = {
        "id": record.id,
        "seq": record.seq,
        "parent": record.parent,
        "branch": record.branch,
        "at": record.at,
        "by": record.author,
        "source": record.source,
        "message": record.message,
        "base": record.base,
        "counts": counts(record),
    }
    out.update(preview("touched", object_ids(record.touched)))
    if removed := object_ids(record.removed):
        out.update(preview("removed", removed))
    meta = dict(record.meta)
    confirm = _confirm(record.input)
    if confirm is not None:
        out["confirm"] = confirm
    ids = meta.pop("ids", None)
    if isinstance(ids, dict) and ids:
        out.update(preview("ids", [f"{ref} -> {i}" for ref, i in ids.items()]))
    out.update(meta)
    text = record.input or ""
    out["input"] = {"bytes": len(text.encode("utf-8")), "lines": len(text.splitlines())}
    return out


def _confirm(text: str | None) -> Any:
    """Commit 交上来的 graph-doc 中的同一性判断 ``confirm``；不是 graph-doc 时为 ``None``。"""
    try:
        doc = yaml.safe_load(text) if text else None
    except yaml.YAMLError:
        return None
    return doc.get("confirm") if isinstance(doc, dict) and "graph-doc" in doc else None


def _input(pinned: Pinned, start: int) -> dict[str, Any]:
    """从第 ``start`` 字节起放得下的若干整行；第一行就放不下时在行内断开。"""
    data = (pinned.record.input or "").encode("utf-8")
    if not 0 <= start <= len(data):
        raise ContractError([{"at": "continuation", "msg": "the meta.continuation returned by the previous call"}])
    ends = [i + 1 for i in range(start, len(data)) if data[i] == ord("\n")]
    if not ends or ends[-1] < len(data):
        ends.append(len(data))
    ends = [e for e in ends if e > start]
    first = data[:start].count(b"\n") + 1

    def view(end: int) -> dict[str, Any]:
        text = data[start:end].decode("utf-8")
        meta = {
            "at": pinned.commit,
            "lines": [first, first + max(text.count("\n") - text.endswith("\n"), 0)] if text else [],
            "total_lines": len(data.decode("utf-8").splitlines()),
            "bytes": [start, end],
            "total_bytes": len(data),
            "continuation": continue_at(end, pinned.commit) if end < len(data) else None,
            "size": {"limit": LIMIT, "used": LIMIT},
        }
        return {"input": text, "meta": meta}

    count = fit(lambda n: view(ends[n - 1]) if n else view(start), len(ends))
    out = view(ends[count - 1]) if count else view(start)
    if count == 1 and size(out) > LIMIT:  # 一行就放不下
        line = data[start : ends[0]].decode("utf-8")
        piece, _ = chunk(line, 0, lambda piece, nxt: size(view(start + len(piece.encode("utf-8")))) <= LIMIT)
        out = view(start + len(piece.encode("utf-8")))
    return finish(out)


def _changes(
    store: Store, pinned: Pinned, node: Any, field: Any, offset: Any, start: int
) -> dict[str, Any]:
    record = pinned.record
    nodes = id_list(node, at="node")
    if field is not None and (nodes is None or len(nodes) != 1):
        raise ContractError([{"at": "node", "msg": "give exactly one node with field"}])
    before = store.graph.state_at(record.parent, branch=pinned.branch)
    after = store.graph.state_at(record.id, branch=pinned.branch)
    candidates = [i for i in (*record.touched, *record.removed) if nodes is None or i in nodes]
    views = changes(candidates, before, after)
    if field is not None:
        if not views:
            raise ContractError([{"at": "node", "msg": f"{nodes[0]} did not change in {record.id}"}])
        return field_view(views[0]["id"], views[0], field, offset, {"at": pinned.commit})
    page = views[start:]

    def view(count: int) -> dict[str, Any]:
        end = start + count
        meta = {
            "at": pinned.commit,
            "returned": count,
            "matched": len(views),
            "continuation": continue_at(end, pinned.commit) if end < len(views) else None,
            "size": {"limit": LIMIT, "used": LIMIT},
        }
        return {"changes": page[:count], "meta": meta}

    return paged(view, len(page), "changes")


SHOW = interface(
    name="Show",
    parameters=schema(
        {
            "commit": STRING,
            "part": {"type": "string", "enum": list(PARTS)},
            "node": STRINGS,
            "field": STRING,
            "offset": {"type": "integer"},
            "continuation": STRING,
        },
        ["commit"],
    ),
    run=show,
)


__all__ = ["SHOW", "show", "summary"]
