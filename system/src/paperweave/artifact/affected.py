"""commit 返回的受影响产物：本次提交让哪些产物新出现了可能过期的原因，告诉这次的写者。

判断全部复用 :func:`paperweave.artifact.stale.stale`，不另加语义：提交前对可能受影响的产物算一次 ``_stale``
（:func:`watch`），提交后再算一次（:func:`affected`），只报新出现的原因（按 ``ref`` 与 ``reason`` 比较）。之前
已经报过的原因（如早先修订过的记录、早已不在表中的论文）不再重复。

候选产物：

- graph-doc 提交（:func:`watch`）：``USED`` 指向本次触及（含删除）的节点的产物，本次触及或增删过 ``USES`` 的
  Experiment 所用数据集上的 Leaderboard；
- 产物提交（:func:`watch_users`）：引用了本次更新的产物的产物（所引的是旧版本，报 ``superseded``）；
- 以及沿 ``USED`` 反向用到这些产物的产物（``stale input`` 由此传递）。

这是信息，不是要求：写者可以顺手更新，也可以留给读到它的人。
"""

from __future__ import annotations

from typing import Any

from graph_vc import Changeset

from ..store.store import Store
from .stale import stale

LIST_MAX = 5
NOTE = (
    "These artifacts use what this commit changed and may now be out of date. Updating them is up to you: "
    "checkout one to revise it, or leave it; readers see the same reasons under _stale."
)

Snapshot = dict[str, set[tuple[str, str]]]


def watch(store: Store, changeset: Changeset) -> Snapshot:
    """提交前：可能受 ``changeset`` 影响的产物 → 它们当前可能过期的原因。"""
    nodes = {n.id for n in changeset.nodes} | {end for e in changeset.edges for end in (e.key.src, e.key.dst)}
    datasets = {e.key.dst for e in changeset.edges if e.key.type == "USES"}
    rows = store.query(
        """UNWIND $ids AS id MATCH (a:Artifact)-[:USED]->({id: id}) RETURN a.id AS id
           UNION
           UNWIND $ids AS id MATCH (:Experiment {id: id})-[:USES]->(d:Dataset) WITH collect(d.id) + $datasets AS ds
           UNWIND ds AS d MATCH (a:Artifact {op: 'Leaderboard'}) WHERE split(a.key, '|')[2] = toLower(d)
           RETURN a.id AS id""",
        ids=sorted(nodes),
        datasets=sorted(datasets),
    )
    return _snapshot(store, {r["id"] for r in rows})


def watch_users(store: Store, artifacts: set[str]) -> Snapshot:
    """提交前：引用了 ``artifacts``（本次要更新的产物）的产物 → 它们当前可能过期的原因。"""
    rows = store.query(
        "UNWIND $ids AS id MATCH (a:Artifact)-[:USED]->(:Artifact {id: id}) RETURN DISTINCT a.id AS id",
        ids=sorted(artifacts),
    )
    return _snapshot(store, {r["id"] for r in rows})


def _snapshot(store: Store, direct: set[str]) -> Snapshot:
    """``direct`` 与沿 ``USED`` 反向用到它们的产物 → 它们当前可能过期的原因。"""
    users = store.query(
        """UNWIND $ids AS id MATCH (a:Artifact)-[:USED*1..]->(:Artifact {id: id}) RETURN DISTINCT a.id AS id""",
        ids=sorted(direct),
    )
    candidates = sorted(set(direct) | {r["id"] for r in users})
    return {a: {_key(r) for r in rs} for a, rs in stale(store, candidates).items()}


def affected(store: Store, before: Snapshot) -> dict[str, Any] | None:
    """提交后：``before`` 中的产物新出现的可能过期原因 ``{note, artifacts, more?}``；没有时为 ``None``。"""
    if not before:
        return None
    found = {
        a: [_text(r) for r in rs if _key(r) not in before.get(a, set())] for a, rs in stale(store, before).items()
    }
    found = {a: rs for a, rs in found.items() if rs}
    if not found:
        return None
    rows = store.query(
        "UNWIND $ids AS id MATCH (a:Artifact {id: id}) RETURN a.id AS id, a.title AS title, a.op AS op",
        ids=sorted(found),
    )
    listed = [{"artifact": r["id"], "title": r["title"], "type": r["op"], "reasons": found[r["id"]]} for r in rows]
    out: dict[str, Any] = {"note": NOTE, "artifacts": listed[:LIST_MAX]}
    if len(listed) > LIST_MAX:
        out["more"] = f"{len(listed)} artifacts in all: " + ", ".join(r["artifact"] for r in listed[LIST_MAX:])
    return out


def _key(reason: dict[str, str]) -> tuple[str, str]:
    return reason["ref"], reason["reason"]


def _text(reason: dict[str, str]) -> str:
    """``exp_0001 revised``、``paper_0002 uncovered (exp_0002)``。"""
    text = f"{reason['ref']} {reason['reason']}"
    return f"{text} ({reason['experiments']})" if reason["reason"] == "uncovered" else text


__all__ = ["LIST_MAX", "Snapshot", "affected", "watch", "watch_users"]
