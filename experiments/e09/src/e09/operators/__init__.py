"""E09 的算子（docs/designs/v2/operators.md）：都在 ``db/``，由中间件执行；共同产物经 ``FetchArtifact`` 取出、
``CheckIn`` 检入，类型契约见 :mod:`e09.artifact.types`。每个算子是一个 :class:`Operator`（见
:mod:`e09.operators.base`），按名称登记在 ``OPERATORS`` 中；
与版本记录的读取接口一起按名称分发见 :mod:`e09.tools`。
"""

from __future__ import annotations

from .base import Context, Operator, Result
from .db import DB_OPERATORS

OPERATORS: dict[str, Operator] = dict(DB_OPERATORS)

__all__ = ["OPERATORS", "Context", "Operator", "Result"]
