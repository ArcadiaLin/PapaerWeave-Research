"""读取算子共用的环境：连接、版本化的图、材料根目录与查询向量的入口，以及契约错误。"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from neo4j import Driver, RoutingControl

from graph_vc import RESERVED_LABELS, GraphVCError, VersionedGraph

from ..model.schema import ARTIFACT, kind_of

Embed = Callable[[list[str]], list[list[float]]]


class ContractError(ValueError):
    """调用没有被执行，什么也没有写入：未知参数、类型不符的引用、该类别不支持的条件、图模型中不存在的端点组合等。

    ``errors`` 是 ``[{rule, at, msg}]``，与 Commit 阻塞项的形状相同；``at`` 指向出错的参数，没有给 ``rule`` 的
    记为 ``schema``（参数的取值）。``status`` 是返回给调用者的状态：``rejected``，或写入时与并发写入冲突的
    ``conflict``。
    """

    def __init__(self, errors: list[dict[str, str]], *, status: str = "rejected"):
        self.errors = [{"rule": e.get("rule", "schema"), "at": e["at"], "msg": e["msg"]} for e in errors]
        self.status = status
        super().__init__("; ".join(f"{e['at']}: {e['msg']}" for e in self.errors))


@dataclass(frozen=True, slots=True)
class Store:
    """``embed`` 为查询文本算向量；为 ``None`` 时语义通道关闭（记入 coverage）。"""

    driver: Driver
    graph: VersionedGraph
    material_root: Path
    database: str | None = None
    embed: Embed | None = None

    def query(self, cypher: str, **params: Any) -> list[dict[str, Any]]:
        records = self.driver.execute_query(
            cypher, params, database_=self.database, routing_=RoutingControl.READ
        ).records
        return [r.data() for r in records]

    def kinds(self, ids: Iterable[str]) -> dict[str, str | None]:
        """库中存在的 id → kind；Artifact 为 ``Artifact``，系统记录为 ``None``，版本记录不算存在。"""
        rows = self.query(
            """UNWIND $ids AS id MATCH (n {id: id}) WHERE none(l IN labels(n) WHERE l IN $reserved)
               RETURN n.id AS id, labels(n) AS labels""",
            ids=sorted(set(ids)),
            reserved=sorted(RESERVED_LABELS),
        )
        return {r["id"]: _kind(frozenset(r["labels"])) for r in rows}

    def snapshot(self) -> str | None:
        """读取所在的提交：主分支的 head；库还没有版本记录时为 ``None``。"""
        try:
            return self.graph.head()
        except GraphVCError:
            return None

    def stable(self, before: str | None) -> tuple[str | None, dict[str, str]]:
        """读取结束时核对头提交：仍是读取开始时的 ``before`` 时返回 ``(before, {})``；读取期间有写入时，结果不一定
        属于哪一个提交，返回 ``(None, 说明)``，说明放进 ``diagnostics``。"""
        if self.snapshot() == before:
            return before, {}
        return None, {"snapshot": "the store changed during this read; repeat the call to get a pinned snapshot"}


def _kind(labels: frozenset[str]) -> str | None:
    return kind_of(labels) or (ARTIFACT if ARTIFACT in labels else None)


__all__ = ["ContractError", "Embed", "Store"]
