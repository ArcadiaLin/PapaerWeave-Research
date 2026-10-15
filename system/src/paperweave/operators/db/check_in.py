"""CheckIn：按类型契约检入共同产物（docs/designs/v2/operators.md §4.1）。

    CheckIn(artifact_doc, update_abstract, confirm?, reason?)
      -> {status: checked | committed | unchanged, ...}

``artifact_doc`` 是写者工作目录中的文档路径，或路径列表（:mod:`paperweave.draft` 的路径规则）。省略 ``confirm`` 时只
校验：返回每份文档的改动与改动的他人内容，不写入；``confirm: true`` 时写入。改动或删除了他人写的行时须给出
``reason``。设计中写作 ``confirm: {reason}``；工具的每个顶层参数只声明一种 JSON 类型（见 operators.md §9），所以
拆成布尔的 ``confirm`` 与文字的 ``reason`` 两个参数。会话与编辑者由调用环境给出。流程见
:mod:`paperweave.artifact.checkin`。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ...artifact.checkin import check_in
from ...draft import read
from ...store.store import ContractError
from ..base import STRING, STRINGS, Context, Operator, params_of, schema

PARAMETERS = schema(
    {"artifact_doc": STRINGS, "update_abstract": STRING, "confirm": {"type": "boolean"}, "reason": STRING},
    ["artifact_doc", "update_abstract"],
)


def execute(ctx: Context, request: Mapping[str, Any]) -> dict[str, Any]:
    params = params_of("CheckIn", PARAMETERS, request)
    context = {"session": ctx.session, "formed_by": ctx.formed_by}
    if missing := [k for k, v in context.items() if not v]:
        msg = "set by the caller's context, not a parameter"
        raise ContractError([{"rule": "format", "at": k, "msg": msg} for k in missing])
    given = params["artifact_doc"]
    paths = [given] if isinstance(given, str) else given
    if not isinstance(paths, list) or not paths:
        raise ContractError([{"rule": "format", "at": "artifact_doc", "msg": "a path or a list of paths"}])
    drafts = [read(ctx.workdir, p, f"artifact_doc[{i}]", ctx.store.material_root) for i, p in enumerate(paths)]
    abstract = params["update_abstract"]
    if not isinstance(abstract, str):
        raise ContractError([{"rule": "format", "at": "update_abstract", "msg": "a text"}])
    reason = params.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise ContractError([{"rule": "format", "at": "reason", "msg": "a text"}])
    return check_in(
        ctx.store,
        drafts,
        abstract,
        confirm=params.get("confirm") is True,
        reason=reason,
        at=ctx.at,
        session=str(ctx.session),
        formed_by=str(ctx.formed_by),
        agent=ctx.agent,
        sync=ctx.sync,
    )


CHECK_IN = Operator(
    name="CheckIn", family="db", parameters=PARAMETERS, execute=execute, writes=True, destructive=False
)

__all__ = ["CHECK_IN", "PARAMETERS", "execute"]
