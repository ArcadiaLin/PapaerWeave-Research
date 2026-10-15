"""对外提供的全部工具：算子（:mod:`paperweave.operators`）与版本记录的读取接口（:mod:`paperweave.interfaces`），按名称登记在
``TOOLS`` 中。命令行（:mod:`paperweave.cli`）与 MCP 服务（:mod:`paperweave.mcp`）都从这里分发。

    call(ctx, {op, ...}) -> Result
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .interfaces import INTERFACES
from .operators import OPERATORS, Context, Operator, Result
from .operators.base import rejected

TOOLS: dict[str, Operator] = {**OPERATORS, **INTERFACES}


def call(ctx: Context, request: Mapping[str, Any]) -> Result:
    """按请求的 ``op`` 找到工具并执行；请求不是映射或 ``op`` 不认识时返回 ``rejected``。"""
    op = request.get("op") if isinstance(request, Mapping) else None
    if op not in TOOLS:
        return rejected([{"rule": "format", "at": "op", "msg": f"one of {list(TOOLS)}"}])
    return TOOLS[op].call(ctx, request)


__all__ = ["TOOLS", "call"]
