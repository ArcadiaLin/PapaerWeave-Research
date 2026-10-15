"""版本记录读取的共同约定（docs/designs/v2/versioning_interfaces.md §2.1）：把分支名或提交 id 固定到具体提交，
续取位置带着固定下来的提交。

续取位置是字符串 ``<下一项的序号>@<提交>``；``Diff`` 为 ``<序号>@<from>..<to>``。续取时只读这些固定的提交，
不再解析分支名。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from graph_vc import CommitRecord, GraphVCError

from ..store.store import ContractError, Store

COMMIT = re.compile(r"^commit_\d+$")
_CONTINUATION = re.compile(r"^(\d+)@(commit_\d+)(?:\.\.(commit_\d+))?$")


@dataclass(frozen=True, slots=True)
class Pinned:
    """固定下来的提交，以及它所在分支从最早到它为止的提交。"""

    commit: str
    branch: str
    history: list[CommitRecord]

    @property
    def record(self) -> CommitRecord:
        return self.history[-1]


def pin(store: Store, ref: Any, *, at: str) -> Pinned:
    """``ref`` 是提交 id，或分支名（代表该分支当前的头提交）。

    Raises:
        ContractError: 不是提交 id 或分支名、提交不存在、分支还没有提交。
    """
    if not isinstance(ref, str) or not ref:
        raise ContractError([{"at": at, "msg": "a commit id such as commit_000027, or a branch name such as main"}])
    graph = store.graph
    try:
        branch = graph.get_commit(ref).branch if COMMIT.match(ref) else ref
        commit = ref if COMMIT.match(ref) else graph.head(branch)
    except GraphVCError as exc:
        raise ContractError([{"at": at, "msg": str(exc)}]) from exc
    if commit is None:
        raise ContractError([{"at": at, "msg": f"branch {branch!r} has no commits yet"}])
    history = graph.history(branch)
    ids = [r.id for r in history]
    return Pinned(commit, branch, history[: ids.index(commit) + 1])


def resume(continuation: Any, refs: dict[str, Any], *, pins: int = 1) -> tuple[int, list[str]] | None:
    """解析续取位置：``(序号, 固定的提交)``；没有续取位置时为 ``None``。``refs`` 是请求中的引用参数（参数名 →
    值），给的是提交 id 时须与续取位置中的相同。

    Raises:
        ContractError: 续取位置不是上一次结果给出的。
    """
    if continuation is None:
        return None
    m = _CONTINUATION.match(continuation) if isinstance(continuation, str) else None
    commits = [c for c in (m.groups()[1:] if m else ()) if c]
    if m is None or len(commits) != pins:
        raise ContractError([{"at": "continuation", "msg": "the meta.continuation returned by the previous call"}])
    for (name, ref), commit in zip(refs.items(), commits, strict=True):
        if isinstance(ref, str) and COMMIT.match(ref) and ref != commit:
            msg = f"this continuation is for {name}={commit}; repeat the previous call's parameters"
            raise ContractError([{"at": "continuation", "msg": msg}])
    return int(m.group(1)), commits


def continue_at(offset: int, *commits: str) -> str:
    """续取位置的写法。"""
    return f"{offset}@{'..'.join(commits)}"


def id_list(value: Any, *, at: str) -> list[str] | None:
    """一个 id 或一组 id（去重，保持顺序）；没有给出时为 ``None``。

    Raises:
        ContractError: 不是 id 或非空的 id 列表。
    """
    if value is None:
        return None
    ids = [value] if isinstance(value, str) else value
    if not isinstance(ids, list) or not ids or not all(isinstance(i, str) and i for i in ids):
        raise ContractError([{"at": at, "msg": "an id or a non-empty list of ids"}])
    return list(dict.fromkeys(ids))


def paging(value: Any, *, at: str, low: int = 0) -> int:
    """非负（或不小于 ``low``）的整数参数。

    Raises:
        ContractError: 不是这样的整数。
    """
    if not isinstance(value, int) or isinstance(value, bool) or value < low:
        raise ContractError([{"at": at, "msg": f"an integer >= {low}"}])
    return value


__all__ = ["COMMIT", "Pinned", "continue_at", "id_list", "paging", "pin", "resume"]
