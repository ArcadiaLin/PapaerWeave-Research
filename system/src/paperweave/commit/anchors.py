"""锚点的写法与有效性（docs/experiments/f3/2026-10-22-f3-design.md §4.1；工程记录 B5、B6）。

锚点写作 ``<来源 ID>::<起>:<止>``：论文 ``2205.13504v2::120:135``（中间可加章节名作提示），代码
``<仓库>@<commit>::<文件>::<起>:<止>``。逐条检查：

- 来源 ID 带版本、已开放（在只读来源目录中）；
- 来源是允许的来源：Content 只能锚到所属 Paper 声明的来源，不能锚到代码；边可以锚到库中任一 Paper 或 Code
  声明过的来源（含同一提交中声明的）；
- 有据记录（Content 与它的修订依据）必须给出行范围；边可以只写来源，或代码只写到文件；
- 给出的行范围在文件之内，且不全是空行或标记。

记录有效性的这些检查 A3、A2 都启用；修订约束（:mod:`paperweave.commit.revision`）只在 A3 启用。
"""

from __future__ import annotations

import re
from collections.abc import Collection

from ..model.refs import normalize_ref, parse_ref
from ..model.schema import ANCHOR, CODE_SOURCE, PAPER_SOURCE, UNVERSIONED
from ..store.sources import SourceDir

FORM = "<source id>::<start>:<end> (a paper like 2205.13504v2::120:135; code like <repo>@<commit>::<file>::<start>:<end>)"
_WORD = re.compile(r"[^\W_]{2,}")  # 一行里至少有一个词：空行、列表符号、分隔线不算


def check(
    item: object,
    sources: SourceDir,
    allowed: Collection[str] | None,
    whose: str = "",
    *,
    grounded: bool,
    require_text: bool = True,
) -> tuple[str | None, str | None]:
    """一条锚点 → (规范写法, 问题)；有问题时规范写法为 ``None``。``allowed`` 为 ``None`` 时不限来源（产物中的引用）；
    ``whose`` 补全来源不在 ``allowed`` 中时的说明，如 ``"a source of paper_0003 (its source: 2205.13504v2)"``。
    ``require_text`` 为假时不检查所引的行有没有文字。"""
    if not isinstance(item, str) or not item.strip():
        return None, f"an anchor is {FORM}"
    ref = parse_ref(item)
    if ref is None or ref.kind != "source":
        return None, _unparsed(normalize_ref(item), allowed or ())
    if not ref.external:
        return None, f"anchors start with the source id, such as 2205.13504v2, not a store id ({ref.head})"
    head = ref.head
    text = ref.text
    if CODE_SOURCE.fullmatch(head) and ref.locator and ref.locator.startswith("./"):
        text = f"{head}::{ref.locator[2:]}"
        ref = parse_ref(text) or ref
    code = CODE_SOURCE.fullmatch(head) is not None
    if grounded and code:
        return None, (
            "a record of what a paper says rests on the paper's own lines, not code; record what the code shows as an "
            "edge (such as Code IMPLEMENTS Method) anchored in the code"
        )
    if not sources.available(head):
        return None, f"{head} is not an available source; fetch sources with read_source and write the id it returns"
    if allowed is not None and head not in allowed:
        return None, f"{head} is not {whose}"
    if grounded and ref.lines is None:
        return None, f"give the lines: {head}::<start>:<end>"
    if code and ref.locator is not None and ref.file is None:
        return None, f"lines in code need the file: {head}::<file>::<start>:<end>"
    if code and ref.file is not None and "::" in ref.file:
        return None, f"a file path cannot contain '::': {ref.file}"
    path = ref.file if code else None
    if code and path is not None and sources.file(head, path) is None:
        return None, f"{path} is not a file in {head}"
    if ref.lines is None:
        return text, None
    lines = sources.lines(head, path)
    if lines is None:
        return None, f"{head}{'::' + path if path else ''} cannot be read as text"
    start, end = ref.lines
    total = len(lines)
    if not 1 <= start <= end <= total:
        return None, f"lines {start}:{end} are outside {head}{'::' + path if path else ''} (1:{total})"
    if require_text and not any(_WORD.search(line) for line in lines[start - 1 : end]):
        near = _nearest_text(lines, start)
        hint = f"; the nearest line with text is {near}: {_cut_line(lines[near - 1])}" if near else ""
        return None, f"lines {start}:{end} hold no text (blank or markup only){hint}"
    return text, None


def _unparsed(text: str, allowed: Collection[str]) -> str:
    head = text.partition("::")[0]
    example = next((s for s in sorted(allowed) if PAPER_SOURCE.fullmatch(s)), "2205.13504v2")
    if ANCHOR.fullmatch(text):
        return f"{text!r} lacks its source: write {example}::{text}"
    if UNVERSIONED.fullmatch(head):
        return f"write the source id with its version, such as {head}v1::<start>:<end> (the id read_source returns)"
    return f"{text!r} is not {FORM}"


def _nearest_text(lines: list[str], line: int) -> int | None:
    """离第 ``line`` 行（从 1 起）最近的有字的行，先往后找。"""
    for d in range(1, 6):
        for n in (line + d, line - d):
            if 1 <= n <= len(lines) and _WORD.search(lines[n - 1]):
                return n
    return None


def _cut_line(line: str, width: int = 80) -> str:
    return repr(line if len(line) <= width else line[:width] + "…")


__all__ = ["FORM", "check"]
