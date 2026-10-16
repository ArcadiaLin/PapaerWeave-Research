"""commit：提交工作目录中的文件——graph-doc（改证据节点与关系）与产物文档（新建或修改共同产物）走同一个工具。

    commit(files, message, reason?, dry_run?: false)
      -> {status: ready | committed | noop | blocked | conflict, ...}

- ``files``：写者工作目录中的文件（:mod:`paperweave.draft` 的路径规则）。以 ``graph-doc:`` 开头的 YAML 是 graph-doc
  （一次至多一份：``$`` 名只在一份文件内有效），其余按产物文档的头部取类型（:mod:`paperweave.artifact`）。
- 先对全部文件做一遍检查；任何一份有阻塞项时什么都不写，阻塞项的位置换算成 ``<文件>:<行号>``。都通过时依次写入：
  graph-doc 一个提交、产物文档一个提交。``dry_run: true`` 只检查。
- ``message`` 是提交说明，产物文档的 ``update_abstract`` 也用它；改动或删除了他人写的产物行时要给 ``reason``。
- 写入身份与来源由调用环境给出（登录身份、会话），不是参数。提交后补算检索用的派生字段，失败只提示。

写入管线在 :mod:`paperweave.commit`（graph-doc）与 :mod:`paperweave.artifact.checkin`（产物）。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from graph_doc import GraphDocError, load
from graph_vc import ConflictError

from ... import draft
from ...artifact.checkin import check_in
from ...artifact.related import related
from ...commit.reader import Neo4jReader
from ...commit.report import conflict, plan, result
from ...commit.submit import apply, prepare
from ...commit.translate import Context as CommitContext
from ...query.dedup import SearchDeduper
from ...store import ContractError
from ...store.database import check_versioned, setup_database
from ..base import STRING, STRINGS, Context, Operator, params_of, schema

PARAMETERS = schema(
    {"files": STRINGS, "message": STRING, "reason": STRING, "dry_run": {"type": "boolean"}},
    ["files", "message"],
)


def execute(ctx: Context, request: Mapping[str, Any]) -> dict[str, Any]:
    params = params_of("commit", PARAMETERS, request)
    message = params["message"]
    if not isinstance(message, str) or not message.strip():
        raise ContractError([{"rule": "format", "at": "message", "msg": "one line: what this commit does"}])
    given = params["files"]
    paths = [given] if isinstance(given, str) else given
    if not isinstance(paths, list) or not paths or not all(isinstance(p, str) for p in paths):
        raise ContractError([{"rule": "format", "at": "files", "msg": "a list of file paths in your working directory"}])
    if ctx.workdir is None:
        raise ContractError([{"rule": "format", "at": "files[0]", "msg": "no working directory to read files from here"}])
    files = [draft.read(ctx.workdir, p, f"files[{i}]", ctx.store.material_root) for i, p in enumerate(paths)]
    docs = [f for f in files if _is_graph_doc(f.text)]
    artifacts = [f for f in files if f not in docs]
    if len(docs) > 1:
        msg = "one graph-doc per commit ($ names are local to a file); merge them, or commit them one by one"
        raise ContractError([{"rule": "format", "at": "files", "msg": msg}])
    for doc in docs:
        if syntax := draft.yaml_syntax(doc):
            raise ContractError([syntax])
    if not ctx.formed_by:
        raise ContractError([{"rule": "identity", "at": "", "msg": "the server was started without a user"}])

    store = ctx.store
    check_versioned(store.driver, database=store.database)
    setup_database(store.graph, store.driver, database=store.database)  # 空库第一次提交前建立版本记录与索引；可重复
    graph_ctx = CommitContext(
        reader=Neo4jReader(store.graph, store.driver, database=store.database),
        source=f"session:{ctx.session}" if ctx.session else "cli",
        at=ctx.at,
        material_root=store.material_root,
        user=ctx.formed_by,
        deduper=SearchDeduper(store),
        agent=ctx.agent,
    )
    art_args = {
        "at": ctx.at,
        "session": str(ctx.session),
        "formed_by": str(ctx.formed_by),
        "agent": ctx.agent,
        "sync": ctx.sync,
    }

    # 1. 全部检查
    out: dict[str, Any] = {}
    blocked = False
    doc = docs[0] if docs else None
    if doc is not None:
        checked = draft.locate_doc(plan(prepare(doc.text, graph_ctx), graph_ctx.reader), doc)
        out["graph_doc"] = {"file": doc.path, **checked}
        blocked |= checked["status"] == "blocked"
    if artifacts:
        try:
            out["artifacts"] = check_in(
                store, artifacts, message, confirm=False, reason=params.get("reason"), **art_args
            )
        except ContractError as exc:
            out["artifacts"] = {"status": exc.status, "errors": exc.errors}
            blocked = True
    if blocked:
        return _summary(out, "blocked")
    if all(part.get("status") in ("noop", "unchanged") for part in (out.get("graph_doc"), out.get("artifacts")) if part):
        return _summary(out, "noop")
    if params.get("dry_run") is True:
        return _summary(out, "ready")

    # 2. 写入
    if doc is not None and out["graph_doc"]["status"] == "ready":
        try:
            prepared, record = apply(doc.text, store.graph, graph_ctx, message=message, meta={"draft": doc.meta()})
        except ConflictError as exc:
            out["graph_doc"] = {"file": doc.path, **conflict(exc)}
            return _summary(out, "conflict")
        if record is None:
            out["graph_doc"] = {"file": doc.path, **draft.locate_doc(plan(prepared, graph_ctx.reader), doc)}
            return _summary(out, "blocked")
        names = _names(prepared)
        out["graph_doc"] = {"file": doc.path, **draft.locate_doc(result(prepared, record, names), doc)}
        if shared := related(store, record.id):
            out["graph_doc"]["related_artifacts"] = shared
    if artifacts:
        try:
            out["artifacts"] = check_in(store, artifacts, message, confirm=True, reason=params.get("reason"), **art_args)
        except ContractError as exc:
            out["artifacts"] = {"status": exc.status, "errors": exc.errors}
            return _summary(out, exc.status)
    if ctx.sync is not None and doc is not None and out["graph_doc"].get("status") == "committed":
        try:
            ctx.sync()
        except Exception as exc:  # noqa: BLE001 —— 派生字段补算失败不影响已完成的提交
            out.setdefault("warnings", []).append(f"search index not updated ({exc}); it is retried on the next commit")
    statuses = {part.get("status") for part in (out.get("graph_doc"), out.get("artifacts")) if part}
    return _summary(out, "committed" if statuses & {"committed"} else "noop")


def _is_graph_doc(text: str) -> bool:
    try:
        data = load(text)
    except GraphDocError:
        return text.lstrip().startswith("graph-doc:")
    return isinstance(data, dict) and "graph-doc" in data


def _names(prepared: Any) -> dict[str, str]:
    """``$`` 名 → 新节点的名称（提交结果中 ``$名 → id (名称)``）。"""
    doc = prepared.document
    out = {}
    for ref in prepared.ids:
        node = doc.create.get(ref) if doc is not None else None
        name = node.props.get("name") if node is not None else None
        if isinstance(name, str):
            out[ref] = name
    return out


def _summary(out: dict[str, Any], status: str) -> dict[str, Any]:
    return {"status": status, **out}


COMMIT = Operator(name="commit", family="db", parameters=PARAMETERS, execute=execute, writes=True)

__all__ = ["COMMIT", "PARAMETERS", "execute"]
