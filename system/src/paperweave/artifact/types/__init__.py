"""共同产物的类型契约（docs/designs/v2/operators.md §4）：按头部的 ``type`` 取用。

v1 的 Leaderboard、Note（原 Generate）、Skill 有种子；CompareSettings、Verify、Summarize 只登记契约，不写种子
（docs/experiments/2026-10-13-arxiv-v1-todo.md A4）。论文表单与增补表单是拆开存进图的检入，经 ``commit``（graph-doc），不按产物检入。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ...store.store import ContractError
from .base import ArtifactType, Authors, Lookup, Mention, Source, Unit
from .compare_settings import COMPARE_SETTINGS
from .note import NOTE
from .leaderboard import LEADERBOARD
from .skill import SKILL
from .summarize import SUMMARIZE
from .verify import VERIFY

TYPES: dict[str, ArtifactType] = {
    t.name: t for t in (LEADERBOARD, COMPARE_SETTINGS, VERIFY, SUMMARIZE, NOTE, SKILL)
}
COMMIT_TYPES = frozenset({"paper-form", "supplement-form"})  # 经 Commit 拆开存进图


def identity_key(fields: Any, *, at: str) -> str:
    """按身份查找（``where.key``，讨论稿 §4 的 G1）：``{type, <身份字段>...}`` → 规范化的身份键，与检入时
    算出、存在产物节点 ``key`` 上的相同。

    Raises:
        ContractError: 不是这样的映射、类型没有身份键，或缺少身份字段。
    """
    keyed = sorted(name for name, kind in TYPES.items() if kind.identity_fields)
    example = "{type: Leaderboard, task: <id>, dataset: <id>, setting: {variate: multivariate}}"
    if not isinstance(fields, Mapping) or fields.get("type") not in TYPES:
        raise ContractError(
            [{"at": at, "msg": f"a mapping {{type, <identity fields>}}, type one of {keyed}; e.g. {example}"}]
        )
    kind = TYPES[fields["type"]]
    if not kind.identity_fields:
        raise ContractError([{"at": at, "msg": f"a {kind.name} has no identity; find it with query or used"}])
    wanted = {"type", *kind.identity_fields}
    if missing := [f for f in kind.identity_fields if fields.get(f) in (None, "", [], {})]:
        raise ContractError([{"at": at, "msg": f"the identity of a {kind.name} also needs {missing}"}])
    if unknown := sorted(set(fields) - wanted):
        raise ContractError([{"at": at, "msg": f"the identity of a {kind.name} is {sorted(wanted)}, not {unknown}"}])
    key = kind.key(dict(fields))
    assert key is not None
    return key


__all__ = [
    "COMMIT_TYPES",
    "TYPES",
    "ArtifactType",
    "Authors",
    "Lookup",
    "Mention",
    "Source",
    "Unit",
    "identity_key",
]
