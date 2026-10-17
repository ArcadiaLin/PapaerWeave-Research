"""Summarize：忠实压缩多份材料或记录（docs/designs/v2/operators.md §4.5）。v1 只登记契约，不写种子。

- 没有身份键：每次新建都是一份新的产物；仍然可以被他人编辑。
- **强制：** 每个段落至少有一处引用（段落以空行分隔，只有标题的段落不计；方括号中的内容全部是引用时才算引用）。
  这是忠实压缩的检查。
"""

from __future__ import annotations

from typing import Any

from ..document import Parsed
from .base import ArtifactType, Report, cited_paragraphs


class Summarize(ArtifactType):
    name = "Summarize"
    template = (
        "---\ntype: Summarize\ntitle: <what is summarized>\nabs: <one sentence on the summary>\n---\n"
        "<One paragraph per point. Every paragraph cites what it summarizes in brackets: a node [exp_0003], paper "
        "lines [paper_0001::120:135], or an artifact row [art_0002#<row key>]. Keep different settings apart; do "
        "not merge them into one number.>\n"
    )

    def check(self, doc: Parsed, report: Report) -> None:
        super().check(doc, report)
        for line, cited in cited_paragraphs(doc):
            if not cited:
                report("schema", line, "every paragraph of a summary cites what it summarizes, in square brackets")

    def stats(self, doc: Parsed) -> dict[str, Any]:
        return {"paragraphs": len(cited_paragraphs(doc))}


SUMMARIZE = Summarize()

__all__ = ["SUMMARIZE", "Summarize"]
