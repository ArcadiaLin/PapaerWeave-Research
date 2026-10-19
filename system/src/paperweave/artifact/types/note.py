"""Note：写者为后来的读者写下的成文结果，如回答、方法选择、找实现的结论、方案（原名 Generate，
docs/designs/v2/operators.md §4.6；用户 2026-10-19 同意改名：Generate 是动作名，写者在“把结果记进库”时想不到它）。

最灵活的产物：没有身份键，每次新建都是一份新的产物，仍然可以被他人编辑。强制的只有“出现的引用必须存在”
（由检入时的引用核对执行）。返回 ``stats``：段落数、带引用的段落数；引用比例只是报告项，不是校验。正文按行比对。
"""

from __future__ import annotations

from typing import Any

from ..document import Parsed
from .base import ArtifactType, cited_paragraphs


class Note(ArtifactType):
    name = "Note"
    template = (
        "---\ntype: Note\ntitle: <short title>\nabs: <one sentence on what this note answers or records>\n---\n"
        "<Your findings and conclusions, written for a later reader who was not here. Cite what each statement "
        "rests on in brackets: a node [exp_0003], paper lines [paper_0001::120:135], or an artifact row "
        "[art_0002#<row key>]. Say where something comes from outside the store (a file you read, a code "
        "repository), and mark your own judgments as yours.>\n"
    )

    def stats(self, doc: Parsed) -> dict[str, Any]:
        found = cited_paragraphs(doc)
        return {"paragraphs": len(found), "cited_paragraphs": sum(1 for _, c in found if c)}


NOTE = Note()

__all__ = ["NOTE", "Note"]
