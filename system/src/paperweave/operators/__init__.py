"""PaperWeave 的工具（docs/designs/v3/tools.md）：都在 ``db/``，由中间件执行；共同产物经 ``checkout`` 取出、
``commit`` 检入，类型契约见 :mod:`paperweave.artifact.types`。每个算子是一个 :class:`Operator`（见
:mod:`paperweave.operators.base`），按名称登记在 ``OPERATORS`` 中；
与版本记录的读取接口一起按名称分发见 :mod:`paperweave.tools`。
"""

from __future__ import annotations

from .base import Context, Operator, Result
from .db import DB_OPERATORS

OPERATORS: dict[str, Operator] = dict(DB_OPERATORS)

__all__ = ["OPERATORS", "Context", "Operator", "Result"]
