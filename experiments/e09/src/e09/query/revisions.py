"""有据层记录最近一次修订的只读字段 ``_revised``：在读取时从提交记录推算，不存在节点上。

修订是带 ``confirm.<id>.revise`` 的提交（:mod:`e09.commit.revision`），锚点与理由记在提交的 ``meta.revisions``。
读者不会去查版本历史，所以最近一次修订随记录一起给出：``{commit, by, at, reason, anchor}``（删除不留记录，没有
``anchor``）。更早的修订与旧值用 Log / Show / Diff 查看。
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from ..store import Store


def latest_revisions(store: Store, ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    """``ids`` 中被修订过的记录 → 最近一次修订；没有修订过的不出现。"""
    rows = store.query(
        """UNWIND $ids AS id MATCH (c:Commit)-[:TOUCHED]->({id: id})
           WHERE c.meta CONTAINS '"revisions"' AND c.meta CONTAINS id
           RETURN id, c.id AS commit, c.seq AS seq, c.author AS by, c.at AS at, c.meta AS meta ORDER BY seq""",
        ids=sorted(set(ids)),
    )
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        entry = json.loads(row["meta"]).get("revisions", {}).get(row["id"])
        if entry:
            out[row["id"]] = {"commit": row["commit"], "by": row["by"], "at": row["at"], **entry}
    return out


__all__ = ["latest_revisions"]
