"""共同产物的类型契约（docs/designs/v2/operators.md §4.1–4.6）：每个类型说明库要对它执行的那部分结构。

一个类型给出：

- **身份键**（:meth:`ArtifactType.key`）：由头部字段算出的规范化字符串，有键的产物一个键只有一份；没有键时为
  ``None``，每次新建都是一份新的产物；
- **校验**（:meth:`ArtifactType.check`）：只拦会破坏库的东西（头部的必填字段、行键的写法），其余留给写者；
- **引用**（:meth:`ArtifactType.mentions`）：文档中出现的引用及其所在的行与角色，由此得出 ``USED`` 边；
- **比对单位**（:meth:`ArtifactType.units`）：按行键对齐的表格行，以及其余的逐行文字；版本之间的改动与每一行的
  编辑者按它们计算（:mod:`e09.artifact.versions`）；
- **记录**（:meth:`ArtifactType.records`）：可用 ``<artifact>#<key>`` 引用的行；
- **取出的位置**（:meth:`ArtifactType.checkout_path`）：``FetchArtifact`` 写到写者工作目录的哪里。

类型的说明与规则改了，``version`` 随之改变，记在产物节点的 ``op_version`` 上。
"""

from __future__ import annotations

import hashlib
import inspect
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any

from ...model.refs import cited
from ..document import Parsed, Table, cells_of, file_name, tables

Report = Callable[[str, int, str], None]
"""报告一个错误：``(rule, 行号, 说明)``。"""


@dataclass(frozen=True, slots=True)
class Mention:
    """文档中的一个引用：``line`` 是所在的行，``text`` 是写法，``role`` 是它在 ``USED`` 边上的角色（头部字段名或
    表格列名；正文中方括号里的引用没有角色）。"""

    line: int
    text: str
    role: str | None = None


@dataclass(frozen=True, slots=True)
class Unit:
    """比对与归属的单位。``key`` 不为 ``None`` 时是按行键对齐的表格行（``<表>\\x00<行键>``，行键已规范化），否则是
    其余的一行。``text`` 用于比较（表格行比较去掉首尾空白的单元格，排版不算改动），``label`` 用于显示。"""

    key: str | None
    line: int
    text: str
    label: str


def normalize(value: Any) -> str:
    """字符串规范化：去首尾空白、连续空白并成一个。"""
    return " ".join(str(value).split()) if value is not None else ""


def identity(*parts: str) -> str:
    """身份键：各部分规范化后以 ``|`` 相连，不区分大小写。"""
    return "|".join(normalize(p) for p in parts).casefold()


def leading_id(cell: str) -> str:
    """单元格开头的 id（如 ``method_0001 Informer`` 中的 ``method_0001``）；没有时为空串。"""
    first = cell.split(maxsplit=1)
    return first[0] if first else ""


class ArtifactType:
    """类型契约的共同部分；具体类型覆盖需要的方法。"""

    name: str = ""
    nested: bool = False  # type、id、base 写在 metadata 下（Skill）

    @cached_property
    def version(self) -> str:
        """说明与规则的哈希：类型模块与本模块的源码。"""
        files = [Path(inspect.getfile(type(self))), Path(__file__)]
        digest = hashlib.sha256(b"".join(f.read_bytes() for f in files)).hexdigest()
        return digest[:12]

    # ── 头部 ──

    def title(self, header: Mapping[str, Any]) -> str:
        return normalize(header.get("title"))

    def abstract(self, header: Mapping[str, Any]) -> str:
        return str(header.get("abs") or "").strip()

    def key(self, header: Mapping[str, Any]) -> str | None:
        return None

    def check(self, doc: Parsed, report: Report) -> None:
        """头部的 ``title`` 与 ``abs`` 是检索文本，必填。"""
        for name in ("title", "abs"):
            value = doc.header.get(name)
            if not (isinstance(value, str) and value.strip()):
                report("schema", header_line(doc, name), f"{name} is required: a non-empty text used for search")

    # ── 引用 ──

    def mentions(self, doc: Parsed) -> list[Mention]:
        """正文中方括号里的引用。"""
        lines = doc.lines
        return [Mention(n, text) for n in range(doc.body_start, len(lines) + 1) for text in cited(lines[n - 1])]

    # ── 比对 ──

    def keyed(self, table: Table) -> tuple[str, Callable[[dict[str, str]], str]] | None:
        """按行键对齐的表格：``(表名, 行 → 行键)``；不按行键对齐时为 ``None``。"""
        return None

    def units(self, doc: Parsed) -> list[Unit]:
        """全文的比对单位，按行的顺序：按行键对齐的表格行，其余每行一个。"""
        rows: dict[int, Unit] = {}
        for table in tables(doc):
            spec = self.keyed(table)
            if spec is None:
                continue
            name, key_of = spec
            for row in table.rows:
                key = key_of(row.cells)
                text = "|".join(row.cells.values())
                rows[row.line] = Unit(f"{name}\x00{key.casefold()}", row.line, text, f"{name} row {key}")
        out: list[Unit] = []
        for n, line in enumerate(doc.lines, start=1):
            if n in rows:
                out.append(rows[n])
                continue
            cells = cells_of(line)
            out.append(Unit(None, n, "|".join(cells) if cells is not None else line.rstrip(), line.strip()))
        return out

    def records(self, doc: Parsed) -> dict[str, str]:
        """可引用的行：规范化后不区分大小写的行键 → 行键。"""
        return {}

    # ── 取出 ──

    def checkout_path(self, header: Mapping[str, Any]) -> str:
        """取出时在写者工作目录中的相对路径。"""
        return f"artifacts/{file_name(self.title(header) or 'artifact')}"


_TOP_KEY = re.compile(r"(?P<key>[A-Za-z_][\w-]*)\s*:")


def header_line(doc: Parsed, name: str) -> int:
    """头部中顶层字段 ``name`` 所在的行号；没有时为头部的第一行。"""
    for n, line in enumerate(doc.lines[1 : doc.body_start - 2], start=2):
        m = _TOP_KEY.match(line)
        if m is not None and m["key"] == name:
            return n
    return 1


__all__ = ["ArtifactType", "Mention", "Report", "Unit", "header_line", "identity", "leading_id", "normalize"]
