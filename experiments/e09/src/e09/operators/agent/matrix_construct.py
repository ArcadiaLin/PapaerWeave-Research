"""MatrixConstruct：把跨论文的比较组织成一张矩阵（docs/designs/v2/operators.md §4.8）。

矩阵由 Agent 填写，中间件只校验表格结构。记录键为 ``<row>~<col>``。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ...artifact.write import Output, Problems
from ..base import DraftForm, agent_operator, schema
from ._common import (
    FIELD_TYPES,
    as_list,
    bullets,
    cell_text,
    check_keys,
    example_cell,
    is_key,
    is_text,
    is_typed,
    parse_cell,
    parse_type,
    table,
    type_name,
)


def matrix(params: Mapping[str, Any], payload: Mapping[str, Any], problems: Problems) -> Output:
    """Agent 填写的矩阵：只校验表格结构，每个 (行, 列) 恰有一格。``basis`` 与 ``note`` 可选，值可为空。

    格子的类型与 Extract 的字段类型相同（T/F/U 写作 ``enum[T, F, U]``）。记录键为 ``<row>~<col>``。不核对格子的
    值与所引记录是否一致，不判断可比性，不排序、不汇总。
    """
    out = Output("", "")
    check_keys(params, "params", {"rows", "columns", "cell"}, {"rows", "columns", "cell"}, problems)
    check_keys(payload, "payload", {"cells"}, {"cells", "note"}, problems)
    rows = _axis(params.get("rows"), "params.rows", out, problems)
    columns = _axis(params.get("columns"), "params.columns", out, problems)
    cell = params.get("cell")
    type_: Any = None
    question = None
    if not isinstance(cell, Mapping):
        problems.add("schema", "params.cell", "{type, question?}")
    else:
        check_keys(cell, "params.cell", {"type"}, {"type", "question"}, problems)
        type_ = parse_type(cell.get("type"))
        if type_ is None:
            problems.add("schema", "params.cell.type", f"one of {list(FIELD_TYPES)} or enum[a, b, ...]")
        question = cell.get("question")
        if question is not None and not is_text(question):
            problems.add("schema", "params.cell.question", "a non-empty string")
            question = None
    note = payload.get("note")
    if note is not None and not is_text(note):
        problems.add("schema", "payload.note", "a non-empty string")

    cells: dict[tuple[str, str], dict[str, Any]] = {}
    attempted: set[tuple[str, str]] = set()  # 给了但不合格的格子已另行报告，不再报缺少
    for i, given in enumerate(as_list(payload.get("cells"), "payload.cells", problems)):
        at = f"payload.cells[{i}]"
        if not isinstance(given, Mapping):
            problems.add("schema", at, "a cell {row, col, value, basis?, note?}")
            continue
        check_keys(given, at, {"row", "col", "value"}, {"row", "col", "value", "basis", "note"}, problems)
        row, col = given.get("row"), given.get("col")
        if row not in rows:
            problems.add("schema", f"{at}.row", f"not a declared row: {row!r}")
        if col not in columns:
            problems.add("schema", f"{at}.col", f"not a declared column: {col!r}")
        if row not in rows or col not in columns:
            continue
        attempted.add((row, col))
        if (row, col) in cells:
            problems.add("schema", at, f"a second cell for {row}~{col}")
            continue
        entry: dict[str, Any] = {"row": row, "col": col, "value": given.get("value")}
        ok = True
        value = entry["value"]
        if value is not None and type_ is not None:
            if not is_typed(value, type_):
                problems.add("schema", f"{at}.value", f"not a {type_name(type_)}: {value!r}")
                ok = False
            elif type_ == "ref":
                out.refs.append((f"{at}.value", value))
        basis = given.get("basis")
        basis = [basis] if isinstance(basis, str) else basis
        if basis is not None:
            if not isinstance(basis, list) or not basis or not all(is_text(b) for b in basis):
                problems.add("schema", f"{at}.basis", "a reference or a list of references")
                ok = False
            else:
                out.refs += [(f"{at}.basis", b) for b in basis]
                entry["basis"] = list(basis)
        cell_note = given.get("note")
        if cell_note is not None:
            if not is_text(cell_note):
                problems.add("schema", f"{at}.note", "a non-empty string")
                ok = False
            else:
                entry["note"] = cell_note.strip()
        if ok:
            cells[(row, col)] = entry
    if absent := [f"{r}~{c}" for r in rows for c in columns if (r, c) not in attempted]:
        problems.add("schema", "payload.cells", f"missing cells: {', '.join(absent)}")

    def shown(entry: dict[str, Any] | None) -> str:
        if entry is None:
            return "—"
        text = cell_text(entry["value"], type_)
        return text + "".join(f" [{b}]" for b in entry.get("basis", []))

    grid = [[r, *(shown(cells.get((r, c))) for c in columns)] for r in rows]
    body = [f"**Cell:** {question.strip()}"] if question else []
    body.append(table(["", *columns], grid))
    body += ["**Rows**", bullets(f"`{k}`: {_label(v)}" for k, v in rows.items())]
    body += ["**Columns**", bullets(f"`{k}`: {_label(v)}" for k, v in columns.items())]
    noted = [e for e in (cells.get((r, c)) for r in rows for c in columns) if e and "note" in e]
    if noted:
        body += ["## Notes", bullets(f"`{e['row']}~{e['col']}`: {e['note']}" for e in noted)]
    if is_text(note):
        body.append(f"**Note:** {note.strip()}")
    out.title = f"Matrix: {question.strip()}" if question else f"Matrix {len(rows)} × {len(columns)}"
    out.body = "\n\n".join(body)
    out.data = {
        "rows": rows,
        "columns": columns,
        "cell": {"type": cell.get("type"), **({"question": question.strip()} if question else {})}
        if isinstance(cell, Mapping)
        else None,
        "cells": [cells[(r, c)] for r in rows for c in columns if (r, c) in cells],
    }
    if is_text(note):
        out.data["note"] = note.strip()
    return out


def _axis(value: Any, at: str, out: Output, problems: Problems) -> dict[str, Any]:
    """行或列：键 → 引用或 ``{text}``。引用的 ``USED.role`` 记这个键。"""
    if not isinstance(value, Mapping) or not value:
        problems.add("schema", at, "a non-empty mapping of key to a reference or {text}")
        return {}
    axis: dict[str, Any] = {}
    for key, label in value.items():
        where = f"{at}.{key}"
        if not is_key(key):
            problems.add("schema", where, "keys use letters, digits, _ . and -")
        elif is_text(label):
            axis[key] = label
            out.refs.append((where, label))
            out.roles.setdefault(label, []).append(key)
        elif isinstance(label, Mapping) and set(label) == {"text"} and is_text(label["text"]):
            axis[key] = {"text": label["text"].strip()}
        else:
            problems.add("schema", where, "a reference or {text}")
    return axis


def _label(value: Any) -> str:
    return value["text"] if isinstance(value, Mapping) else f"[{value}]"


# ── CSV 草稿：长表，一格一行 ──────────────────────────────────────────

COLUMNS = ["row", "col", "value", "basis", "note"]


def _cell_type(params: Mapping[str, Any]) -> Any:
    cell = params.get("cell")
    return parse_type(cell.get("type")) if isinstance(cell, Mapping) else None


def _columns(params: Mapping[str, Any]) -> tuple[list[str], set[str]] | None:
    rows, columns = params.get("rows"), params.get("columns")
    if not isinstance(rows, Mapping) or not rows or not isinstance(columns, Mapping) or not columns:
        return None
    if _cell_type(params) is None:
        return None
    return COLUMNS, {"row", "col", "value"}


def _example(params: Mapping[str, Any]) -> dict[str, str]:
    return {
        "row": str(next(iter(params["rows"]))),
        "col": str(next(iter(params["columns"]))),
        "value": example_cell(_cell_type(params)),
        "basis": "<artifact id>#<record key>;<source reference>",
        "note": "",
    }


def _cell(params: Mapping[str, Any], cells: dict[str, str]) -> dict[str, Any]:
    """一行转成一格：``value`` 为空时是 ``null``；``basis`` 中的多个引用用 ``;`` 分隔。"""
    text = cells.get("value", "")
    entry: dict[str, Any] = {
        "row": cells.get("row", ""),
        "col": cells.get("col", ""),
        "value": parse_cell(text, _cell_type(params)) if text else None,
    }
    if basis := [b.strip() for b in cells.get("basis", "").split(";") if b.strip()]:
        entry["basis"] = basis
    if note := cells.get("note"):
        entry["note"] = note
    return entry


MATRIX_CONSTRUCT = agent_operator(
    name="MatrixConstruct",
    params=schema(
        {
            "rows": {"type": "object"},
            "columns": {"type": "object"},
            "cell": schema({"type": {"type": "string"}, "question": {"type": "string"}}, ["type"]),
        },
        ["rows", "columns", "cell"],
    ),
    payload=schema(
        {
            "cells": {
                "type": "array",
                "items": {"type": "object"},
            },
            "note": {"type": "string"},
        },
        ["cells"],
    ),
    validate=matrix,
    draft=DraftForm(key="cells", columns=_columns, example=_example, item=_cell),
)


__all__ = ["MATRIX_CONSTRUCT"]
