"""Commit：提交一份 graph-doc（docs/experiments/e09/operators/commit.md）。

    Commit(doc: <graph-doc>, source, apply?: false, message?, base?, dedup?: true)
      -> graph-plan（dry_run，或没有变化）| graph-result（提交后）

不加 ``apply`` 时只做 dry_run。写入管线在 :mod:`e09.commit`：解析 → 翻译 → 求差 → 写入后检查 →（apply 时）分配
id 并经 graph-vc 提交。查重（Resolve）与向量补算用 ``E09_NEO4J_URI`` 所指的同一个库。没有版本记录的旧库一律拒绝。
``status`` 为 ``blocked`` 或 ``conflict`` 时是错误结果，``errors`` 列出阻塞项或冲突。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import httpx
from neo4j import Driver

from graph_vc import ConflictError, VersionedGraph

from ...commit.reader import Neo4jReader
from ...commit.report import conflict, plan, result
from ...commit.review import ResolveDeduper
from ...commit.submit import apply, prepare
from ...commit.translate import Context as CommitContext
from ...store.database import check_versioned, setup_database
from ...yamlfmt import dump
from ..base import STRING, Context, Operator, params_of, schema


def run(
    text: str,
    *,
    graph: VersionedGraph,
    driver: Driver,
    ctx: CommitContext,
    commit: bool,
    message: str = "",
    base: str | None = None,
    database: str | None = None,
    embed: Callable[[], int] | None = None,
) -> dict[str, Any]:
    """dry_run 或提交一份 graph-doc，返回 graph-plan 或 graph-result。

    提交后调用 ``embed`` 补算向量。向量是提交之后补算的派生属性，补算失败（如向量服务不可用）
    不影响已完成的提交，只在结果中提示；之后可以用 ``make embed`` 再补。

    Raises:
        UnversionedDatabaseError: 库中有数据但没有版本记录。
    """
    check_versioned(driver, database=database)
    if not commit:
        return plan(prepare(text, ctx), ctx.reader)
    setup_database(graph, driver, database=database)
    try:
        prepared, record = apply(text, graph, ctx, message=message, base=base)
    except ConflictError as exc:
        return conflict(exc)
    if record is None:
        return plan(prepared, ctx.reader)
    out = result(prepared, record)
    if embed is not None:
        try:
            embed()
        except (httpx.HTTPError, ValueError) as exc:
            warning = {"rule": "embedding", "at": record.id, "msg": f"embeddings not synced ({exc}); run make embed"}
            out.setdefault("warnings", []).append(warning)
    return out


PARAMETERS = schema(
    {
        "doc": STRING,
        "source": {"type": "string"},
        "apply": {"type": "boolean"},
        "message": {"type": "string"},
        "base": {"type": "string"},
        "dedup": {"type": "boolean"},
    },
    ["doc", "source"],
)


def execute(call: Context, request: Mapping[str, Any]) -> dict[str, Any]:
    params = params_of("Commit", PARAMETERS, request)
    doc = params["doc"]
    text = doc if isinstance(doc, str) else dump(doc)
    store = call.store
    ctx = CommitContext(
        reader=Neo4jReader(store.graph, store.driver, database=store.database),
        source=params["source"],
        at=call.at,
        material_root=store.material_root,
        deduper=ResolveDeduper() if params.get("dedup", True) else None,
        user=call.formed_by,
        agent=call.agent,
    )
    return run(
        text,
        graph=store.graph,
        driver=store.driver,
        ctx=ctx,
        commit=bool(params.get("apply", False)),
        message=params.get("message", ""),
        base=params.get("base"),
        database=store.database,
        embed=call.sync,
    )


COMMIT = Operator(
    name="Commit",
    family="db",
    parameters=PARAMETERS,
    execute=execute,
    writes=True,
)


__all__ = ["COMMIT", "PARAMETERS", "execute", "run"]
