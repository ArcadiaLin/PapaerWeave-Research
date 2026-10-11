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

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any, Literal

from ..artifact.write import REQUEST_KEYS, REQUIRED, Validate, write_artifact
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
    不给时用请求的 YAML。查询向量由 ``store.embed`` 给出。"""

    store: Store
    at: str
    session: str | None = None
    formed_by: str | None = None
    agent: str | None = None
    sync: Callable[[], int] | None = None
    text: str | None = None


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


def rejected(errors: list[dict[str, str]], *, status: str = "rejected") -> Result:
    """没有执行的结果：``{status, errors}``。"""
    return Result({"status": status, "errors": ContractError(errors, status=status).errors})


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


def agent_operator(
    *,
    name: str,
    params: dict[str, Any],
    payload: dict[str, Any],
    validate: Validate,
) -> Operator:
    """Agent 算子：``validate`` 检查该算子的 ``params`` 与 ``payload``，其余（共同校验、文档、提交）都经
    :func:`e09.artifact.write.write_artifact`。``params`` 与 ``payload`` 是这两个键的 JSON Schema。

    写入的请求是参数加上 ``op``（算子名）与 ``Context`` 中的 ``session``、``formed_by``；二者缺一时拒绝。"""
    parameters = schema(
        {
            "title": STRING,
            "abs": STRING,
            "inputs": {"type": "array", "items": STRING},
            "params": params,
            "payload": payload,
        },
        [k for k in REQUEST_KEYS if k in REQUIRED and k not in CONTEXT_KEYS],
    )

    def execute(ctx: Context, request: Mapping[str, Any]) -> dict[str, Any]:
        params = params_of(name, parameters, request)
        context = {"session": ctx.session, "formed_by": ctx.formed_by}
        if missing := [k for k, v in context.items() if not v]:
            msg = "set by the caller's context, not a parameter"
            raise ContractError([{"rule": "format", "at": k, "msg": msg} for k in missing])
        full = {"op": name, **params, **context}
        return write_artifact(
            ctx.store, full, {name: validate}, at=ctx.at, text=ctx.text, sync=ctx.sync, agent=ctx.agent
        )

    return Operator(name, "agent", parameters, execute, writes=True, validate=validate)


__all__ = [
    "CONTEXT_KEYS",
    "STRING",
    "STRINGS",
    "TERMS",
    "TEXT",
    "Context",
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
