"""Commit：提交一份 graph-doc（docs/experiments/e09/operators/commit.md）。

    Commit(doc | doc_file, source?, apply?: true, message?, base?, dedup?: true)
      -> graph-plan（dry_run、有阻塞项或没有变化）| graph-result（提交后）

``doc`` 是 graph-doc 文本；``doc_file`` 是写者工作目录中的 graph-doc 草稿（:mod:`e09.draft`），二者给一个。
用草稿时，阻塞项与提示的位置换算成 ``<文件>:<行号> (<位置>)``，提交的 ``meta.draft`` 记草稿的路径与哈希。
``apply`` 默认提交：先做 dry_run，有阻塞项时返回 graph-plan、不写入，没有时直接提交；``apply: false`` 只做
dry_run。命令行入口（:mod:`e09.cli`）总是显式给出 ``apply``，仍须加 ``--apply`` 才提交。

``source`` 省略时记为调用所在的会话（``session:<id>``）；没有会话时必须给出。写入管线在 :mod:`e09.commit`：
解析 → 翻译 → 求差 → 写入后检查 →（apply 时）分配 id 并经 graph-vc 提交。查重（Resolve）与向量补算用 ``E09_NEO4J_URI`` 所指的同一个库。没有版本记录的旧库一律拒绝。
``status`` 为 ``blocked`` 或 ``conflict`` 时是错误结果，``errors`` 列出阻塞项或冲突。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import httpx
from neo4j import Driver

from graph_vc import ConflictError, VersionedGraph

from ... import draft
from ...artifact.related import related
from ...commit.reader import Neo4jReader
from ...commit.report import conflict, plan, result
from ...commit.review import ResolveDeduper
from ...commit.submit import apply, prepare
from ...commit.translate import Context as CommitContext
from ...store import ContractError
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
    meta: Mapping[str, Any] | None = None,
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
        prepared, record = apply(text, graph, ctx, message=message, base=base, meta=meta)
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
        "doc_file": STRING,
        "source": {"type": "string"},
        "apply": {"type": "boolean"},
        "message": {"type": "string"},
        "base": {"type": "string"},
        "dedup": {"type": "boolean"},
    },
    (),
)


def execute(call: Context, request: Mapping[str, Any]) -> dict[str, Any]:
    params = params_of("Commit", PARAMETERS, request)
    if ("doc" in params) == ("doc_file" in params):
        raise ContractError([{"rule": "format", "at": "doc", "msg": "give either doc (the YAML text) or doc_file"}])
    file = None
    if "doc_file" in params:
        file = draft.read(call.workdir, params["doc_file"], "doc_file", call.store.material_root)
        if syntax := draft.yaml_syntax(file):
            raise ContractError([syntax])
        text = file.text
    else:
        doc = params["doc"]
        text = doc if isinstance(doc, str) else dump(doc)
    source = params.get("source") or (f"session:{call.session}" if call.session else None)
    if source is None:
        raise ContractError([{"rule": "format", "at": "source", "msg": "give source: where this knowledge comes from"}])
    store = call.store
    ctx = CommitContext(
        reader=Neo4jReader(store.graph, store.driver, database=store.database),
        source=source,
        at=call.at,
        material_root=store.material_root,
        deduper=ResolveDeduper() if params.get("dedup", True) else None,
        user=call.formed_by,
        agent=call.agent,
    )
    out = run(
        text,
        graph=store.graph,
        driver=store.driver,
        ctx=ctx,
        commit=bool(params.get("apply", True)),
        message=params.get("message", ""),
        base=params.get("base"),
        database=store.database,
        embed=call.sync,
        meta={"draft": file.meta()} if file else None,
    )
    if out.get("status") == "committed" and (shared := related(store, out["commit"])):
        out["related_artifacts"] = shared
    return draft.locate_doc(out, file) if file else out


COMMIT = Operator(
    name="Commit",
    family="db",
    parameters=PARAMETERS,
    execute=execute,
    writes=True,
)


__all__ = ["COMMIT", "PARAMETERS", "execute", "run"]
