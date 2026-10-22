"""读者能读的原文范围：库中记录过的锚点，扩到所在的块（docs/designs/v3/evaluation.md §2.2）。

只读库的读者没有现成的原文，库把他带到哪里，他就读到哪里。记录过的锚点有三处来源，都按材料 id 归位：

- Content 的 ``anchor``，材料取它 ``FROM`` 边的 ``material_ref``；
- 带锚点的边（``anchor``）与产物的 ``USED`` 边（``locators``），材料取边上的 ``material_ref``；
- 产物文档正文中的来源引用 ``<id>::[<章节>::]<起>:<止>``，含旧版本的文档；开头按库的当前状态解析为材料。

每个锚点扩到所在的块：起止行不是空行时，分别向上、向下取到空行为止，即正文的整段、表格的整张（与 D 段落组取段落的
规则相同；正式语料的 288 张表中，从任一行扩出的块都恰是整张表）。相邻的块之间只隔空行时合并。
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from ..model.refs import normalize_ref
from ..model.schema import LOCATOR
from ..store.store import Store
from .materials import load_lines, materials

_HEAD = r"[a-z]+_[0-9a-f]{4,}"
_LINES = r"L?\d+(?:\s*(?:[-\u2013\u2014:~]|\.\.)\s*L?\d+)?"
# 正文中的来源引用：先认不带章节的写法（行号后不能紧跟数字、冒号、字母或小数点后的数字，免得把 5.2 节读成第 5 行），
# 再认带章节的写法（章节中不能出现另一个引用的开头）
SOURCE_IN_TEXT = re.compile(
    rf"(?P<head>{_HEAD})::(?:(?P<plain>{_LINES})(?![\d:\w]|\.\d)"
    rf"|(?:(?!{_HEAD}::)[^\n\[\]|`;])+?::(?P<sectioned>{_LINES}))"
)


def recorded(store: Store, ids: set[str]) -> dict[str, list[tuple[int, int]]]:
    """材料 id → 库中记录在它上面的锚点（起止行），只取 ``ids`` 中的材料。"""
    rows = store.query(
        """MATCH (c:Content)-[f:FROM]->() WHERE f.material_ref IN $ids
           UNWIND coalesce(c.anchor, []) AS loc RETURN f.material_ref AS material, loc
           UNION ALL
           MATCH ()-[r]->() WHERE r.material_ref IN $ids AND type(r) <> 'FROM'
           UNWIND coalesce(r.anchor, []) + coalesce(r.locators, []) AS loc RETURN r.material_ref AS material, loc""",
        ids=sorted(ids),
    )
    out: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for r in rows:
        if span := _span(str(r["loc"])):
            out[r["material"]].append(span)
    cited: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for document in _documents(store):
        for line in load_lines(store, document) or []:
            for m in SOURCE_IN_TEXT.finditer(line):
                if span := _span(m["plain"] or m["sectioned"]):
                    cited[m["head"]].append(span)
    for head, material in materials(store, set(cited)).items():
        if material["id"] in ids:
            out[material["id"]] += cited[head]
    return dict(out)


def block(lines: list[str], start: int, end: int) -> tuple[int, int]:
    """行范围扩到所在的块：起止行不是空行时，分别向上、向下取到空行为止。"""
    a, b = start, end
    if lines[a - 1].strip():
        while a > 1 and lines[a - 2].strip():
            a -= 1
    if lines[b - 1].strip():
        while b < len(lines) and lines[b].strip():
            b += 1
    return a, b


def readable(lines: list[str], spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """锚点扩成块后合并：重叠的、相接的、中间只隔空行的块合成一段。越界的锚点不算。"""
    blocks = sorted(block(lines, s, e) for s, e in spans if 1 <= s <= e <= len(lines))
    out: list[tuple[int, int]] = []
    for a, b in blocks:
        if out and all(not line.strip() for line in lines[out[-1][1] : a - 1]):
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _span(locator: str) -> tuple[int, int] | None:
    m = LOCATOR.fullmatch(normalize_ref(f"x::{locator}").partition("::")[2])
    return (int(m["start"]), int(m["end"])) if m else None


def _documents(store: Store) -> list[dict[str, Any]]:
    """所有产物文档的材料，含旧版本。"""
    return store.query(
        """MATCH (m:Material)-[:MATERIAL_OF]->(:Artifact)
           RETURN DISTINCT m.id AS id, m.path AS path, m.content_hash AS content_hash"""
    )


__all__ = ["SOURCE_IN_TEXT", "block", "readable", "recorded"]
