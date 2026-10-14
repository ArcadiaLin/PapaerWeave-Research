"""CompareSettings：判断两组结果是否可比（docs/designs/v2/operators.md §4.3）。v1 只登记契约，不写种子。

- **身份键：** 头部的 ``items``，被比较的两项（Leaderboard 的记录引用或实验 id），不分先后。
- **强制：** ``verdict`` 为三值；比较表每个维度一行（行键为 ``dimension``），``same`` 为三值，``T`` 与 ``F`` 在
  ``basis`` 中带引用，``U`` 在 ``basis`` 中写明原因。
- **可选：** ``relation``（两项是不同论文对同一格报告的值时，按论文自己的陈述它们本该是什么关系）。
- **警告：** 缺少种子给出的维度（``lookback``、``split``、``normalization``、``training_data``、``protocol``）。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from ...model.refs import cited, parse_ref
from ..document import Parsed, Table, tables
from .base import ArtifactType, Lookup, Mention, Report, header_line, identity, normalize

VERDICTS = ("T", "F", "U")
COLUMNS = ("dimension", "left", "right", "same", "basis")
DIMENSIONS = ("lookback", "split", "normalization", "training_data", "protocol")
RELATIONS = frozenset({"same_source", "independent", "incomparable", "unknown"})


def _items(header: Mapping[str, Any]) -> list[str]:
    items = header.get("items")
    return [normalize(i) for i in items] if isinstance(items, list) else []


def _table(table: Table) -> bool:
    return "dimension" in table.columns and "same" in table.columns


class CompareSettings(ArtifactType):
    name = "CompareSettings"

    def key(self, header: Mapping[str, Any]) -> str | None:
        return identity(self.name, *sorted(i.casefold() for i in _items(header)))

    def check(self, doc: Parsed, report: Report) -> None:
        super().check(doc, report)
        items = _items(doc.header)
        if len(items) != 2 or len(set(items)) != 2 or any(parse_ref(i) is None for i in items):
            msg = (
                "items lists the two things compared: Leaderboard row references (art_...#<row key>) or experiment ids"
            )
            report("schema", header_line(doc, "items"), msg)
        if doc.header.get("verdict") not in VERDICTS:
            report("schema", header_line(doc, "verdict"), "verdict is T (comparable), F (not comparable) or U")
        relation = doc.header.get("relation")
        if relation is not None and relation not in RELATIONS:
            report("schema", header_line(doc, "relation"), f"relation is one of {sorted(RELATIONS)}")
        found = [t for t in tables(doc) if _table(t)]
        if not found:
            report("schema", doc.body_start, f"a comparison table with columns {', '.join(COLUMNS)}")
        for table in found:
            if missing := [c for c in COLUMNS if c not in table.columns]:
                report("schema", table.lines[0], f"the comparison table lacks columns {missing}")
            seen: dict[str, int] = {}
            for row in table.rows:
                same, basis = row.cells.get("same", ""), row.cells.get("basis", "")
                if same not in VERDICTS:
                    report("schema", row.line, "same is T, F or U")
                elif same in ("T", "F") and not cited(basis):
                    report("schema", row.line, f"same {same} needs a citation in basis, in square brackets")
                elif same == "U" and not basis:
                    report("schema", row.line, "same U needs the reason in basis")
                dimension = normalize(row.cells.get("dimension", "")).casefold()
                if dimension in seen:
                    report("schema", row.line, f"dimension {dimension!r} is already on line {seen[dimension]}")
                seen.setdefault(dimension, row.line)

    def mentions(self, doc: Parsed) -> list[Mention]:
        line = header_line(doc, "items")
        head = [Mention(line, i, "items") for i in _items(doc.header) if parse_ref(i) is not None]
        return head + super().mentions(doc)

    def keyed(self, table: Table) -> tuple[str, Callable[[dict[str, str]], str]] | None:
        return ("dimensions", lambda cells: normalize(cells.get("dimension", ""))) if _table(table) else None

    def rules(self, doc: Parsed, changed: set[int], lookup: Lookup, report: Report, warn: Report) -> None:
        for table in (t for t in tables(doc) if _table(t)):
            if not any(row.line in changed for row in table.rows):
                continue
            present = {normalize(row.cells.get("dimension", "")).casefold() for row in table.rows}
            if missing := [d for d in DIMENSIONS if d not in present]:
                warn("structure", table.lines[0], f"the form also has the dimensions {missing}")


COMPARE_SETTINGS = CompareSettings()

__all__ = ["COMPARE_SETTINGS", "CompareSettings"]
