"""commit 返回的相关共同产物（docs/designs/v2/operators.md §3.5）：让写者知道刚写的内容与哪些产物有关。

当前只沿一条路径：本次提交触及的 Experiment（新建、修改，或增删过关系）→ 它 ``USES`` 的评测数据集 → 以该数据集为
身份键的 ``Leaderboard``；另列出还没有 Leaderboard 的数据集。这是查询结果，不是要求：不提示写者去维护。
"""

from __future__ import annotations

from typing import Any

from ..store.store import Store
from .versions import history

LIST_MAX = 20


def related(store: Store, commit: str) -> dict[str, Any] | None:
    """提交 ``commit`` 触及的 Experiment 所用数据集上的 Leaderboard；没有触及带评测数据集的 Experiment 时为
    ``None``。"""
    used = store.query(
        """MATCH (:Commit {id: $commit})-[:TOUCHED]->(e:Experiment)-[:USES {role: 'evaluation_data'}]->(d)
           RETURN d.id AS dataset, d.name AS name, collect(DISTINCT e.id) AS experiments ORDER BY dataset""",
        commit=commit,
    )
    if not used:
        return None
    datasets = [r["dataset"] for r in used]
    boards = store.query(
        """MATCH (a:Artifact {op: 'Leaderboard'}) WHERE split(a.key, '|')[2] IN $datasets
           RETURN a.id AS id, a.title AS title, split(a.key, '|')[2] AS dataset ORDER BY id""",
        datasets=[d.casefold() for d in datasets],
    )
    covered = {b["dataset"] for b in boards}
    out: dict[str, Any] = {
        "experiments": sorted({e for r in used for e in r["experiments"]}),
        "leaderboards": [_board(store, b) for b in boards[:LIST_MAX]],
    }
    if len(boards) > LIST_MAX:
        out["more"] = f"{len(boards)} leaderboards in all; find the others with search, kind: [Leaderboard]"
    if missing := [
        {"dataset": r["dataset"], "name": r["name"]} for r in used if r["dataset"].casefold() not in covered
    ]:
        out["no_leaderboard_yet"] = missing
    return out


def _board(store: Store, row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"artifact": row["id"], "title": row["title"]}
    versions = history(store, row["id"])
    if versions:
        latest = versions[-1]
        out.update(version=latest.number, last_edited_by=latest.author, commit=latest.commit)
    return out


__all__ = ["related"]
