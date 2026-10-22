"""外部来源：只读来源目录中的固定副本，与库中 Paper、Code 声明的来源（docs/experiments/f3/2026-10-22-f3-design.md §4）。

来源 ID 是外部的固定版本：论文为带版本的 arXiv 编号（``2205.13504v2``），代码为 ``<仓库>@<8 位 commit>``。
来源目录（``PAPERWEAVE_SOURCES``）由运行环境维护，只放已开放的来源，系统只读：

- 论文：``<目录>/<来源 ID>/paper.md``；
- 代码：``<目录>/<仓库>@<commit>/`` 下为仓库的原有目录结构。

同一来源 ID 的内容固定不变，锚点的行号按它解析。版本先后从 ID 读出：arXiv 编号相同时版本号大者更新，不另建版本表；
代码的 commit 不排序。某个来源被取代，指库中有 Paper 声明了同一编号的更新版本。
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from ..model.schema import CODE_SOURCE, PAPER_SOURCE

if TYPE_CHECKING:
    from .store import Store


def version(source_id: str) -> tuple[str, int] | None:
    """论文来源 ID → (arXiv 编号, 版本号)；不是论文来源时为 ``None``。"""
    if not PAPER_SOURCE.fullmatch(source_id):
        return None
    number, _, v = source_id.rpartition("v")
    return number, int(v)


def newer(source_id: str, declared: Iterable[str]) -> str | None:
    """``declared`` 中同一 arXiv 编号的最新版本，比 ``source_id`` 新时返回它，否则为 ``None``。"""
    own = version(source_id)
    if own is None:
        return None
    best = max((v for v in map(version, declared) if v is not None and v[0] == own[0]), default=None, key=lambda v: v[1])
    return f"{best[0]}v{best[1]}" if best is not None and best[1] > own[1] else None


def declared(store: Store) -> dict[str, list[str]]:
    """库中声明过的来源 → 声明它的 Paper 或 Code（按 id 排序）。"""
    rows = store.query(
        """MATCH (n:Entity) WHERE n.source IS NOT NULL UNWIND n.source AS source
           RETURN source, collect(n.id) AS owners"""
    )
    return {r["source"]: sorted(r["owners"]) for r in rows}


class SourceDir:
    """只读来源目录。文件按需读取并缓存（同一来源 ID 的内容固定）。"""

    def __init__(self, root: Path):
        self.root = root
        self._lines: dict[Path, list[str] | None] = {}

    def available(self, source_id: str) -> bool:
        """来源已开放（目录中有它）。"""
        if PAPER_SOURCE.fullmatch(source_id):
            return (self.root / source_id / "paper.md").is_file()
        return bool(CODE_SOURCE.fullmatch(source_id)) and (self.root / source_id).is_dir()

    def file(self, source_id: str, path: str | None = None) -> Path | None:
        """论文的 Markdown，或代码仓库中的文件；不在、路径越出仓库时为 ``None``。"""
        if PAPER_SOURCE.fullmatch(source_id):
            file = self.root / source_id / "paper.md"
        elif CODE_SOURCE.fullmatch(source_id) and path:
            parts = PurePosixPath(path.removeprefix("./")).parts
            if not parts or parts[0] == "/" or ".." in parts:
                return None
            file = self.root / source_id / Path(*parts)
        else:
            return None
        return file if file.is_file() else None

    def lines(self, source_id: str, path: str | None = None) -> list[str] | None:
        """文件的各行；不在或不是 UTF-8 文本时为 ``None``。"""
        file = self.file(source_id, path)
        if file is None:
            return None
        if file not in self._lines:
            try:
                self._lines[file] = file.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                self._lines[file] = None
        return self._lines[file]

    def sha256(self, source_id: str, path: str | None = None) -> str | None:
        file = self.file(source_id, path)
        return hashlib.sha256(file.read_bytes()).hexdigest() if file is not None else None


__all__ = ["SourceDir", "declared", "newer", "version"]
