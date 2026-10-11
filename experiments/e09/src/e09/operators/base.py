"""算子的定义：每个算子是一个 :class:`Operator`，可以直接作为 Agent 的工具（MCP 入口见 :mod:`e09.mcp`）。

    operator.execute(ctx, request) -> 结构化结果；没有执行时抛出 ContractError（Agent 算子为其子类 OperatorError）
    operator.call(ctx, request)    -> Result：先兜底修复参数（:mod:`.repair`），再执行；把错误转成错误结果，给命令行与
                                      工具入口用

**参数。** ``parameters``（JSON Schema）只含算子自己的参数，不含 ``op``：作为工具注册时工具名就是算子名。请求中
可以带 ``op``（命令行按它分发），须与算子名相同。会话、形成者与形成时间是调用环境的信息，由 :class:`Context`
给出，不是参数。``parameters`` 只描述顶层形状与取值类型，供注册工具与 LLM 理解；细的校验由各算子的代码给出，
不在两处各写一遍。

**返回。** 成功时是各算子的结果（读视图、graph-plan / graph-result 或 artifact-result）。没有完成时一律是
``{status, errors: [{rule, at, msg, ...}]}``：``status`` 为 ``rejected``（请求没有被执行，什么也没有写入）、
``blocked``（Commit 的阻塞项）或 ``conflict``（提交时与并发写入冲突）；``errors`` 的每一项与 Commit 阻塞项同形，
``at`` 指向出错的参数或节点，阻塞项另带 ``candidates`` 与 ``fix``。
"""

from __future__ import annotations

import csv
import io
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any, Literal

from ..artifact.write import REQUEST_KEYS, REQUIRED, OperatorError, Problems, Validate, write_artifact
from ..draft import Workdir, locate_rows, read, read_csv
from ..store.store import ContractError, Store
from ..yamlfmt import dump
from .repair import repair

Family = Literal["db", "agent", "interface"]
FAILED = frozenset({"rejected", "blocked", "conflict"})  # 没有完成的状态


@dataclass(frozen=True, slots=True)
class Context:
    """一次调用的环境。``at`` 是写入的形成时间；``session`` 与 ``formed_by`` 是调用所在的会话与形成者（登录身份），
    ``agent`` 是所用的 Agent 与模型（记入提交的 ``meta.agent``）；
    Agent 算子写入时必须有；``sync`` 在写入后补算向量，为 ``None`` 时不补算；``text`` 是请求原文，写入时记入提交，
    不给时用请求的 YAML。查询向量由 ``store.embed`` 给出。``workdir`` 是调用者的工作目录，草稿文件
    （``payload_file``、``doc_file``，见 :mod:`e09.draft`）只从这里读；为 ``None`` 时不接受草稿文件。"""

    store: Store
    at: str
    session: str | None = None
    formed_by: str | None = None
    agent: str | None = None
    sync: Callable[[], int] | None = None
    text: str | None = None
    workdir: Workdir | None = None


@dataclass(frozen=True, slots=True)
class Result:
    """一次调用的结果：``details`` 是结构化结果，``text`` 是给 LLM 读的 YAML。``status`` 为
    ``rejected``、``blocked`` 或 ``conflict`` 时是错误结果。``repairs`` 是执行前对参数的兜底修复，只给入口记日志，
    不在 ``text`` 中。"""

    details: dict[str, Any]
    repairs: tuple[str, ...] = ()

    @property
    def is_error(self) -> bool:
        return self.details.get("status") in FAILED

    @property
    def text(self) -> str:
        return dump(self.details)


MAX_ERRORS = 30  # 返回的错误条数上限：一份草稿可能每行都错，整份列出会占满写者的上下文


def rejected(errors: list[dict[str, str]], *, status: str = "rejected") -> Result:
    """没有执行的结果：``{status, errors}``。错误超过 :data:`MAX_ERRORS` 条时只列前面的，余下的按规则计数。"""
    items = ContractError(errors, status=status).errors
    if len(items) > MAX_ERRORS:
        rest = Counter(e["rule"] for e in items[MAX_ERRORS:])
        counts = ", ".join(f"{rule} x{n}" for rule, n in rest.most_common())
        msg = f"{len(items) - MAX_ERRORS} more errors not shown ({counts}); fix the ones above, then call again"
        items = [*items[:MAX_ERRORS], {"rule": "more", "at": "", "msg": msg}]
    return Result({"status": status, "errors": items})


Execute = Callable[[Context, Mapping[str, Any]], dict[str, Any]]
CONTEXT_KEYS = ("op", "session", "formed_by")  # 写入请求中不由参数给出的键：工具名与调用环境


@dataclass(frozen=True)
class Operator:
    """一个算子。``family`` 为 ``db``（由中间件执行）或 ``agent``（Agent 给内容，中间件校验后写成 Artifact）；
    版本记录的读取接口（:mod:`e09.interfaces`）也用这个形式，``family`` 为 ``interface``；
    ``validate`` 只有 Agent 算子有。给模型看的文字（标题、说明、参数说明）不在这里，见 :mod:`e09.mcp`。"""

    name: str
    family: Family
    parameters: dict[str, Any]
    execute: Execute
    writes: bool = False
    validate: Validate | None = None

    def call(self, ctx: Context, request: Mapping[str, Any]) -> Result:
        repairs: list[str] = []
        if isinstance(request, Mapping):
            request, repairs = repair(self.parameters, request)
        try:
            result = Result(self.execute(ctx, request))
        except ContractError as exc:
            result = rejected(exc.errors, status=exc.status)
        return replace(result, repairs=tuple(repairs))


def schema(properties: Mapping[str, Any], required: list[str] | tuple[str, ...] = ()) -> dict[str, Any]:
    """对象的 JSON Schema。"""
    out: dict[str, Any] = {"type": "object", "properties": dict(properties), "additionalProperties": False}
    if required:
        out["required"] = list(required)
    return out


def one_or_many(item: Mapping[str, Any]) -> dict[str, Any]:
    """一个值或一组值。"""
    return {"anyOf": [dict(item), {"type": "array", "items": dict(item)}]}


STRING = {"type": "string"}
STRINGS = {"type": "array", "items": STRING}
TEXT = schema({"text": STRING}, ["text"])  # 不是库中对象时直接写出的文字
TERMS = schema({"identifier": STRING, "mention": STRING, "text": STRING})  # 查找用的标识符、提及与描述


def params_of(op: str, parameters: Mapping[str, Any], request: Mapping[str, Any]) -> dict[str, Any]:
    """去掉 ``op`` 后的参数，按 ``parameters`` 的顶层形状核对：未知参数与缺少的必填参数是 ``format`` 错误。

    Raises:
        ContractError: 请求不符合算子契约。
    """
    if not isinstance(request, Mapping):
        raise ContractError([{"rule": "format", "at": "request", "msg": "a mapping of the operator's parameters"}])
    if "op" in request and request["op"] != op:
        raise ContractError([{"rule": "format", "at": "op", "msg": f"this operator is {op}"}])
    params = {k: v for k, v in request.items() if k != "op"}
    accepted = sorted(parameters["properties"])
    if unknown := sorted(set(params) - set(accepted)):
        raise ContractError([{"rule": "format", "at": k, "msg": f"{op} accepts {accepted}"} for k in unknown])
    if missing := [k for k in parameters.get("required", []) if k not in params]:
        raise ContractError([{"rule": "format", "at": k, "msg": "required"} for k in missing])
    return params


def db_operator(
    *,
    name: str,
    parameters: dict[str, Any],
    run: Callable[..., dict[str, Any]],
) -> Operator:
    """只读的中间件算子：核对参数后调用 ``run(store, **params)``。"""

    def execute(ctx: Context, request: Mapping[str, Any]) -> dict[str, Any]:
        return run(ctx.store, **params_of(name, parameters, request))

    return Operator(name, "db", parameters, execute)


def interface(
    *,
    name: str,
    parameters: dict[str, Any],
    run: Callable[..., dict[str, Any]],
) -> Operator:
    """版本记录的读取接口：与只读算子一样调用，来源不同（从版本机制推导，不从 workload 推导）。"""
    return replace(db_operator(name=name, parameters=parameters, run=run), family="interface")


@dataclass(frozen=True)
class DraftForm:
    """Agent 算子的 CSV 草稿（``payload_file``）：文件给出 ``payload[key]``，一行一项。

    ``columns(params)`` 给出表头的列（模板中的顺序）与不可缺少的列，``params`` 不成形时为 ``None``；
    ``example(params)`` 给出模板中的示例行（列名 → 文字）；``item(params, cells)`` 把一行（列名 → 文字，空格
    已去掉）转成 ``payload[key]`` 的一项，与参数中直接写出的形式相同。"""

    key: str
    columns: Callable[[Mapping[str, Any]], tuple[list[str], set[str]] | None]
    example: Callable[[Mapping[str, Any]], dict[str, str]]
    item: Callable[[Mapping[str, Any], dict[str, str]], dict[str, Any]]


def agent_operator(
    *,
    name: str,
    params: dict[str, Any],
    payload: dict[str, Any],
    validate: Validate,
    draft: DraftForm | None = None,
) -> Operator:
    """Agent 算子：``validate`` 检查该算子的 ``params`` 与 ``payload``，其余（共同校验、文档、提交）都经
    :func:`e09.artifact.write.write_artifact`。``params`` 与 ``payload`` 是这两个键的 JSON Schema。

    写入的请求是参数加上 ``op``（算子名）与 ``Context`` 中的 ``session``、``formed_by``；二者缺一时拒绝。

    有 ``draft`` 的算子另接受 ``payload_file``：``payload[draft.key]`` 由工作目录中的 CSV 草稿给出（``payload``
    中可以只写其余的键，如 ``note``）。既没有 ``payload`` 也没有 ``payload_file`` 时返回模板（``status: template``，
    表头与示例行），什么也不写入。内容来自草稿时，报错的位置换算成 ``<文件>:<行号>``，提交的 ``input`` 记调用参数
    与草稿原文，``meta.draft`` 记草稿的路径与哈希。"""
    properties: dict[str, Any] = {
        "title": STRING,
        "abs": STRING,
        "inputs": {"type": "array", "items": STRING},
        "params": params,
        "payload": payload,
    }
    required = [k for k in REQUEST_KEYS if k in REQUIRED and k not in CONTEXT_KEYS]
    if draft is not None:  # 取模板时只需 params；写入时缺少的键由 write_artifact 报告
        properties["payload"] = {k: v for k, v in payload.items() if k != "required"}
        properties["payload_file"] = STRING
        required = ["params"]
    parameters = schema(properties, required)

    def execute(ctx: Context, request: Mapping[str, Any]) -> dict[str, Any]:
        params = params_of(name, parameters, request)
        context = {"session": ctx.session, "formed_by": ctx.formed_by}
        if missing := [k for k, v in context.items() if not v]:
            msg = "set by the caller's context, not a parameter"
            raise ContractError([{"rule": "format", "at": k, "msg": msg} for k in missing])
        given = params.pop("payload_file", None)
        if draft is None or (given is None and "payload" in params):
            full = {"op": name, **params, **context}
            return write_artifact(
                ctx.store, full, {name: validate}, at=ctx.at, text=ctx.text, sync=ctx.sync, agent=ctx.agent
            )

        # 表头由声明给出：声明有问题时（如 key 中的字段没有声明）先报告它们，不给模板、不读文件
        declared = params.get("params") if isinstance(params.get("params"), Mapping) else {}
        problems = Problems()
        validate(declared, {}, problems)
        errors = [e for e in problems.items if e["at"].startswith("params")]
        columns = None if errors else draft.columns(declared)
        if columns is None:
            raise ContractError(errors or [{"rule": "schema", "at": "params", "msg": "a mapping"}])
        header, needed = columns
        if given is None:
            return _template(name, draft, params["params"], header)

        file = read(ctx.workdir, given, "payload_file", ctx.store.material_root)
        inline = params.get("payload", {})
        if not isinstance(inline, Mapping):
            raise ContractError([{"rule": "format", "at": "payload", "msg": "a mapping"}])
        if draft.key in inline:
            msg = f"give {draft.key} either in payload_file or in payload.{draft.key}, not both"
            raise ContractError([{"rule": "format", "at": f"payload.{draft.key}", "msg": msg}])
        table = read_csv(file, header, needed)
        items = [draft.item(params["params"], cells) for _, cells in table.records]
        full = {"op": name, **params, "payload": {**inline, draft.key: items}, **context}
        text = dump({**dict(request), "draft": file.text})
        try:
            return write_artifact(
                ctx.store,
                full,
                {name: validate},
                at=ctx.at,
                text=text,
                sync=ctx.sync,
                agent=ctx.agent,
                draft=file.meta(),
            )
        except OperatorError as exc:
            lines = [line for line, _ in table.records]
            raise OperatorError(locate_rows(exc.errors, file, draft.key, lines), status=exc.status) from exc

    return Operator(name, "agent", parameters, execute, writes=True, validate=validate)


def _template(name: str, draft: DraftForm, params: Mapping[str, Any], header: list[str]) -> dict[str, Any]:
    example = draft.example(params)
    line = io.StringIO()
    csv.writer(line, lineterminator="").writerow([example.get(h, "") for h in header])
    return {
        "status": "template",
        "header": ",".join(header),
        "example": line.getvalue(),
        "next": (
            "Write a CSV file in your working directory: this header on the first line, then one line per "
            f"{'record' if draft.key == 'rows' else 'cell'}; quote values that contain commas. Then call {name} "
            "again with the same params plus abs, inputs and payload_file (the file's path). Nothing was written."
        ),
    }


__all__ = [
    "CONTEXT_KEYS",
    "STRING",
    "STRINGS",
    "TERMS",
    "TEXT",
    "Context",
    "DraftForm",
    "Execute",
    "Family",
    "Operator",
    "Result",
    "agent_operator",
    "db_operator",
    "interface",
    "one_or_many",
    "params_of",
    "rejected",
    "schema",
]
