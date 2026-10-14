"""共同产物的类型契约（docs/designs/v2/operators.md §4）：按头部的 ``type`` 取用。

v1 实现 Leaderboard、Generate、Skill（docs/experiments/2026-10-13-arxiv-v1-todo.md A4）。论文表单与增补表单是拆开
存进图的检入，经 ``Commit``，不经 ``CheckIn``。
"""

from __future__ import annotations

from .base import ArtifactType, Mention, Unit
from .generate import GENERATE
from .leaderboard import LEADERBOARD
from .skill import SKILL

TYPES: dict[str, ArtifactType] = {t.name: t for t in (LEADERBOARD, GENERATE, SKILL)}
COMMIT_TYPES = frozenset({"paper-form", "supplement-form"})  # 经 Commit 拆开存进图

__all__ = ["COMMIT_TYPES", "TYPES", "ArtifactType", "Mention", "Unit"]
