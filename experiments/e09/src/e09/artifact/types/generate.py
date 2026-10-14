"""Generate：回答、草稿、点子、方案（docs/designs/v2/operators.md §4.6）。

最灵活的产物：没有身份键，每次新建都是一份新的产物，仍然可以被他人编辑。强制的只有“出现的引用必须存在”
（由检入时的引用核对执行）。正文按行比对。
"""

from __future__ import annotations

from .base import ArtifactType


class Generate(ArtifactType):
    name = "Generate"


GENERATE = Generate()

__all__ = ["GENERATE", "Generate"]
