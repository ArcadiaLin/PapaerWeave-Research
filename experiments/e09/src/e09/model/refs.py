"""引用的三种写法（docs/designs/v2/operators.md §2.1）与正文中的方括号引用。

- 对象引用：节点 id，如 ``exp_0012``、``art_0003``；
- 来源引用：``<材料 id 或带材料的节点 id>::<章节>::<start>:<end>``，与 graph-doc 的 ``source_refs`` 相同；
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

from .schema import LOCATOR

RefKind = Literal["object", "source", "record"]

NODE_ID = re.compile(r"[a-z]+_[0-9a-f]{4,}")  # 模型节点、Artifact 与 Material 的 id
RECORD = re.compile(r"(?P<art>art_\d{4,})#(?P<key>[^\s\[\]#](?:[^\[\]#\n]*[^\s\[\]#])?)")
RECORD_KEY = re.compile(r"[A-Za-z0-9_.-]+")  # 记录键、项键与矩阵的行列键；~ 留给 Check 的成对键与矩阵的格子
_BRACKET = re.compile(r"\[([^\[\]\n]+)\](?!\()")
_SEPARATOR = re.compile(r"\s*[,;]\s+(?=[a-z]+_[0-9a-f]{4,})")


@dataclass(frozen=True, slots=True)
class Ref:
    """``head`` 是对象 id、Artifact id（记录引用）或来源引用开头的材料 / 节点 id。"""

    text: str
    kind: RefKind
    head: str
    key: str | None = None  # 记录键
    locator: str | None = None  # 来源引用 :: 之后的部分


_LINES = re.compile(r"(?:lines?\s*|L)?(?P<start>\d+)(?:\s*(?:[-\u2013\u2014:~]|\.\.)\s*L?(?P<end>\d+))?", re.I)


def normalize_ref(text: str) -> str:
    """引用的规范写法：去掉两端的空白、反引号、引号与一对方括号，``::`` 两侧不留空白，行范围写成 ``start:end``。
    认不出行范围时只做前两步。"""
    text = text.strip().strip("`'\"").strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1].strip()
    parts = [p.strip() for p in text.split("::")]
    if len(parts) < 3:
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
        if NODE_ID.fullmatch(head) and LOCATOR.fullmatch(locator):
            return Ref(text, "source", head, locator=locator)
        return None
    if NODE_ID.fullmatch(text):
        return Ref(text, "object", text)
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
