"""Agent 算子共用的校验与正文部件：字段类型、逐项判断（T/F/U）、项键与 Markdown 表格。

判断的取值：``T`` 在声明的条件与依据下成立，``F`` 有依据判断不成立，``U`` 依据不足、相互冲突或条件含义不明。
``T`` 与 ``F`` 必须给出 ``basis``，``U`` 必须给出 ``reason``。
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from ...artifact.write import Output, Problems
from ...model.refs import RECORD_KEY
from ..base import STRING, one_or_many

VALUES = ("T", "F", "U")


FIELD_TYPES = ("string", "number", "integer", "boolean", "ref")


_ENUM = re.compile(r"enum\[(?P<values>[^\]]*)\]")

JUDGMENT = {
    "type": "object",
    "properties": {
        "value": {"enum": list(VALUES)},
        "basis": one_or_many(STRING),
        "reason": {"type": "string"},
    },
}


# ── 字段类型（Extract 的字段、MatrixConstruct 的格子） ─────────────────


def parse_type(value: Any) -> Any:
    if value in FIELD_TYPES:
        return value
    match = _ENUM.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        return None
    options = tuple(v.strip() for v in match["values"].split(",") if v.strip())
    return options or None


def is_typed(value: Any, type_: Any) -> bool:
    if isinstance(type_, tuple):
        return value in type_
    if type_ == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if type_ == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_ == "boolean":
        return isinstance(value, bool)
    return isinstance(value, str)  # string、ref


def type_name(type_: Any) -> str:
    return f"enum{list(type_)}" if isinstance(type_, tuple) else type_


def parse_cell(text: str, type_: Any) -> Any:
    """草稿 CSV 中一格的文字按声明的类型取值：``number`` 取整数或小数，``integer`` 取整数，``boolean`` 取
    ``true`` / ``false``，其余（``string``、``ref``、枚举）照原文。解析不了时照原文，由校验报告类型不符。"""
    try:
        if type_ == "number":
            return int(text) if re.fullmatch(r"[+-]?\d+", text) else float(text)
        if type_ == "integer":
            return int(text)
    except ValueError:
        return text
    if type_ == "boolean":
        return {"true": True, "false": False}.get(text.lower(), text)
    return text


def example_cell(type_: Any) -> str:
    """模板中示例行的一格。"""
    if isinstance(type_, tuple):
        return type_[0]
    return {"number": "0.375", "integer": "96", "boolean": "true", "ref": "<id>"}.get(type_, "<text>")


def cell_text(value: Any, type_: Any) -> str:
    if value is None:
        return "—"
    if type_ == "ref":
        return f"[{value}]"
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


# ── 逐项判断（Check、Verify、Filter） ─────────────────────────────────


def items_of(value: Any, minimum: int, out: Output, problems: Problems) -> dict[str, str]:
    if not isinstance(value, Mapping) or len(value) < minimum:
        problems.add("schema", "params.items", f"a mapping of at least {minimum} item key(s) to references")
        return {}
    items: dict[str, str] = {}
    for key, ref in value.items():
        at = f"params.items.{key}"
        if not is_key(key):
            problems.add("schema", at, "item keys use letters, digits, _ . and -")
        elif not is_text(ref):
            problems.add("schema", at, "a reference")
        else:
            items[key] = ref
            out.refs.append((at, ref))
            out.roles.setdefault(ref, []).append(key)
    return items


def judgment_shape(
    value: Any,
    at: str,
    extra: set[str],
    problems: Problems,
    required: frozenset[str] | None = None,
) -> bool:
    if not isinstance(value, Mapping):
        problems.add("schema", at, "a judgment {value, basis?, reason?}")
        return False
    allowed = {"value", "basis", "reason", *extra}
    check_keys(value, at, {"value", *(extra if required is None else required)}, allowed, problems)
    return True


def verdict_of(judgment: Mapping[str, Any], at: str, out: Output, problems: Problems) -> dict[str, Any] | None:
    """``T`` 与 ``F`` 必须有 ``basis``，``U`` 必须有 ``reason``；``basis`` 中的引用必须属于 inputs。"""
    value, basis, reason = judgment.get("value"), judgment.get("basis"), judgment.get("reason")
    if value not in VALUES:
        problems.add("judgment", f"{at}.value", "T, F or U; an interrupted or malformed run is an error, not U")
        return None
    basis = [basis] if isinstance(basis, str) else basis
    if basis is not None and (not isinstance(basis, list) or not all(is_text(b) for b in basis)):
        problems.add("judgment", f"{at}.basis", "a reference or a list of references")
        return None
    if reason is not None and not is_text(reason):
        problems.add("judgment", f"{at}.reason", "a non-empty string")
        return None
    if value in ("T", "F") and not basis:
        problems.add("judgment", f"{at}.basis", f"{value} needs the references it rests on")
        return None
    if value == "U" and not reason:
        problems.add("judgment", f"{at}.reason", "U needs a reason: insufficient, conflicting or unclear evidence")
        return None
    out.refs += [(f"{at}.basis", b) for b in basis or []]
    verdict: dict[str, Any] = {"value": value}
    if basis:
        verdict["basis"] = list(basis)
    if reason:
        verdict["reason"] = reason.strip()
    return verdict


def why(judgment: Mapping[str, Any]) -> str:
    parts = []
    if judgment.get("basis"):
        parts.append("basis " + ", ".join(f"[{r}]" for r in judgment["basis"]))
    if judgment.get("reason"):
        parts.append(judgment["reason"])
    return " — " + "; ".join(parts) if parts else ""


# ── 形状与正文 ─────────────────────────────────────────────────────────


def check_keys(value: Any, at: str, required: set[str], allowed: set[str], problems: Problems) -> None:
    if not isinstance(value, Mapping):
        problems.add("schema", at, f"a mapping with {sorted(allowed)}")
        return
    if unknown := sorted(set(value) - allowed):
        problems.add("schema", at, f"unknown keys {unknown}; allowed {sorted(allowed)}")
    for key in sorted(required - set(value)):
        problems.add("schema", f"{at}.{key}", "required")


def as_list(value: Any, at: str, problems: Problems) -> list[Any]:
    if not isinstance(value, list):
        problems.add("schema", at, "a list")
        return []
    return value


def is_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def is_key(value: Any) -> bool:
    return isinstance(value, str) and bool(RECORD_KEY.fullmatch(value))


def head(text: str) -> str:
    line = " ".join(text.split())
    return repr(line if len(line) <= 60 else line[:57] + "...")


def bullets(lines: Iterable[str]) -> str:
    return "\n".join(f"- {line}" for line in lines)


def table(columns: list[str], rows: list[list[str]]) -> str:
    """Markdown 表格；单元格中的 ``|`` 与换行会转义。"""

    def cell(value: str) -> str:
        return value.replace("|", "\\|").replace("\n", " ")

    lines = ["| " + " | ".join(cell(c) for c in columns) + " |", "|" + "---|" * len(columns)]
    lines += ["| " + " | ".join(cell(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)
