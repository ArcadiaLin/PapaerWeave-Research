"""算子作为工具的接口：参数只含算子自己的参数，调用环境由 Context 给出，没有完成时一律 {status, errors}。

不连库：这里的请求都在执行前被拒绝。
"""

from __future__ import annotations

from typing import Any

import pytest

from paperweave.operators import Context
from paperweave.tools import TOOLS as OPERATORS
from paperweave.tools import call

AT = "2026-10-05T12:00:00+00:00"
NO_STORE: Any = None  # 被拒绝的请求不会用到库


def _typed(schema: dict[str, Any]) -> bool:
    """顶层参数有确定的 JSON 类型。只写 anyOf 时，按 type 转换参数的工具调用解析器（如 sglang 对 qwen）会把值当作
    字符串，数组与对象因此变成 JSON 文本。"""
    return isinstance(schema.get("type"), str)


@pytest.mark.parametrize("name", list(OPERATORS))
def test_parameters_are_the_operators_own(name: str) -> None:
    parameters = OPERATORS[name].parameters
    assert parameters["type"] == "object" and parameters["additionalProperties"] is False
    assert not {"op", "session", "formed_by"} & set(parameters["properties"])  # 工具名与调用环境不是参数
    assert set(parameters.get("required", [])) <= set(parameters["properties"])
    untyped = [k for k, v in parameters["properties"].items() if not _typed(v)]
    assert untyped == []


def rejected(request: dict[str, Any], ctx: Context | None = None) -> list[tuple[str, str]]:
    out = call(ctx or Context(NO_STORE, AT), request)
    assert out.is_error and set(out.details) == {"status", "errors"}
    assert out.details["status"] == "rejected"
    assert all(set(e) == {"rule", "at", "msg"} for e in out.details["errors"])
    return [(e["rule"], e["at"]) for e in out.details["errors"]]


CHECKIN = {"artifact_doc": ["artifacts/a.md"], "update_abstract": "x"}


@pytest.mark.parametrize(
    ("request_", "ctx", "found"),
    [
        ({"op": "Rank"}, None, [("format", "op")]),
        ({"op": "Search", "type": "Entity", "colour": "red"}, None, [("format", "colour")]),
        ({"op": "Traverse"}, None, [("format", "start")]),
        ({"op": "Commit", "doc": "graph-doc: v0.1"}, None, [("format", "source")]),
        # 会话与形成者由调用环境给出：缺了拒绝，写在请求中也拒绝
        ({"op": "CheckIn", **CHECKIN}, None, [("format", "session"), ("format", "formed_by")]),
        ({"op": "CheckIn", **CHECKIN}, Context(NO_STORE, AT, session="s"), [("format", "formed_by")]),
        (
            {"op": "CheckIn", **CHECKIN, "session": "s", "formed_by": "m"},
            None,
            [("format", "formed_by"), ("format", "session")],
        ),
    ],
)
def test_failures_have_one_shape(request_: dict[str, Any], ctx: Context | None, found: list[tuple[str, str]]) -> None:
    assert rejected(request_, ctx) == found


def test_op_in_the_request_must_name_the_operator() -> None:
    out = OPERATORS["Search"].call(Context(NO_STORE, AT), {"op": "Traverse", "type": "Entity"})
    assert out.details == {
        "status": "rejected",
        "errors": [{"rule": "format", "at": "op", "msg": "this operator is Search"}],
    }
