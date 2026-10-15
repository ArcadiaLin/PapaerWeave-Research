"""结果的容量控制（docs/designs/v2/versioning_interfaces.md §2.2）：分页时放得下的最多项数；单项自己就放不下时
截短它的长文本与长列表，被截短的值用分块读取取回。

大小按 YAML 的字节数计（与返回给 Agent 的文本相同），上限是 :data:`paperweave.query.excerpts.LIMIT`。

**截短。** 先把过长的字符串截到同一个长度（在 UTF-8 字符边界截断，末尾写 ``…``），取放得下的最大长度；字符串截到
最短仍放不下时，再把过长的列表截到同一个项数。被截短的位置记在该项的 ``_cut`` 中：``{路径: {bytes: 原长}}`` 或
``{路径: {items: 原项数}}``。路径用 ``.`` 连接键与列表下标，如 ``fields.text.1``。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..store.store import ContractError
from ..yamlfmt import dump
from .excerpts import LIMIT, cut

MIN_TEXT = 64  # 截短后字符串至少保留的字节数
MIN_ITEMS = 1  # 截短后列表至少保留的项数


def size(view: Any) -> int:
    """``view`` 的 YAML 字节数。"""
    return len(dump(view).encode("utf-8"))


def fit(view: Callable[[int], Any], total: int) -> int:
    """放得下的最多项数（视图大小随项数单调不减，二分查找）；一项也放不下时仍返回一项，由调用者截短。"""
    if total == 0 or size(view(total)) <= LIMIT:
        return total
    low, high = 1, total - 1  # view(low) 不一定放得下；high 之后的都放不下
    while low < high:
        mid = (low + high + 1) // 2
        if size(view(mid)) <= LIMIT:
            low = mid
        else:
            high = mid - 1
    return low


def finish(view: dict[str, Any]) -> dict[str, Any]:
    """在 ``meta.size`` 中写入上限与实际大小。"""
    view["meta"]["size"] = {"limit": LIMIT, "used": LIMIT}  # 占位：位数不少于实际
    for _ in range(2):  # 写入 used 本身后的大小；第二次计入位数的变化
        view["meta"]["size"]["used"] = size(view)
    return view


def paged(view: Callable[[int], dict[str, Any]], total: int, key: str) -> dict[str, Any]:
    """分页的结果：``view(n)`` 是前 ``n`` 项的视图，各项在 ``view(n)[key]`` 中（列表或以 id 为键的映射）。取放得下的
    最多项；只剩一项仍放不下时截短它（:func:`shrink`）。最后写入 ``meta.size``。"""
    out = view(fit(view, total))
    items = out[key]
    if len(items) == 1 and size(out) > LIMIT:
        k = next(iter(items)) if isinstance(items, dict) else 0
        original = items[k]

        def fits(item: dict[str, Any]) -> bool:
            items[k] = item
            return size(out) <= LIMIT

        items[k] = shrink(original, fits)
    return finish(out)


def field_view(node_id: str, item: dict[str, Any], path: Any, offset: Any, meta: dict[str, Any]) -> dict[str, Any]:
    """分块读取一项中被截短的值：``{id, field, offset, bytes | items, value, meta}``，``meta.next_offset`` 是下一段的
    起点（读完为 ``None``）。

    Raises:
        ContractError: 路径不在这一项中，或 ``offset`` 超出范围。
    """
    try:
        value = value_at(item, path) if isinstance(path, str) else None
    except KeyError:
        value = None
    if value is None:
        raise ContractError([{"at": "field", "msg": "a path in the item, such as a key of its _cut"}])
    total = {"bytes": len(value.encode("utf-8"))} if isinstance(value, str) else {}
    total = {"items": len(value)} if isinstance(value, list) else total
    offset = 0 if offset is None else offset
    if not isinstance(offset, int) or isinstance(offset, bool) or not 0 <= offset <= next(iter(total.values()), 0):
        raise ContractError([{"at": "offset", "msg": f"an integer from 0 to the value's size {total}"}])

    def view(piece: Any, nxt: int | None) -> dict[str, Any]:
        out_meta = {**meta, "next_offset": nxt, "size": {"limit": LIMIT, "used": LIMIT}}
        return {"id": node_id, "field": path, "offset": offset, **total, "value": piece, "meta": out_meta}

    piece, nxt = chunk(value, offset, lambda piece, nxt: size(view(piece, nxt)) <= LIMIT)
    return finish(view(piece, nxt))


def shrink(item: dict[str, Any], fits: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
    """``item`` 放不下时截短后的副本（带 ``_cut``）；截到最短仍放不下时返回最短的那个。"""
    if fits(item):
        return item
    longest = max((_bytes(s) for _, s in _leaves(item, str)), default=0)
    text = _largest(lambda n: fits(_cut(item, n, None)), MIN_TEXT, longest)
    if text is not None:
        return _cut(item, text, None)
    most = max((len(v) for _, v in _leaves(item, list)), default=0)
    items = _largest(lambda n: fits(_cut(item, MIN_TEXT, n)), MIN_ITEMS, most)
    return _cut(item, MIN_TEXT, items if items is not None else MIN_ITEMS)


def value_at(item: Any, path: str) -> Any:
    """路径所指的值。

    Raises:
        KeyError: 路径不存在。
    """
    node = item
    for part in path.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            raise KeyError(path)
    return node


def chunk(value: Any, offset: int, fits: Callable[[Any, int | None], bool]) -> tuple[Any, int | None]:
    """分块读取：字符串从第 ``offset`` 字节起、列表从第 ``offset`` 项起，放得下的最长一段及下一段的起点
    （读完为 ``None``）。``fits(片段, 下一段起点)`` 判断带上这一段的结果是否放得下；至少返回一个字符或一项。
    其他值整个返回。"""
    if isinstance(value, str):
        data = value.encode("utf-8")
        start = _boundary(data, offset)

        def piece(n: int) -> tuple[str, int | None]:
            end = _boundary(data, start + n) if start + n < len(data) else len(data)
            return data[start:end].decode("utf-8"), end if end < len(data) else None

        n = _largest(lambda n: fits(*piece(n)), 1, len(data) - start)
        text, nxt = piece(n if n is not None else 1)
        if not text and start < len(data):  # 一个多字节字符
            end = _boundary(data, start + 1, forward=True)
            text, nxt = data[start:end].decode("utf-8"), end if end < len(data) else None
        return text, nxt
    if isinstance(value, list):

        def part(n: int) -> tuple[list[Any], int | None]:
            end = min(offset + n, len(value))
            return value[offset:end], end if end < len(value) else None

        n = _largest(lambda n: fits(*part(n)), 1, len(value) - offset)
        return part(n if n is not None else 1)
    return value, None


# ── 内部 ──────────────────────────────────────────────────────────────


def _largest(ok: Callable[[int], bool], low: int, high: int) -> int | None:
    """``[low, high]`` 中使 ``ok`` 成立的最大值（``ok`` 单调：小的成立，大的不成立）；都不成立时为 ``None``。"""
    if high < low or not ok(low):
        return None
    while low < high:
        mid = (low + high + 1) // 2
        if ok(mid):
            low = mid
        else:
            high = mid - 1
    return low


def _cut(item: dict[str, Any], text: int, items: int | None) -> dict[str, Any]:
    """字符串截到 ``text`` 字节、列表截到 ``items`` 项（``None`` 不截）后的副本，带 ``_cut``。"""
    marks: dict[str, dict[str, int]] = {}

    def walk(node: Any, path: str) -> Any:
        if isinstance(node, str) and _bytes(node) > text:
            marks[path] = {"bytes": _bytes(node)}
            return cut(node, text)
        if isinstance(node, list):
            kept = node
            if items is not None and len(node) > items:
                marks[path] = {"items": len(node)}
                kept = node[:items]
            return [walk(v, _join(path, str(i))) for i, v in enumerate(kept)]
        if isinstance(node, dict):
            return {k: walk(v, _join(path, str(k))) for k, v in node.items() if k != "_cut"}
        return node

    out = walk(item, "")
    if marks:
        out["_cut"] = marks
    return out


def _leaves(node: Any, kind: type, path: str = "") -> list[tuple[str, Any]]:
    """``node`` 中类型为 ``kind`` 的值（字符串或列表）及其路径。"""
    found = [(path, node)] if isinstance(node, kind) else []
    if isinstance(node, dict):
        children = [(str(k), v) for k, v in node.items()]
    elif isinstance(node, list):
        children = [(str(i), v) for i, v in enumerate(node)]
    else:
        children = []
    for key, value in children:
        found += _leaves(value, kind, _join(path, key))
    return found


def _join(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def _bytes(text: str) -> int:
    return len(text.encode("utf-8"))


def _boundary(data: bytes, offset: int, *, forward: bool = False) -> int:
    """``offset`` 处的 UTF-8 字符边界：不在边界上时向前（``forward`` 时向后）移到最近的边界。"""
    offset = max(0, min(offset, len(data)))
    step = 1 if forward else -1
    while 0 < offset < len(data) and data[offset] & 0xC0 == 0x80:
        offset += step
    return offset


__all__ = ["chunk", "field_view", "finish", "fit", "paged", "shrink", "size", "value_at"]
