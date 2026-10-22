"""共同产物的轻度规则与附注所需的来源：来源引用 → 所指的来源及所引的行（paperweave.artifact.types.Lookup）。

产物中的来源引用自带来源 ID（``2205.13504v2::120:135``、``<仓库>@<commit>::<文件>::<起>:<止>``），按只读来源目录解析；
``owners`` 是库中声明这个来源的 Paper 或 Code，``superseded_by`` 是库中声明过的同一 arXiv 编号的更新版本
（docs/experiments/f3/2026-10-22-f3-design.md §4.1）。
"""

from __future__ import annotations

from ..model.refs import parse_ref
from ..store.sources import declared, newer
from ..store.store import Store
from .types import Lookup, Source


def lookup(store: Store) -> Lookup:
    """来源引用的解析；结果缓存在返回的函数中。不是外部来源的引用、来源未开放时为 ``None``。"""
    sources = store.sources
    owners: dict[str, list[str]] | None = None

    def get(text: str) -> Source | None:
        nonlocal owners
        ref = parse_ref(text)
        if ref is None or not ref.external or not sources.available(ref.head):
            return None
        if owners is None:
            owners = declared(store)
        cited = None
        if ref.lines is not None:
            lines = sources.lines(ref.head, ref.file)
            start, end = ref.lines
            cited = lines[start - 1 : end] if lines is not None and end <= len(lines) else None
        return Source(ref.head, tuple(owners.get(ref.head, ())), newer(ref.head, owners), cited)

    return get


__all__ = ["lookup"]
