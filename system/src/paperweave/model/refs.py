"""引用的三种写法（docs/designs/v2/operators.md §2.1）与正文中的方括号引用。

- 对象引用：节点 id，如 ``exp_0012``、``art_0003``；
- 来源引用：``<来源 id>::[<章节>::]<start>:<end>``，来源 id 为带版本的 arXiv 编号或 ``<仓库>@<commit>``，章节可省略；
  代码写作 ``<仓库>@<commit>::<文件路径>::<start>:<end>``。只写来源 id（或代码只写到文件）指整个来源（或整个文件）。
  产物与材料 id 开头的 ``<id>::<start>:<end>`` 也解析为来源引用，只用作 read_evidence 的读取输入；
- 记录引用：``<artifact id>#<key>``，指 Artifact 中的一条记录：旧版 Agent 算子是数据块中的记录，共同产物是按行键
  对齐的表格行，``key`` 为行键各字段以 ``+`` 相连（如 ``art_0003#method_0001++paper_0001+24+96``），字段可以含
  ``/`` 与空格（operators.md §4.1）。

正文中的引用写在方括号里，如 ``[exp_0012]``、``[art_0003#dlinear-etth1-96]``；一对方括号里可以用逗号或分号
隔开多个引用。方括号里不全是引用时（如普通的方括号文字）不当作引用；Markdown 链接 ``[文字](地址)`` 也不算。

解析前先按 :func:`normalize_ref` 兜底模型常见的写法偏差（不提示给 Agent）：两端的空白、反引号、引号与一对方括号，
``::`` 两侧的空白，行范围写成 ``174-196``、``174–196``、``L174-L196``、``lines 174-196`` 或单个行号 ``174``。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from .schema import CODE_SOURCE, LOCATOR, SOURCE_ID

RefKind = Literal["object", "source", "record"]

NODE_ID = re.compile(r"[a-z]+_[0-9a-f]{4,}")  # 模型节点、Artifact 与 Material 的 id
RECORD = re.compile(r"(?P<art>art_\d{4,})#(?P<key>[^\s\[\]#](?:[^\[\]#\n]*[^\s\[\]#])?)")
RECORD_KEY = re.compile(r"[A-Za-z0-9_.-]+")  # 记录键、项键与矩阵的行列键；~ 留给 Check 的成对键与矩阵的格子
_BRACKET = re.compile(r"\[([^\[\]\n]+)\](?!\()")
_SEPARATOR = re.compile(rf"\s*[,;]\s+(?=[a-z]+_[0-9a-f]{{4,}}|{SOURCE_ID.pattern})")


@dataclass(frozen=True, slots=True)
class Ref:
    """``head`` 是对象 id、Artifact id（记录引用）或来源引用开头的来源、材料或节点 id。"""

    text: str
    kind: RefKind
    head: str
    key: str | None = None  # 记录键
    locator: str | None = None  # 来源引用 :: 之后的部分；只写来源时为 None

    @property
    def external(self) -> bool:
        """来源引用以外部来源 id 开头（不是库内的节点或材料 id）。"""
        return self.kind == "source" and SOURCE_ID.fullmatch(self.head) is not None

    @property
    def file(self) -> str | None:
        """代码来源引用中的仓库内文件路径。"""
        if self.kind != "source" or not CODE_SOURCE.fullmatch(self.head) or not self.locator:
            return None
        match = LOCATOR.fullmatch(self.locator)
        return match["section"] if match else self.locator

    @property
    def lines(self) -> tuple[int, int] | None:
        """来源引用的行范围；只写到来源或文件时为 None。"""
        match = LOCATOR.fullmatch(self.locator or "")
        return (int(match["start"]), int(match["end"])) if match else None


_PATH = re.compile(r"[^\s:]+(?:/[^\s:]+)*")  # 仓库内的文件路径：不含空白与冒号
_LINES = re.compile(r"(?:lines?\s*|L)?(?P<start>\d+)(?:\s*(?:[-\u2013\u2014:~]|\.\.)\s*L?(?P<end>\d+))?", re.I)


def normalize_ref(text: str) -> str:
    """引用的规范写法：去掉两端的空白、反引号、引号与一对方括号，``::`` 两侧不留空白，行范围写成 ``start:end``。
    认不出行范围时只做前两步。"""
    text = text.strip().strip("`'\"").strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1].strip()
    parts = [p.strip() for p in text.split("::")]
    if len(parts) < 2:
        return "::".join(parts)
    lines = _LINES.fullmatch(parts[-1])
    if lines is not None:
        parts[-1] = f"{lines['start']}:{lines['end'] or lines['start']}"
    return "::".join(parts)


def parse_ref(text: str) -> Ref | None:
    """解析一个引用（先经 :func:`normalize_ref`）；不是三种写法之一时返回 ``None``。``Ref.text`` 是规范写法。"""
    text = normalize_ref(text)
    if match := RECORD.fullmatch(text):
        return Ref(text, "record", match["art"], key=match["key"])
    head, sep, locator = text.partition("::")
    if sep:
        if (NODE_ID.fullmatch(head) or SOURCE_ID.fullmatch(head)) and LOCATOR.fullmatch(locator):
            return Ref(text, "source", head, locator=locator)
        if CODE_SOURCE.fullmatch(head) and _PATH.fullmatch(locator):  # 代码只写到文件
            return Ref(text, "source", head, locator=locator)
        return None
    if NODE_ID.fullmatch(text):
        return Ref(text, "object", text)
    if SOURCE_ID.fullmatch(text):  # 只写来源：整个来源
        return Ref(text, "source", text)
    return None


def cited(text: str) -> list[str]:
    """正文中方括号里的引用，按出现顺序，不去重。"""
    out: list[str] = []
    for match in _BRACKET.finditer(text):
        parts = _SEPARATOR.split(match[1].strip())
        if parts and all(parse_ref(p) is not None for p in parts):
            out += [p.strip() for p in parts]
    return out


def paragraphs(text: str) -> list[str]:
    """以空行分隔的段落；只有标题行的段落不计。"""
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text)]
    return [b for b in blocks if b and not all(line.lstrip().startswith("#") for line in b.splitlines())]


__all__ = ["NODE_ID", "RECORD", "RECORD_KEY", "Ref", "RefKind", "cited", "normalize_ref", "paragraphs", "parse_ref"]
