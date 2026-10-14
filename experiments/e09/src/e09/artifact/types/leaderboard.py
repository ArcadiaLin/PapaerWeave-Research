"""Leaderboard：共同维护的结果表（docs/designs/v2/operators.md §4.2）。

一份对应一个（任务、数据集、设置），跨论文、跨预测长度。本模块只含身份键、行键、引用与必填的结构；“新增与修改的
行须带 ``source``”“``metrics`` 中的列须为数字”等轻度规则与读取时现算的附注见 A4（docs/experiments/
2026-10-13-arxiv-v1-todo.md）。

- **身份键：** 头部的 ``task``、``dataset``（写成 id，后面可跟名字或注释）与 ``setting``（映射或文字）。
- **结果表**是含 ``method``、``paper``、``pred_len``、``lookback`` 列的表，行键为（方法、变体、论文、预测长度、
  look-back），``variant`` 列可以没有。方法与论文的单元格以 id 开头。行键的各字段按字符串比较，可以写说明文字。
- **论文覆盖表**是含 ``paper`` 列、不含 ``method`` 列的表，行键为论文。
- **引用：** 头部的 ``task``、``dataset``；表中 ``method``、``paper`` 列开头的 id；``source`` 列的来源引用；
  表格单元格中不带方括号的来源引用（如 ``Table 1 (material_a1::4.2::112:140)``）；正文中方括号里的引用。
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from typing import Any

from ...model.refs import NODE_ID, cited
from ..document import Parsed, Table, tables
from .base import ArtifactType, Mention, Report, header_line, identity, leading_id, normalize

ROW_KEY = ("method", "variant", "paper", "pred_len", "lookback")
REQUIRED_COLUMNS = ("method", "paper", "pred_len", "lookback")
ID_COLUMNS = ("method", "paper")
_SOURCE = re.compile(r"[a-z]+_[0-9a-f]{4,}::[^:()\[\]|]+::\d+(?:\s*[:–-]\s*\d+)?")
_SPLIT = re.compile(r"\s*;\s*|\s*,\s+(?=[a-z]+_[0-9a-f]{4,}::)")


def row_key(cells: Mapping[str, str]) -> str:
    """结果表的行键：各字段以 ``+`` 相连，方法与论文取开头的 id，空字段留空。"""
    parts = [leading_id(cells.get(c, "")) if c in ID_COLUMNS else normalize(cells.get(c, "")) for c in ROW_KEY]
    return "+".join(parts)


def _setting(value: Any) -> str:
    if isinstance(value, Mapping):
        return json.dumps({normalize(k): _setting(v) for k, v in value.items()}, sort_keys=True, ensure_ascii=False)
    if isinstance(value, list):
        return json.dumps([_setting(v) for v in value], ensure_ascii=False)
    return normalize(value)


def _results(table: Table) -> bool:
    return all(c in table.columns for c in ("method", "paper", "pred_len"))


def _papers(table: Table) -> bool:
    return "paper" in table.columns and "method" not in table.columns


class Leaderboard(ArtifactType):
    name = "Leaderboard"

    def key(self, header: Mapping[str, Any]) -> str | None:
        task, dataset = (leading_id(str(header.get(f) or "")) for f in ("task", "dataset"))
        return identity(self.name, task, dataset, _setting(header.get("setting")))

    def check(self, doc: Parsed, report: Report) -> None:
        super().check(doc, report)
        for name in ("task", "dataset"):
            value = doc.header.get(name)
            if not (isinstance(value, str) and NODE_ID.fullmatch(leading_id(value))):
                report("schema", header_line(doc, name), f"{name} is required: the id of the {name}, e.g. {name}_0001")
        if doc.header.get("setting") in (None, "", {}):
            report("schema", header_line(doc, "setting"), "setting is required, e.g. {variate: multivariate}")
        found = [t for t in tables(doc) if _results(t)]
        if not found:
            msg = f"a results table with columns {', '.join(ROW_KEY)} (variant may be left out)"
            report("schema", doc.body_start, msg)
        for table in found:
            if missing := [c for c in REQUIRED_COLUMNS if c not in table.columns]:
                report("schema", table.lines[0], f"the results table lacks columns {missing}")
        for table in tables(doc):
            spec = self.keyed(table)
            if spec is None:
                continue
            seen: dict[str, int] = {}
            for row in table.rows:
                for column in ID_COLUMNS:
                    if column in table.columns and not NODE_ID.fullmatch(leading_id(row.cells[column])):
                        report("schema", row.line, f"{column} starts with an id, e.g. {column}_0001 <name>")
                key = spec[1](row.cells).casefold()
                if key in seen:
                    report("schema", row.line, f"the same row key as line {seen[key]}; merge the two rows")
                seen.setdefault(key, row.line)

    def mentions(self, doc: Parsed) -> list[Mention]:
        out = [
            Mention(header_line(doc, name), leading_id(str(doc.header[name])), name)
            for name in ("task", "dataset")
            if isinstance(doc.header.get(name), str) and NODE_ID.fullmatch(leading_id(doc.header[name]))
        ]
        for table in tables(doc):
            for row in table.rows:
                for column, cell in row.cells.items():
                    if column in ID_COLUMNS and NODE_ID.fullmatch(leading_id(cell)):
                        out.append(Mention(row.line, leading_id(cell), column))
                    elif column == "source" and cell:
                        out += [Mention(row.line, part) for part in _sources(cell)]  # 来源由 locators 表达，不另设角色
                    elif not cited(cell):
                        out += [Mention(row.line, m[0]) for m in _SOURCE.finditer(cell)]
        return out + super().mentions(doc)

    def keyed(self, table: Table) -> tuple[str, Callable[[dict[str, str]], str]] | None:
        if _results(table):
            return "results", row_key
        if _papers(table):
            return "papers", lambda cells: leading_id(cells.get("paper", ""))
        return None

    def records(self, doc: Parsed) -> dict[str, str]:
        keys = [row_key(row.cells) for table in tables(doc) if _results(table) for row in table.rows]
        return {k.casefold(): k for k in keys}


def _sources(cell: str) -> list[str]:
    """``source`` 列中的引用：可写在方括号里，多个以分号隔开；不是引用的写法原样返回，由引用核对报告。"""
    if bracketed := cited(cell):
        return bracketed
    parts = [p.strip().strip("[]").strip() for p in _SPLIT.split(cell.strip())]
    return [p for p in parts if p]


LEADERBOARD = Leaderboard()

__all__ = ["LEADERBOARD", "Leaderboard", "row_key"]
