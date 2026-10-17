"""共同产物的类型契约（docs/designs/v2/operators.md §4.1–4.6）：每个类型说明库要对它执行的那部分结构。

一个类型给出：

- **身份键**（:meth:`ArtifactType.key`）：由头部字段算出的规范化字符串，有键的产物一个键只有一份；没有键时为
  ``None``，每次新建都是一份新的产物；
- **校验**（:meth:`ArtifactType.check`）：只拦会破坏库的东西（头部的必填字段、行键的写法），其余留给写者；
- **引用**（:meth:`ArtifactType.mentions`）：文档中出现的引用及其所在的行与角色，由此得出 ``USED`` 边；
- **比对单位**（:meth:`ArtifactType.units`）：按行键对齐的表格行，以及其余的逐行文字；版本之间的改动与每一行的
  编辑者按它们计算（:mod:`paperweave.artifact.versions`）；
- **记录**（:meth:`ArtifactType.records`）：可用 ``<artifact>#<key>`` 引用的行；
- **取出的位置**（:meth:`ArtifactType.checkout_path`）：``checkout`` 写到写者工作目录的哪里；
- **轻度规则**（:meth:`ArtifactType.rules`）：只作用于这次新增与修改的单位，拒绝的记为错误，其余只警告（如数字
  不在所引的行中）；需要所引来源的行时经 :data:`Lookup` 取得；
- **统计与附注**（:meth:`ArtifactType.stats`、:meth:`ArtifactType.notes`）：检入时返回的统计，以及读取时现算、
  不写进文档的附注（如 Leaderboard 每位编辑者写的行数、所引论文已有新版本的行、同一格的多个值）。

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
"""报告一个错误或警告：``(rule, 行号, 说明)``。"""


@dataclass(frozen=True, slots=True)
class Source:
    """一个来源引用所指的材料：``owner`` 是材料所属的节点，``superseded_by`` 是取代它的新版本材料，``lines`` 是所引
    的那几行（文件不在或哈希不符时为 ``None``）。"""

    material: str
    owner: str | None
    superseded_by: str | None
    lines: list[str] | None


Lookup = Callable[[str], "Source | None"]
"""来源引用的写法 → 所指的材料；不是来源引用或材料不在时为 ``None``。"""

Authors = Mapping[int, tuple[str, int]]
"""文档的行号 → 最近编辑它的 ``(编辑者, 版本号)``，由版本链推出（paperweave.artifact.versions.blame）。"""


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
    identity_fields: tuple[str, ...] = ()  # 算身份键的头部字段；没有身份键的类型为空
    template: str = ""  # checkout new 给出的空白文档；空时不给模板

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

    # ── 轻度规则、统计与附注 ──

    def rules(self, doc: Parsed, changed: set[int], lookup: Lookup, report: Report, warn: Report) -> None:
        """这次新增与修改的单位（``changed`` 是它们的行号）上的轻度规则：拒绝的经 ``report``，其余经 ``warn``。"""

    def stats(self, doc: Parsed) -> dict[str, Any]:
        """检入时返回的统计；只是报告项，不是校验。"""
        return {}

    def notes(self, doc: Parsed, authors: Authors, lookup: Lookup, changed: set[int] | None = None) -> dict[str, Any]:
        """读取时现算的附注，不写进文档；行号是 ``doc`` 中的行号。``changed`` 给出时（检入的返回）是这次新增与修改
        的行：随表变长的逐条附注只展开与它们有关的，其余给条数，全部的在 checkout 写出的 notes 文件中。"""
        return {}

    # ── 取出 ──

    def checkout_path(self, header: Mapping[str, Any]) -> str:
        """取出时在写者工作目录中的相对路径。"""
        return f"artifacts/{file_name(self.title(header) or 'artifact')}"


def cited_paragraphs(doc: Parsed) -> list[tuple[int, bool]]:
    """正文的段落（以空行分隔，只有标题的段落不计）：``(起始行号, 是否至少有一处方括号引用)``。"""
    out: list[tuple[int, bool]] = []
    start: int | None = None
    block: list[str] = []
    lines = doc.lines
    for n in range(doc.body_start, len(lines) + 2):
        line = lines[n - 1] if n <= len(lines) else ""
        if line.strip():
            start = n if start is None else start
            block.append(line)
            continue
        if start is not None and not all(b.lstrip().startswith("#") for b in block):
            out.append((start, any(cited(b) for b in block)))
        start, block = None, []
    return out


_TOP_KEY = re.compile(r"(?P<key>[A-Za-z_][\w-]*)\s*:")


def header_line(doc: Parsed, name: str) -> int:
    """头部中顶层字段 ``name`` 所在的行号；没有时为头部的第一行。"""
    for n, line in enumerate(doc.lines[1 : doc.body_start - 2], start=2):
        m = _TOP_KEY.match(line)
        if m is not None and m["key"] == name:
            return n
    return 1


__all__ = [
    "ArtifactType",
    "Authors",
    "Lookup",
    "Mention",
    "Report",
    "Source",
    "Unit",
    "cited_paragraphs",
    "header_line",
    "identity",
    "leading_id",
    "normalize",
]
