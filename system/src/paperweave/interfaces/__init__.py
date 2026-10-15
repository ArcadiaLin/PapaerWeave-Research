"""版本记录的读取接口（docs/designs/v2/versioning_interfaces.md）：Log、Show、Diff、AsOf。

它们从版本机制推导，不从研究 workload 推导，所以不归入算子；调用形式与只读算子相同（:class:`paperweave.operators.Operator`，
``family`` 为 ``interface``），按名称登记在 ``INTERFACES`` 中。都只读；分支名在第一次调用时固定到具体提交，
续取位置带着它（:mod:`paperweave.query.versions`）；结果不超过 16 KB（:mod:`paperweave.query.capacity`）。
"""

from ..operators.base import Operator
from .as_of import AS_OF
from .diff import DIFF
from .log import LOG
from .show import SHOW

INTERFACES: dict[str, Operator] = {op.name: op for op in (LOG, SHOW, DIFF, AS_OF)}

__all__ = ["AS_OF", "DIFF", "INTERFACES", "LOG", "SHOW"]
