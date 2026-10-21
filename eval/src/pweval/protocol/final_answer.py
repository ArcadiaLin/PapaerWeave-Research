"""读者回答末尾的 Final answer 段：按题型生成格式要求，判分时用正则解析（docs/designs/v3/evaluation.md §7 第 3 条）。

字段只取每题 ``scoring`` 计分所需的部分。自动题（题库 ``auto.yml``，有 ``answer_type``）按题型给出格式；要点题
（``manual-rendered.yml``，金标准为 ``gold.points``）不要求格式，照常自由作答。所有读者条件用同一份格式。

解析只认格式本身：取最后一个 ``Final answer`` 标题之后的内容，按题型拆成字段，名称原样保留（判分时再按题库的
别名表归一）。缺少这一段或解析不出时返回 ``None``，由判分子代理读全文判定。T8 中“是否判定某值正确”不设字段，
设字段会诱导读者作出判定。
"""

from __future__ import annotations

import re
from typing import Any

LEAD = "End your reply with a section headed `Final answer`, exactly in this form:"

FORMATS = {
    "T1": "MSE: <value>\nMAE: <value>\nLocation: <table number, or lines, in the paper>",
    "T3": (
        "<method> | <paper> | <MSE> | <look-back as the paper states it, or \"not stated\">\n"
        "(one line per model; several lines only if several tie)"
    ),
    "T4": "<method>\n(one method per line; write none if there are none)",
    "T5": (
        "Beaten:\n<method>\n(one method per line; write none if there are none)\n"
        "Later papers:\n<baseline> | <paper>\n(one pair per line; write none if there are none)"
    ),
    "T6": "<method>\n(one method per line; write none if there are none)",
    "T7": "<paper> | own\n<paper> | cited: <source>\n<paper> | not stated\n(one line per paper, with one of the three)",
    "T8": "<paper> | <MSE> | <table or setting, optional>\n(one line per paper)",
}
NOTE = "Write <paper> as its arXiv id or its title, and <method> as the paper names it."

HEADING = re.compile(r"^[ \t]*(?:#+[ \t]*)?(?:\*\*)?Final answer(?:\*\*)?[ \t]*:?[ \t]*(?:\*\*)?[ \t]*$", re.I | re.M)
NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
KEY_VALUE = re.compile(r"^(MSE|MAE|Location):\s*(.+)$", re.I)
NONE = re.compile(r"^none\.?$", re.I)


def is_auto(probe: dict[str, Any]) -> bool:
    return "answer_type" in probe and "points" not in (probe.get("gold") or {})


def format_for(probe: dict[str, Any]) -> str | None:
    """题的 Final answer 格式要求（接在提示语末尾）；要点题与未定义格式的题型为 ``None``。"""
    if not is_auto(probe) or probe["template"] not in FORMATS:
        return None
    body = FORMATS[probe["template"]]
    note = f"\n\n{NOTE}" if "<paper>" in body or "<method>" in body else ""
    return f"{LEAD}\n\nFinal answer\n{body}{note}"


def section(text: str) -> str | None:
    """最后一个 ``Final answer`` 标题之后的内容（去掉代码围栏）；没有标题时为 ``None``。"""
    heads = list(HEADING.finditer(text))
    if not heads:
        return None
    return re.sub(r"^\s*```\w*\s*$", "", text[heads[-1].end() :], flags=re.M).strip()


def _lines(body: str) -> list[str]:
    """内容行：去掉列表符号、粗体与空行，丢掉格式说明式的括号行。"""
    out = []
    for raw in body.splitlines():
        line = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", raw).replace("**", "").strip().strip("`").strip()
        if line and not (line.startswith("(") and line.endswith(")")):
            out.append(line)
    return out


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _numbers(text: str) -> list[str]:
    return NUMBER.findall(text)


def parse(template: str, text: str) -> dict[str, Any] | None:
    """按题型解析 Final answer 段；没有这一段或形式不对时为 ``None``。数值保留原文写法（比较时按数值相等）。"""
    body = section(text)
    if body is None:
        return None
    lines = _lines(body)
    parser = _PARSERS.get(template)
    return parser(lines) if parser else None


def _t1(lines: list[str]) -> dict[str, Any] | None:
    fields = {}
    for line in lines:
        if m := KEY_VALUE.match(line):
            fields[m[1].lower()] = m[2].strip()
    if not {"mse", "mae"} <= fields.keys():
        return None
    mse, mae = _numbers(fields["mse"]), _numbers(fields["mae"])
    return {
        "mse": mse[0] if mse else None,
        "mae": mae[0] if mae else None,
        "location": fields.get("location"),
    }


def _t3(lines: list[str]) -> dict[str, Any] | None:
    rows = []
    for line in lines:
        cells = _cells(line)
        if len(cells) == 4:
            mse = _numbers(cells[2])
            rows.append({"method": cells[0], "paper": cells[1], "mse": mse[0] if mse else None, "lookback": cells[3]})
    return {"best": rows} if rows else None


def _set(lines: list[str]) -> dict[str, Any] | None:
    if len(lines) == 1 and NONE.match(lines[0]):
        return {"methods": []}
    methods = [line for line in lines if "|" not in line and not NONE.match(line)]
    return {"methods": methods} if methods else None


def _t5(lines: list[str]) -> dict[str, Any] | None:
    parts: dict[str, list[str]] = {}
    current = None
    for line in lines:
        head = line.rstrip(":").strip().lower()
        if head in ("beaten", "later papers"):
            current = head
            parts[current] = []
        elif current is not None and not NONE.match(line):
            parts[current].append(line)
    if set(parts) != {"beaten", "later papers"}:
        return None
    pairs = [_cells(line) for line in parts["later papers"]]
    if any(len(p) != 2 for p in pairs):
        return None
    return {"beaten": parts["beaten"], "later_papers": [{"baseline": b, "paper": p} for b, p in pairs]}


def _t7(lines: list[str]) -> dict[str, Any] | None:
    entries = []
    for line in lines:
        cells = _cells(line)
        if len(cells) != 2:
            continue
        paper, said = cells
        if m := re.match(r"cited\s*:\s*(.+)$", said, re.I):
            entries.append({"paper": paper, "provenance": "cited", "from": m[1].strip()})
        elif re.fullmatch(r"own\.?", said, re.I):
            entries.append({"paper": paper, "provenance": "own"})
        elif re.fullmatch(r"not stated\.?", said, re.I):
            entries.append({"paper": paper, "provenance": "not stated"})
        else:
            return None
    return {"entries": entries} if entries else None


def _t8(lines: list[str]) -> dict[str, Any] | None:
    pairs = []
    for line in lines:
        cells = _cells(line)
        if len(cells) in (2, 3) and (mse := _numbers(cells[1])):
            table = cells[2] if len(cells) == 3 and cells[2] else None
            pairs.append({"paper": cells[0], "mse": mse[0], "table": table})
    return {"pairs": pairs} if pairs else None


_PARSERS = {"T1": _t1, "T3": _t3, "T4": _set, "T5": _t5, "T6": _set, "T7": _t7, "T8": _t8}


__all__ = ["FORMATS", "format_for", "is_auto", "parse", "section"]
