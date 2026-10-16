"""Generate：回答、草稿、点子、方案（docs/designs/v2/operators.md §4.6）。

最灵活的产物：没有身份键，每次新建都是一份新的产物，仍然可以被他人编辑。强制的只有“出现的引用必须存在”
（由检入时的引用核对执行）。返回 ``stats``：段落数、带引用的段落数；引用比例只是报告项，不是校验。正文按行比对。
"""

from __future__ import annotations

from typing import Any

from ..document import Parsed
from .base import ArtifactType, cited_paragraphs


class Generate(ArtifactType):
    name = "Generate"
    template = (
        "---\ntype: Generate\ntitle: <short title>\nabs: <one sentence on what this is>\n---\n"
        "<Your text. Cite what each statement rests on in brackets: a node [exp_0003], paper lines "
        "[paper_0001::120:135], or an artifact row [art_0002#<row key>].>\n"
    )

    def stats(self, doc: Parsed) -> dict[str, Any]:
        found = cited_paragraphs(doc)
        return {"paragraphs": len(found), "cited_paragraphs": sum(1 for _, c in found if c)}


GENERATE = Generate()

__all__ = ["GENERATE", "Generate"]
