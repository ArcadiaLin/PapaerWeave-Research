"""在内存中按顺序重放入库文档，得到图状态（与 Commit 相同的写入路径：dry_run、分配 id、用真实 id 准备、应用）。

A0 的检查点 0 由这个状态渲染，A3 的检查点 0 由同样的文档按同样的顺序提交到图库，两者因此内容相同。重放不查重：
入库文档中的查重判断（``confirm``）已在提交到图库时做过。
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path

from e09.commit import Context, MemoryReader, allocate_ids, prepare
from graph_vc import GraphState

AT = "2026-10-11T00:00:00+00:00"  # 形成时间：重放结果不随运行时刻变化


class ReplayError(Exception):
    """某份文档在重放时有错误。"""


class _Counters:
    """与 graph-vc 的 ``allocate_ids`` 同格式的内存 id 分配。"""

    def __init__(self) -> None:
        self.last: dict[str, int] = defaultdict(int)

    def allocate_ids(self, prefix: str, count: int = 1) -> list[str]:
        start = self.last[prefix]
        self.last[prefix] += count
        return [f"{prefix}_{n:04d}" for n in range(start + 1, start + count + 1)]


def replay(docs: Iterable[tuple[Path, str]], material_root: Path) -> GraphState:
    """从空状态依次应用 ``docs``（文档路径与来源标签，与提交到图库时相同）；任一文档有错误时报错，不跳过。"""
    state, counters = GraphState(), _Counters()
    for path, source in docs:
        text = path.read_text(encoding="utf-8")
        context = Context(MemoryReader(state), source, AT, material_root, None)
        dry = prepare(text, context)
        if not dry.ok or dry.document is None:
            raise ReplayError(f"{path.name}: {[(p.rule, p.at, p.msg) for p in dry.errors]}")
        context = Context(MemoryReader(state), source, AT, material_root, None)
        prepared = prepare(text, context, allocate_ids(dry.document, counters))
        if not prepared.ok or prepared.changeset is None:
            raise ReplayError(f"{path.name}: {[(p.rule, p.at, p.msg) for p in prepared.errors]}")
        state = state.apply(prepared.changeset)
    return state


__all__ = ["AT", "ReplayError", "replay"]
