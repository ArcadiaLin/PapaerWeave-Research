"""FetchArtifact：把共同产物的文档取到写者的工作目录（docs/designs/v2/operators.md §3.6、§5.6）。

    fetch(store, ids, *, workdir, me, at=None)
      -> {items: [{artifact, type, path, version, base, hint, ...}], missing: [{artifact, msg}], next}

- 文档写到工作目录中类型给出的位置（:meth:`e09.artifact.types.ArtifactType.checkout_path`）：通常是
  ``artifacts/<标题>.md``；Skill 是 ``.agents/skills/<name>/SKILL.md``。同名文件已存在且内容不同时覆盖，并在返回
  中说明（``overwritten``）。一次取的几份落到同一路径时，后面的加序号。
- 头部加上 ``id`` 与 ``base``（这个版本所在的提交），检入时据此核对；写者不应修改这两行。
- ``at``（提交 id 或分支名）给出时取该提交时的版本，只供阅读：检入时 ``base`` 不是最新版本会被拒绝。
- ``hint`` 是编辑提示，由提交链与各版本的比对算出：版本号、最近的编辑者与修改说明、各编辑者，以及“自你上次
  编辑以来别人改了哪些行”（``me`` 是调用者）。行号是取出的文件中的行号。
- ``notes`` 是类型给出的、读取时现算的附注（如 Leaderboard 每位编辑者写的行数、所引论文已有新版本的行、同一格
  的多个值），不写进文档。
- 旧版 Agent 算子的产物写入后不可修改，不能取出；用 ``ReadEvidence`` 阅读。
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import PurePosixPath
from typing import Any

from ..draft import Workdir
from ..model.schema import ARTIFACT
from ..query.versions import pin
from ..store.store import ContractError, Store
from .checkin import relocate
from .document import Parsed, add_checkout, line_map
from .sources import lookup
from .stale import pinned as pins
from .types import TYPES, ArtifactType
from .versions import Version, blame, history, load, since

LIST_MAX = 30  # 编辑提示中逐行列出的上限


def fetch(
    store: Store, ids: list[str], *, workdir: Workdir | None, me: str | None, at: str | None = None
) -> dict[str, Any]:
    """取出 ``ids`` 中的产物。

    Raises:
        ContractError: 没有工作目录，或 ``at`` 不是提交 id 或分支名。
    """
    if workdir is None:
        raise ContractError(
            [
                {
                    "rule": "format",
                    "at": "artifact",
                    "msg": "FetchArtifact writes into your working directory, which is not available here",
                }
            ]
        )
    pinned = pin(store, at, at="at") if at is not None else None
    kinds = store.kinds(ids)
    ops = {
        r["id"]: r["op"]
        for r in store.query("UNWIND $ids AS id MATCH (a:Artifact {id: id}) RETURN a.id AS id, a.op AS op", ids=ids)
    }
    taken: set[str] = set()
    items: list[dict[str, Any]] = []
    missing: list[dict[str, str]] = []
    for art_id in ids:
        if kinds.get(art_id) != ARTIFACT:
            missing.append({"artifact": art_id, "msg": "not an artifact in the store"})
            continue
        kind = TYPES.get(ops.get(art_id) or "")
        if kind is None:
            msg = f"a {ops.get(art_id)} artifact from the retired operators cannot be edited; read it with ReadEvidence"
            missing.append({"artifact": art_id, "msg": msg})
            continue
        versions = history(store, art_id)
        shown = [v for v in versions if pinned is None or v.seq <= pinned.record.seq]
        if not shown:
            missing.append(
                {"artifact": art_id, "msg": f"did not exist at {pinned.commit}" if pinned else "has no document"}
            )
            continue
        docs = [load(store, v) for v in shown]
        if any(d is None for d in docs):
            missing.append(
                {"artifact": art_id, "msg": "a version's document is missing or changed; the store needs repair"}
            )
            continue
        items.append(_one(store, kind, art_id, shown, docs, versions[-1], workdir, me, taken))  # type: ignore[arg-type]
    steps = (
        "Edit the files with your own tools, then call CheckIn with artifact_doc (the paths) and update_abstract "
        "(what you changed and why). Do not edit the id and base lines."
    )
    return {"items": items, "missing": missing, "next": steps}


def _one(
    store: Store,
    kind: ArtifactType,
    art_id: str,
    versions: list[Version],
    docs: list[Parsed],
    latest: Version,
    workdir: Workdir,
    me: str | None,
    taken: set[str],
) -> dict[str, Any]:
    target, doc = versions[-1], docs[-1]
    text = add_checkout(doc.text, art_id, target.commit)
    rel = _free(kind.checkout_path(doc.header), taken)
    root = workdir.root.resolve()
    file = (root / rel).resolve()
    if not file.is_relative_to(root):
        raise ContractError([{"rule": "format", "at": "artifact", "msg": f"{rel} is outside the working directory"}])
    overwritten = file.exists() and file.read_text(encoding="utf-8", errors="replace") != text
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text, encoding="utf-8")
    out: dict[str, Any] = {
        "artifact": art_id,
        "type": kind.name,
        "path": rel,
        "version": target.number,
        "base": target.commit,
    }
    if overwritten:
        out["overwritten"] = f"{rel} existed with other content and was replaced"
    if target.number != latest.number:
        out["read_only"] = (
            f"this is v{target.number}; the latest is v{latest.number} ({latest.commit}). "
            "CheckIn accepts only edits based on the latest version"
        )
    lines = line_map(text, doc.text)
    out["hint"] = _hint(kind, versions, docs, me, lines)
    history_docs = [(v.author, v.number, d) for v, d in zip(versions, docs, strict=True)]
    authors = {b.unit.line: (b.author, b.version) for b in blame(kind, history_docs)}
    pinned = pins(store, art_id) if target.number == latest.number else {}  # 旧版本按当时的库解析，不另求
    notes = kind.notes(doc, authors, lookup(store, pinned))
    if notes:
        out["notes"] = relocate(notes, lambda n: lines[n - 1] if 0 < n <= len(lines) else n)
    return out


def _free(rel: str, taken: set[str]) -> str:
    """一次取的几份落到同一路径时，后面的在文件名（Skill 为目录名）后加序号。"""
    path = PurePosixPath(rel)
    n = 0
    candidate = rel
    while candidate in taken:
        n += 1
        if path.name == "SKILL.md":
            candidate = str(path.parent.with_name(f"{path.parent.name}-{n}") / path.name)
        else:
            candidate = str(path.with_name(f"{path.stem} ({n}){path.suffix}"))
    taken.add(candidate)
    return candidate


def _hint(
    kind: ArtifactType, versions: list[Version], docs: list[Parsed], me: str | None, lines: list[int]
) -> dict[str, Any]:
    """编辑提示：``lines`` 把文档的行号换算成取出的文件中的行号。"""
    last = versions[-1]
    edit: dict[str, Any] = {"editor": last.author, "commit": last.commit, "message": last.message}
    if last.reason:
        edit["reason"] = last.reason
    by: dict[str, list[int]] = defaultdict(list)
    for v in versions:
        by[v.author].append(v.number)
    out: dict[str, Any] = {
        "version": last.number,
        "last_edit": edit,
        "editors": [{"editor": a, "versions": ns} for a, ns in by.items()],
    }
    mine = [v.number for v in versions if me is not None and v.author == me]
    if not mine:
        out["since_your_last_edit"] = "you have not edited it before"
        return out
    if mine[-1] == last.number:
        out["since_your_last_edit"] = "you made the latest version"
        return out
    history_docs = [(v.author, v.number, d) for v, d in zip(versions, docs, strict=True)]
    now = blame(kind, history_docs)
    then = blame(kind, history_docs[: mine[-1]])
    changed = since(now, then, me or "", mine[-1])
    for entry in changed:
        if entry["at"] is not None:
            entry["at"] = lines[entry["at"] - 1] if 0 < entry["at"] <= len(lines) else entry["at"]
    shown = changed[:LIST_MAX]
    detail: dict[str, Any] = {"your_version": mine[-1], "changed_by_others": shown}
    if len(changed) > LIST_MAX:
        detail["more"] = f"{len(changed) - LIST_MAX} more changes not listed"
    out["since_your_last_edit"] = detail
    return out


__all__ = ["fetch"]
