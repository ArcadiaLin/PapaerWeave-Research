"""写入检查报告的问题。``error`` 阻塞写入，``warning`` 只提示。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

Severity = Literal["error", "warning"]


@dataclass(frozen=True, slots=True)
class Problem:
    """``rule`` 是规则类别，``at`` 是 graph-doc 中的位置（如 ``nodes.$exp.EVALUATES[1]``），
    ``candidates`` 是与之冲突或可供选择的已有节点 id，``evidence`` 记录每个候选由哪些通道找到（查重）。"""

    rule: str
    at: str
    msg: str
    severity: Severity = "error"
    candidates: tuple[str, ...] = ()
    evidence: Mapping[str, tuple[str, ...]] = field(default_factory=dict)


__all__ = ["Problem", "Severity"]
