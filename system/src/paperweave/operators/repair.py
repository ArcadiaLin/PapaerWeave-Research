"""兜底修复模型给出的参数：按算子的 ``parameters``（JSON Schema）把常见的输出偏差改成声明的形状，再交给算子校验。

修复不提示给 Agent（结果里没有），只随 :class:`~paperweave.operators.base.Result` 交给入口记入日志（MCP 服务写在
stderr 与 ``PAPERWEAVE_MCP_LOG``）。规则都是确定的，修不了时原样交给算子，由算子照常报错：

- 声明为对象或数组、收到字符串：去掉 Markdown 代码块围栏后按 JSON 解析；解析失败时补齐末尾缺少的引号、``]``
  与 ``}`` 再试一次（模型输出长参数时常少写最后的括号）；仍不成时按 YAML 行内写法解析（``[{rel: USES}]``，键不加
  引号；与 graph-doc 同一套 1.2 规则）；解析结果的类型须是声明的类型；
- 声明为 integer、number 或 boolean、收到字符串：按字面转换（``"10"``、``"0.5"``、``"true"``）；
- 枚举：大小写不同的字符串换成枚举中的写法；T/F/U 判断收到 ``true`` / ``false`` 时换成 ``T`` / ``F``；
- ``anyOf``：按值的类型进入相应的分支；字符串以 ``[`` 或 ``{`` 开头且某个分支是数组或对象时按 JSON 解析；
- 声明为字符串数组、收到不是 JSON 的字符串：按逗号切开（``"Task,Issue,Model"``），没有逗号时是一项。

来源引用的写法偏差由 :func:`paperweave.model.refs.normalize_ref` 兜底，不在这里。
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from graph_doc import DocError, load

_FENCE = re.compile(r"```[A-Za-z]*\s*\n?(?P<body>.*?)\n?```", re.S)
_CLOSE = {"[": "]", "{": "}"}
_JUDGMENT = {"true": "T", "false": "F"}


def repair(parameters: Mapping[str, Any], request: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """按 ``parameters`` 修复 ``request`` 的各个参数。返回修复后的副本与修复记录（``<路径>: <做了什么>``）。"""
    notes: list[str] = []
    properties = parameters.get("properties", {})
    out = {k: _repair(properties[k], v, k, notes) if k in properties else v for k, v in request.items()}
    return out, notes


def _repair(schema: Mapping[str, Any], value: Any, at: str, notes: list[str]) -> Any:
    if "anyOf" in schema:
        branches = [b for b in schema["anyOf"] if isinstance(b, Mapping)]
        if isinstance(value, str) and value.lstrip()[:1] in ("[", "{"):
            wanted = {t for b in branches for t in _types(b)} & {"array", "object"}
            parsed = _json(value, wanted)
            if parsed is not None:
                notes.append(f"{at}: JSON text parsed")
                value = parsed
        branch = next((b for b in branches if _fits(value, b)), None)
        return _repair(branch, value, at, notes) if branch is not None else value
    types = _types(schema)
    if isinstance(value, str) and {"array", "object"} & set(types) and "string" not in types:
        parsed = _json(value, {"array", "object"} & set(types))
        if parsed is not None:
            notes.append(f"{at}: JSON text parsed")
            value = parsed
        elif "array" in types and _types(schema.get("items") or {}) == ["string"]:
            notes.append(f"{at}: {value!r} split on commas")
            value = [v.strip() for v in value.split(",") if v.strip()]
    elif isinstance(value, str) and types[:1] in (["integer"], ["number"], ["boolean"]):
        converted = _scalar(value, types[0])
        if converted is not None:
            notes.append(f"{at}: {value!r} read as {types[0]}")
            value = converted
    if "enum" in schema and value not in schema["enum"]:
        value = _enum(value, list(schema["enum"]), at, notes)
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        return {k: _repair(properties[k], v, f"{at}.{k}", notes) if k in properties else v for k, v in value.items()}
    if isinstance(value, list) and isinstance(schema.get("items"), Mapping):
        return [_repair(schema["items"], v, f"{at}[{n}]", notes) for n, v in enumerate(value)]
    return value


def _types(schema: Mapping[str, Any]) -> list[str]:
    declared = schema.get("type")
    if isinstance(declared, str):
        return [declared]
    return [t for t in declared if isinstance(t, str)] if isinstance(declared, list) else []


def _fits(value: Any, schema: Mapping[str, Any]) -> bool:
    if "enum" in schema or "const" in schema:
        return isinstance(value, str)
    checks = {"string": str, "object": dict, "array": list, "integer": int, "number": int | float, "boolean": bool}
    return any(isinstance(value, checks[t]) for t in _types(schema) if t in checks)


def _json(text: str, wanted: set[str]) -> Any:
    """按 JSON 解析成 ``wanted`` 中的类型；不成时返回 ``None``。"""
    body = text.strip()
    if fence := _FENCE.fullmatch(body):
        body = fence["body"].strip()
    for candidate in (body, _closed(body)):
        try:
            parsed = json.loads(candidate)
        except ValueError:
            continue
        if ("object" in wanted and isinstance(parsed, dict)) or ("array" in wanted and isinstance(parsed, list)):
            return parsed
    try:
        parsed = load(body)  # YAML 行内写法：键不加引号
    except DocError:
        return None
    if ("object" in wanted and isinstance(parsed, dict)) or ("array" in wanted and isinstance(parsed, list)):
        return parsed
    return None


def _closed(text: str) -> str:
    """补齐末尾没有闭合的字符串、``]`` 与 ``}``；多余的结尾逗号去掉。"""
    stack: list[str] = []
    in_string = escaped = False
    for ch in text:
        if in_string:
            escaped, in_string = (False, True) if escaped else (ch == "\\", ch != '"')
        elif ch == '"':
            in_string = True
        elif ch in _CLOSE:
            stack.append(_CLOSE[ch])
        elif ch in "]}" and stack and stack[-1] == ch:
            stack.pop()
    out = text + '"' if in_string else text
    return out.rstrip().rstrip(",") + "".join(reversed(stack))


def _scalar(text: str, type_: str) -> Any:
    word = text.strip()
    if type_ == "boolean":
        return {"true": True, "false": False}.get(word.lower())
    try:
        number = float(word)
    except ValueError:
        return None
    if type_ == "integer":
        return int(number) if number.is_integer() else None
    return number


def _enum(value: Any, options: list[Any], at: str, notes: list[str]) -> Any:
    if isinstance(value, bool) and {"T", "F"} <= set(options):
        notes.append(f"{at}: {value} read as {_JUDGMENT[str(value).lower()]}")
        return _JUDGMENT[str(value).lower()]
    if isinstance(value, str):
        word = value.strip().lower()
        if {"T", "F"} <= set(options) and word in _JUDGMENT:
            notes.append(f"{at}: {value!r} read as {_JUDGMENT[word]}")
            return _JUDGMENT[word]
        match = [o for o in options if isinstance(o, str) and o.lower() == word]
        if len(match) == 1:
            notes.append(f"{at}: {value!r} read as {match[0]!r}")
            return match[0]
    return value


__all__ = ["repair"]
