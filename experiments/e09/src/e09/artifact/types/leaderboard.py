"""Leaderboard：共同维护的结果表（docs/designs/v2/operators.md §4.2）。

一份对应一个（任务、数据集、设置），跨论文、跨预测长度。

- **身份键：** 头部的 ``task``、``dataset``（写成 id，后面可跟名字或注释）与 ``setting``（映射或文字）。
- **结果表**是含 ``method``、``paper``、``pred_len``、``lookback`` 列的表，行键为（方法、变体、论文、预测长度、
  look-back），``variant`` 列可以没有。方法与论文的单元格以 id 开头。行键的各字段按字符串比较，可以写说明文字。
- **论文覆盖表**是含 ``paper`` 列、不含 ``method`` 列的表，行键为论文。
- **引用：** 头部的 ``task``、``dataset``；表中 ``method``、``paper`` 列开头的 id；``source`` 列的来源引用；
  表格单元格中不带方括号的来源引用（如 ``Table 1 (material_a1::4.2::112:140)``）；正文中方括号里的引用。
- **轻度规则**（只看这次新增与修改的行）：须带 ``source``，且落在该行 ``paper`` 的材料中；``metrics`` 中声明的列
  须为数字或留空。只警告的：数字没有出现在所引的行中；列与表单不同；``lookback``、``pred_len`` 写成文字；
  ``role``、``origin`` 的取值不在表单中。
- **附注**（读取时现算）：每位编辑者写的结果行数；所引论文已有新版本的行；同一格（方法、变体、预测长度、指标）
  有几个值，分开“同一篇论文给了不同的值”（多半有人抄错，或 look-back 不同）与“不同论文的值”（正常的并存）。
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from typing import Any

from ...model.refs import NODE_ID, cited
from ..document import Parsed, Table, tables
from .base import (
    ArtifactType,
    Authors,
    Lookup,
    Mention,
    Report,
    header_line,
    identity,
    leading_id,
    normalize,
)

ROW_KEY = ("method", "variant", "paper", "pred_len", "lookback")
REQUIRED_COLUMNS = ("method", "paper", "pred_len", "lookback")
ID_COLUMNS = ("method", "paper")
FORM = ("method", "variant", "paper", "role", "origin", "lookback", "pred_len")  # 之后是 metrics 中的列与 source
ROLES = frozenset({"target", "baseline"})
ORIGINS = frozenset({"run", "cited"})
DIRECTIONS = frozenset({"lower", "higher"})
_NUMBER = re.compile(r"-?\d*\.?\d+(?:[eE]-?\d+)?")
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
    identity_fields = ("task", "dataset", "setting")

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
        metrics = doc.header.get("metrics")
        if metrics is not None and not (
            isinstance(metrics, Mapping) and metrics and all(v in DIRECTIONS for v in metrics.values())
        ):
            report("schema", header_line(doc, "metrics"), "metrics maps each metric column to lower or higher")
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

    def rules(self, doc: Parsed, changed: set[int], lookup: Lookup, report: Report, warn: Report) -> None:
        metrics = _metrics(doc.header)
        results = [t for t in tables(doc) if _results(t)]
        if not metrics and any(row.line in changed for t in results for row in t.rows):
            msg = "declare metrics, e.g. {MSE: lower, MAE: lower}: the numbers in those columns are checked"
            warn("structure", header_line(doc, "metrics"), msg)
        for table in results:
            rows = [row for row in table.rows if row.line in changed]
            if not rows:
                continue
            form = [*FORM, *metrics, "source"]
            missing = [c for c in form if c not in table.columns]
            extra = [c for c in table.columns if c not in form]
            if missing or extra:
                msg = f"the columns differ from the form | {' | '.join(form)} |: missing {missing}, extra {extra}"
                warn("structure", table.lines[0], msg)
            for row in rows:
                self._row(row.line, row.cells, metrics, lookup, report, warn)

    def _row(
        self, line: int, cells: dict[str, str], metrics: list[str], lookup: Lookup, report: Report, warn: Report
    ) -> None:
        for column, allowed in (("role", ROLES), ("origin", ORIGINS)):
            if cells.get(column) and cells[column] not in allowed:
                warn("format", line, f"{column} is one of {sorted(allowed)}, not {cells[column]!r}")
        for column in ("lookback", "pred_len"):
            if cells.get(column) and _number(cells[column]) is None:
                warn("format", line, f"{column} {cells[column]!r} is not a number; fine if the paper states it so")
        values = {m: cells[m] for m in metrics if cells.get(m)}
        for metric, value in values.items():
            if _number(value) is None:
                report("schema", line, f"{metric} is a number or left empty, not {value!r}")
        refs = _sources(cells.get("source", ""))
        if not refs:
            report("schema", line, "source is required: the lines of the paper that report this row")
            return
        paper = leading_id(cells.get("paper", ""))
        found = [f for f in (lookup(r) for r in refs) if f is not None]
        if any(f.owner != paper for f in found):
            report("schema", line, f"source must cite the material of {paper}, the row's paper")
            return
        numbers = [x for f in found for text in f.lines or [] for x in _numbers(text)]
        for metric, value in values.items():
            number = _number(value)
            if number is not None and found and not _within(value, number, numbers):
                warn("number", line, f"{metric} {value} does not appear in the cited lines {'; '.join(refs)}")

    def notes(self, doc: Parsed, authors: Authors, lookup: Lookup) -> dict[str, Any]:
        rows = [row for table in tables(doc) if _results(table) for row in table.rows]
        out: dict[str, Any] = {}
        counts: dict[str, list[int]] = {}
        for row in rows:
            author, version = authors.get(row.line, ("?", 0))
            counts.setdefault(author, []).append(version)
        if counts:
            out["rows_by_contributor"] = [
                {"editor": a, "rows": len(vs), "versions": sorted(set(vs))} for a, vs in counts.items()
            ]
        superseded = []
        for row in rows:
            for ref in _sources(row.cells.get("source", "")):
                found = lookup(ref)
                if found is not None and found.superseded_by:
                    entry = {"at": row.line, "row": row_key(row.cells), "source": ref, "newer": found.superseded_by}
                    superseded.append(entry)
        if superseded:
            out["superseded_sources"] = superseded
        if several := _several(rows, _metrics(doc.header)):
            out["cells_with_several_values"] = several
        return out


def _metrics(header: Mapping[str, Any]) -> list[str]:
    metrics = header.get("metrics")
    return [str(m) for m in metrics] if isinstance(metrics, Mapping) else []


def _number(text: str) -> float | None:
    try:
        return float(text.replace(",", "").strip())
    except ValueError:
        return None


def _numbers(text: str) -> list[float]:
    return [float(m[0]) for m in _NUMBER.finditer(text.replace(",", ""))]


def _within(written: str, value: float, numbers: list[float]) -> bool:
    """``value`` 是否出现在 ``numbers`` 中：按写出的小数位数取半个单位的容差，如 0.375 容许 0.3745–0.3755。"""
    decimals = len(written.strip().split(".", 1)[1]) if "." in written else 0
    tolerance = 0.5 * 10**-decimals + 1e-12
    return any(abs(value - n) <= tolerance for n in numbers)


def _several(rows: list[Any], metrics: list[str]) -> list[dict[str, Any]]:
    """同一格（方法、变体、预测长度、指标）上的几个值。"""
    cells: dict[tuple[str, str, str], list[Any]] = {}
    for row in rows:
        key = (
            leading_id(row.cells.get("method", "")),
            normalize(row.cells.get("variant", "")),
            row.cells.get("pred_len", ""),
        )
        cells.setdefault(key, []).append(row)
    out = []
    for (method, variant, horizon), group in cells.items():
        for metric in metrics:
            values = [
                {
                    "value": r.cells[metric],
                    "paper": leading_id(r.cells.get("paper", "")),
                    "lookback": r.cells.get("lookback", ""),
                    "at": r.line,
                }
                for r in group
                if r.cells.get(metric)
            ]
            if len({_number(v["value"]) for v in values}) < 2:
                continue
            by_paper: dict[str, set[float | None]] = {}
            for v in values:
                by_paper.setdefault(v["paper"], set()).add(_number(v["value"]))
            same = any(len(vs) > 1 for vs in by_paper.values())
            cell = " · ".join(p for p in (method, variant, horizon, metric) if p)
            out.append({"cell": cell, "kind": "same paper" if same else "different papers", "values": values})
    return out


def _sources(cell: str) -> list[str]:
    """``source`` 列中的引用：可写在方括号里，多个以分号隔开；不是引用的写法原样返回，由引用核对报告。"""
    if bracketed := cited(cell):
        return bracketed
    parts = [p.strip().strip("[]").strip() for p in _SPLIT.split(cell.strip())]
    return [p for p in parts if p]


LEADERBOARD = Leaderboard()

__all__ = ["LEADERBOARD", "Leaderboard", "row_key"]
