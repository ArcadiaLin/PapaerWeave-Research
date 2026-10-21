"""读取结果的 YAML 文本：与 graph-doc 同形，并用注释给出 id 的名称与锚点的章节。

PyYAML 不能写注释，所以这里自己写一个只覆盖读取结果形状的小写法器：映射、标量、标量的列表。写法与 graph-doc 的
书写规则一致（docs/designs/v3/tools.md）：长文字用 ``|`` 块，短文字在需要时用双引号，不用单引号，不写 ``{...}``
行内映射；行内 ``[...]`` 只放 id、标识与行号范围这类短项。写出的文本经 :func:`graph_doc.load` 读回与原数据相同
（见测试）。

注释：值或键是 ``names`` 中的 id 时，行末加 ``# <名称>``；``notes`` 按路径（如 ``("exp_0042", "anchor")``）给出
其他行末注释，如锚点的章节。注释接在值后空两格，不对齐到固定列：f1 中对齐用的空格占 search 返回的约一成。
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

INDENT = "  "
COMMENT_GAP = "  "  # 值与行末注释之间
_PLAIN = re.compile(r"[A-Za-z0-9_$(][^\n]*")
_SPECIAL_START = tuple("!&*%@`'\"[]{}>|#,?-:")
_RESOLVES = re.compile(
    r"(?:~|null|Null|NULL|true|True|TRUE|false|False|FALSE|[-+]?[0-9]+|"
    r"[-+]?(?:\.[0-9]+|[0-9]+(?:\.[0-9]*)?)(?:[eE][-+]?[0-9]+)?)"
)
FLOW_WIDTH = 100


def render(data: Mapping[str, Any], names: Mapping[str, str] | None = None, notes: Mapping[tuple, str] | None = None) -> str:
    out: list[str] = []
    _mapping(data, 0, (), out, names or {}, notes or {})
    return "\n".join(out) + "\n"


def _mapping(data: Mapping[str, Any], depth: int, path: tuple, out: list[str], names: Mapping, notes: Mapping) -> None:
    pad = INDENT * depth
    for key, value in data.items():
        here = (*path, key)
        head = f"{pad}{_key(key)}:"
        comment = notes.get(here) or (names.get(key) if isinstance(key, str) else None)
        if isinstance(value, Mapping):
            out.append(_with(head, comment))  # 空映射写成空值，不写 {}
            _mapping(value, depth + 1, here, out, names, notes)
        elif isinstance(value, list):
            _list(head, value, depth, here, out, names, notes, comment)
        elif isinstance(value, str) and _block(value):
            out.append(_with(head + " |", comment))
            out.extend(f"{pad}{INDENT}{line}".rstrip() for line in value.rstrip("\n").split("\n"))
        else:
            comment = comment or (names.get(value) if isinstance(value, str) else None)
            out.append(_with(f"{head} {_scalar(value)}", comment))


def _list(head: str, value: list, depth: int, path: tuple, out: list[str], names: Mapping, notes: Mapping, comment: str | None) -> None:
    pad = INDENT * depth
    if not value:
        out.append(_with(head + " []", comment))
        return
    if any(isinstance(v, Mapping) for v in value):  # 映射的列表：每项写成 "- " 开头的块
        out.append(_with(head, comment))
        for n, v in enumerate(value):
            if not isinstance(v, Mapping):
                out.append(f"{pad}{INDENT}- {_scalar(v)}")
                continue
            block: list[str] = []
            _mapping(v, depth + 2, (*path, n), block, names, notes)
            first = block[0][len(INDENT) * (depth + 2) :]
            out.append(f"{pad}{INDENT}- {first}")
            out.extend(block[1:])
        return
    items = [_scalar(v) for v in value]
    flow = f"[{', '.join(items)}]"
    labelled = [names.get(v) for v in value if isinstance(v, str) and v in names]
    if len(head) + len(flow) <= FLOW_WIDTH and all(_flowable(v) for v in value) and (len(labelled) <= 1 or comment):
        out.append(_with(f"{head} {flow}", comment or (labelled[0] if labelled else None)))
        return
    out.append(_with(head, comment))
    for v, item in zip(value, items, strict=True):
        out.append(_with(f"{pad}{INDENT}- {item}", names.get(v) if isinstance(v, str) else None))


def _with(line: str, comment: str | None) -> str:
    if not comment:
        return line
    comment = " ".join(comment.split())
    if len(comment) > 70:
        comment = comment[:69].rstrip() + "…"
    return f"{line}{COMMENT_GAP}# {comment}"


def _key(key: Any) -> str:
    return key if isinstance(key, str) and _safe(key) else json.dumps(str(key), ensure_ascii=False)


def _block(value: str) -> bool:
    return "\n" in value or len(value) > 80


def _flowable(value: Any) -> bool:
    return not isinstance(value, str) or (_safe(value) and "," not in value and len(value) <= 40)


def _safe(text: str) -> bool:
    """可以不加引号的写法：不以特殊字符开头，不含 ``: `` 与 `` #``，读回仍是字符串。"""
    return (
        bool(text)
        and bool(_PLAIN.fullmatch(text))
        and not text.startswith(_SPECIAL_START)
        and ": " not in text
        and " #" not in text
        and not text.endswith((":", " "))
        and "[" not in text
        and "]" not in text
        and "{" not in text
        and "}" not in text
        and not _RESOLVES.fullmatch(text)
    )


def _scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return json.dumps(value)
    text = str(value)
    return text if _safe(text) else json.dumps(text, ensure_ascii=False)


__all__ = ["render"]
