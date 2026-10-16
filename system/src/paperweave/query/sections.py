"""锚点所在的章节：按论文 Markdown 的标题行现算，不存在库中（论文换版本时不会过期）。"""

from __future__ import annotations

import re
from functools import lru_cache

from ..model.schema import ANCHOR

_HEADING = re.compile(r"#{1,6}\s+(?P<title>.+?)\s*#*\s*$")


def headings(lines: list[str]) -> list[tuple[int, str]]:
    """（行号, 标题）按行号排序；行号从 1 起。"""
    out = []
    for n, line in enumerate(lines, 1):
        m = _HEADING.fullmatch(line.strip())
        if m:
            out.append((n, m["title"]))
    return out


def section_at(heads: list[tuple[int, str]], line: int) -> str | None:
    """``line`` 所在的章节：它之前最近的标题。"""
    title = None
    for n, text in heads:
        if n > line:
            break
        title = text
    return title


def sections(heads: list[tuple[int, str]], anchors: list[str]) -> list[str]:
    """每个锚点所在的章节，去重保序。"""
    out: list[str] = []
    for anchor in anchors:
        m = ANCHOR.fullmatch(anchor) if isinstance(anchor, str) else None
        title = section_at(heads, int(m["start"])) if m else None
        if title and title not in out:
            out.append(title)
    return out


@lru_cache(maxsize=256)
def cached_headings(path: str, content_hash: str, text: str) -> tuple[tuple[int, str], ...]:
    """按材料内容哈希缓存的标题表（同一份材料在一个服务进程中只解析一次）。"""
    del path, content_hash
    return tuple(headings(text.splitlines()))


__all__ = ["cached_headings", "headings", "section_at", "sections"]
