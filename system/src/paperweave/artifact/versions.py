"""共同产物的版本链、逐行归属与比对（docs/designs/v2/operators.md §4.1、§5.5、§5.6）。

**版本不加字段。** 每个版本是挂在产物上的一份 Material（``MATERIAL_OF``），按创建它的提交的序号排序；上一版本的
Material 记上 ``superseded_by``。版本号、各版本的编辑者（提交的 ``author``）与修改说明（提交的 ``message``）都从
提交链推出（:func:`history`）。

**归属**（:func:`blame`）：按类型的比对单位（:meth:`paperweave.artifact.types.ArtifactType.units`）逐版本推进。按行键
对齐的表格行，行键相同且单元格不变时保留原编辑者，否则记为这一版的编辑者；其余文字按行比对（同 ``git blame``）。

**比对**（:func:`compare`）：交上来的文档与基础版本逐单位比较，得出新增、修改、删除的行，以及改动或删除的、由他人
写入的行（``others``）。种子写入的行也算他人的行。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from ..store.store import Store
from .document import Parsed, parse, strip_checkout
from .stale import document_text
from .types import ArtifactType, Unit


@dataclass(frozen=True, slots=True)
class Version:
    """一个版本：``number`` 从 1 起；``material`` 是 ``{id, path, content_hash}``；``commit`` 是写入它的提交。"""

    number: int
    material: dict[str, Any]
    commit: str
    seq: int
    author: str
    message: str
    at: str
    reason: str | None = None


def history(store: Store, art_id: str) -> list[Version]:
    """产物的全部版本，从最早到最新；不是产物或没有登记文档时为空。"""
    rows = store.query(
        """MATCH (m:Material)-[:MATERIAL_OF]->(:Artifact {id: $id})
           MATCH (c:Commit)-[:TOUCHED {op: 'create'}]->(m)
           RETURN m.id AS id, m.path AS path, m.content_hash AS content_hash, c.id AS commit, c.seq AS seq
           ORDER BY seq""",
        id=art_id,
    )
    out: list[Version] = []
    for n, row in enumerate(rows, start=1):
        record = store.graph.get_commit(row["commit"])
        reason = record.meta.get("reason") if isinstance(record.meta, dict) else None
        material = {k: row[k] for k in ("id", "path", "content_hash")}
        out.append(Version(n, material, record.id, record.seq, record.author, record.message, record.at, reason))
    return out


def load(store: Store, version: Version) -> Parsed | None:
    """版本的文档；文件不在、哈希不符或无法解析时为 ``None``。"""
    text = document_text(store, version.material)
    if text is None:
        return None
    try:
        return parse(strip_checkout(text))
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class Blamed:
    """一个单位及其最近的编辑者与版本。"""

    unit: Unit
    author: str
    version: int


def blame(kind: ArtifactType, versions: Iterable[tuple[str, int, Parsed]]) -> list[Blamed]:
    """按版本推进的归属：``versions`` 是 ``(编辑者, 版本号, 文档)``，从最早到最新。返回最后一个版本的各单位。"""
    current: list[Blamed] = []
    for author, number, doc in versions:
        current = advance(current, kind.units(doc), author, number)
    return current


def advance(old: list[Blamed], new: list[Unit], author: str, number: int) -> list[Blamed]:
    """从上一版本的归属推到新版本：不变的单位保留原编辑者，其余记为 ``author``。"""
    keyed = {b.unit.key: b for b in old if b.unit.key is not None}
    plain_old = [b for b in old if b.unit.key is None]
    plain_new = [u for u in new if u.key is None]
    kept: dict[int, Blamed] = {}
    matcher = SequenceMatcher(None, [b.unit.text for b in plain_old], [u.text for u in plain_new], autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for i, j in zip(range(i1, i2), range(j1, j2), strict=True):
                kept[id(plain_new[j])] = plain_old[i]
    out: list[Blamed] = []
    for unit in new:
        before = keyed.get(unit.key) if unit.key is not None else kept.get(id(unit))
        if before is not None and before.unit.text == unit.text:
            out.append(Blamed(unit, before.author, before.version))
        else:
            out.append(Blamed(unit, author, number))
    return out


@dataclass
class Changes:
    """交上来的文档相对于基础版本的改动。``added``、``modified``、``deleted`` 是按行键对齐的行（``{at, row}``，
    ``at`` 是行号：删除的行是基础版本中的行号）；``lines`` 是其余文字中改动的行数；``others`` 是改动或删除的、由
    他人写入的单位（``{at, what, editor, version, change}``）。"""

    added: list[dict[str, Any]] = field(default_factory=list)
    modified: list[dict[str, Any]] = field(default_factory=list)
    deleted: list[dict[str, Any]] = field(default_factory=list)
    lines: int = 0
    others: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "rows_added": len(self.added),
            "rows_modified": len(self.modified),
            "rows_deleted": len(self.deleted),
            "lines_changed": self.lines,
        }
        if self.modified:
            out["modified"] = self.modified
        if self.deleted:
            out["deleted"] = self.deleted
        return out


def compare(base: list[Blamed], new: list[Unit], me: str) -> Changes:
    """交上来的文档（比对单位 ``new``）相对于基础版本（归属 ``base``）的改动；``me`` 是交上来的编辑者。"""
    changes = Changes()
    old_keyed = {b.unit.key: b for b in base if b.unit.key is not None}
    new_keyed = {u.key: u for u in new if u.key is not None}

    def other(b: Blamed, at: int, change: str) -> None:
        if b.author != me:
            what = b.unit.label
            changes.others.append({"at": at, "what": what, "editor": b.author, "version": b.version, "change": change})

    for key, unit in new_keyed.items():
        before = old_keyed.get(key)
        if before is None:
            changes.added.append({"at": unit.line, "row": unit.label})
        elif before.unit.text != unit.text:
            changes.modified.append({"at": unit.line, "row": unit.label})
            other(before, unit.line, "modified")
    for key, before in old_keyed.items():
        if key not in new_keyed:
            changes.deleted.append({"at": before.unit.line, "row": before.unit.label})
            other(before, before.unit.line, "deleted")

    plain_old = [b for b in base if b.unit.key is None]
    plain_new = [u for u in new if u.key is None]
    matcher = SequenceMatcher(None, [b.unit.text for b in plain_old], [u.text for u in plain_new], autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        changes.lines += max(i2 - i1, j2 - j1)
        for i in range(i1, i2):  # 被替换或删除的旧行
            at = plain_new[j1].line if tag == "replace" and j1 < len(plain_new) else plain_old[i].unit.line
            other(plain_old[i], at, "modified" if tag == "replace" else "deleted")
    return changes


def since(blamed: list[Blamed], earlier: list[Blamed], me: str, mine: int) -> list[dict[str, Any]]:
    """“自你上次编辑以来别人改了哪些行”：``blamed`` 是当前版本的归属，``earlier`` 是 ``me`` 最后编辑的版本
    （版本号 ``mine``）的归属。列出之后由他人新增或改动的单位，以及之后被删掉的按行键对齐的行。"""
    out = [
        {"at": b.unit.line, "what": b.unit.label, "editor": b.author, "version": b.version}
        for b in blamed
        if b.version > mine and b.author != me and b.unit.text.strip()
    ]
    now = {b.unit.key for b in blamed if b.unit.key is not None}
    out += [
        {"at": None, "what": b.unit.label, "editor": None, "version": None, "change": "deleted"}
        for b in earlier
        if b.unit.key is not None and b.unit.key not in now
    ]
    return out


__all__ = ["Blamed", "Changes", "Version", "advance", "blame", "compare", "history", "load", "since"]
