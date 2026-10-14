"""CheckIn：按类型契约检入共同产物（docs/designs/v2/operators.md §4.1、§5.4、§5.5）。

    check_in(store, drafts, update_abstract, *, confirm, reason, at, session, formed_by, ...)
      -> {status: checked, items, next}            省略 confirm：只校验，不写入
       | {status: committed, commit, items, warnings}
       | {status: unchanged, items}                 每份都与最新版本相同，或是重试
    Raises ContractError：rejected（有错误）或 conflict（base 不是最新版本、id 被改）

**每份文档**（写者工作目录中的文件，:mod:`e09.draft`）：

1. 解析头部，按 ``type`` 取类型契约（:mod:`e09.artifact.types`）；论文表单经 ``Commit``，不在这里；
2. 头部带 ``id`` 与 ``base`` 时是更新：``base`` 须是该产物最新版本的提交，否则 ``conflict``，让写者重新取出、
   合并后再交；不带时是新建；
3. 类型自己的校验；身份键已有另一份产物时拒绝（``identity``），退回已有的那份；
4. 文档中的引用都要在库中：对象存在；记录所属的产物的当前版本有这一行；来源引用的材料存在、文件与登记的哈希
   一致、行号不越界（``reference``）。由引用得出 ``USED`` 边；
5. 去掉 ``id``、``base`` 两行后与最新版本相同时为 ``noop``；没有身份键的类型新建时，内容与同一编辑者写的同类
   产物的某个版本相同，视为重试（``existing``）；
6. 与基础版本逐单位比对，得出改动与 ``others``（:mod:`e09.artifact.versions`）；
7. 类型的轻度规则只作用于新增与修改的行：拒绝的是错误，其余是 ``warnings``（如数字不在所引的行中）。

``checked`` 的每份文档另给 ``stats``（类型的统计）与 ``warnings``；``committed`` 的每份另给读取时现算的 ``notes``
（如 Leaderboard 每位编辑者写的行数、所引论文已有新版本的行、同一格的多个值）。

任一份有错误时整次不写入。``others`` 不为空时须给出 ``reason``。

**写入**（一个提交）：每份文档写到材料根目录的 ``artifacts/<标题>.v<版本>.md``；新建的产物分配 id、写节点；每份
产物登记新版本的 Material 与 ``MATERIAL_OF``，上一版本的 Material 记上 ``superseded_by``，按新版本重写 ``USED``
边，更新 ``title``、``abs``、``op_version``、``key``。提交的 ``source`` 为 ``operator:CheckIn``，``author`` 为
编辑者，``message`` 为 ``update_abstract``，``meta`` 记各产物的 id、版本与动作、会话与 ``reason``。提交后补算
向量，失败只在 ``warnings`` 中提示。

**每个版本一份 Material。** id 由（产物、版本、内容哈希）算出，``content_hash`` 仍是内容的哈希：改回早先的内容时，
早先那份 Material 已被取代，不能拿来当新版本；两份产物内容相同时，一份 Material 也不能同时属于两份产物。
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

import httpx

from graph_vc import Changeset, ConflictError, EdgeChange, FileRef, NodeChange

from ..draft import Draft
from ..model.refs import parse_ref
from ..model.schema import ARTIFACT, LOCATOR
from ..query.materials import load_lines, materials
from ..store.database import setup_database
from ..store.store import ContractError, Store
from ..yamlfmt import dump
from .document import (
    DIRECTORY,
    Document,
    HeaderError,
    Parsed,
    data_of,
    header_field,
    line_map,
    parse,
    record_keys,
    strip_checkout,
    version_file_name,
)
from .sources import lookup
from .stale import document_text, documents
from .types import COMMIT_TYPES, TYPES, ArtifactType, Mention
from .versions import Changes, Version, blame, compare, history, load

SOURCE = "operator:CheckIn"
PREFIX = "art"


@dataclass
class Item:
    """一份交上来的文档在检入中的状态。``doc`` 是去掉 ``id``、``base`` 两行后要保存的文档；``lines`` 把它的行号
    换算成写者文件中的行号。"""

    draft: Draft
    kind: ArtifactType | None = None
    doc: Parsed | None = None
    lines: list[int] = field(default_factory=list)
    art_id: str | None = None
    base: str | None = None
    versions: list[Version] = field(default_factory=list)
    key: str | None = None
    used: dict[str, dict[str, Any]] = field(default_factory=dict)
    action: str = "create"
    changes: Changes | None = None
    history: list[tuple[str, int, Parsed]] = field(default_factory=list)  # (编辑者, 版本号, 文档)，从最早到最新
    warnings: list[dict[str, str]] = field(default_factory=list)

    def at(self, line: int) -> str:
        """写者文件中的位置 ``<文件>:<行号>``；``line`` 是要保存的文档中的行号。"""
        mapped = self.lines[line - 1] if 0 < line <= len(self.lines) else line
        return f"{self.draft.path}:{mapped}"


class Problems:
    """校验中的错误：``{rule, at, msg}``，与 Commit 阻塞项的形状相同。"""

    def __init__(self) -> None:
        self.items: list[dict[str, str]] = []

    def add(self, rule: str, at: str, msg: str) -> None:
        self.items.append({"rule": rule, "at": at, "msg": msg})

    def __bool__(self) -> bool:
        return bool(self.items)

    def raise_if_any(self) -> None:
        if self.items:
            conflict = any(e["rule"] == "conflict" for e in self.items)
            raise ContractError(self.items, status="conflict" if conflict else "rejected")


def check_in(
    store: Store,
    drafts: list[Draft],
    update_abstract: str,
    *,
    confirm: bool,
    reason: str | None,
    at: str,
    session: str,
    formed_by: str,
    agent: str | None = None,
    sync: Callable[[], int] | None = None,
) -> dict[str, Any]:
    """校验交上来的文档；``confirm`` 时写入。

    Raises:
        ContractError: 有错误（``rejected``），或 ``base`` 不是最新版本、``id`` 被改（``conflict``）；什么也没有写入。
    """
    problems = Problems()
    if not update_abstract.strip():
        problems.add("format", "update_abstract", "what you changed and why; shown to later editors")
    items = [_prepare(store, d, formed_by, problems) for d in drafts]
    _across(items, problems)
    problems.raise_if_any()

    others = [(item, o) for item in items if item.changes for o in item.changes.others]
    if not confirm:
        return _checked(items, others)
    if others and not (reason and reason.strip()):
        msg = (
            f"{len(others)} changed or deleted lines were written by others; "
            "give reason: why you changed them (cite new evidence if you used any)"
        )
        raise ContractError([{"rule": "others", "at": items[0].draft.path, "msg": msg}])
    if not any(item.action in ("create", "update") for item in items):
        return {"status": "unchanged", "items": [_entry(item) for item in items]}
    return _write(
        store, items, update_abstract, reason, at=at, session=session, formed_by=formed_by, agent=agent, sync=sync
    )


# ── 校验 ──────────────────────────────────────────────────────────────


def _prepare(store: Store, draft: Draft, me: str, problems: Problems) -> Item:
    item = Item(draft)
    try:
        given = parse(draft.text)
    except HeaderError as exc:
        problems.add("format", f"{draft.path}:{exc.line}", str(exc))
        return item
    name = header_field(given.header, "type")
    accepted = sorted(TYPES)
    if name is None:
        problems.add("format", f"{draft.path}:1", f"the header names the type: type: one of {accepted}")
        return item
    if name in COMMIT_TYPES:
        problems.add("format", f"{draft.path}:1", f"a {name} is checked in with Commit (as a graph-doc), not CheckIn")
        return item
    kind = TYPES.get(str(name))
    if kind is None:
        problems.add("format", f"{draft.path}:1", f"unknown type {name!r}; one of {accepted}")
        return item
    item.kind = kind
    if kind.nested and "type" in given.header:
        problems.add("format", f"{draft.path}:1", f"a {kind.name} keeps type, id and base under metadata")
        return item

    stored = strip_checkout(draft.text)
    item.doc = parse(stored)
    item.lines = line_map(draft.text, stored)
    item.art_id, item.base = (header_field(given.header, k) for k in ("id", "base"))
    kind.check(given, lambda rule, line, msg: problems.add(rule, f"{draft.path}:{line}", msg))

    if (item.art_id is None) != (item.base is None):
        msg = "id and base come together from FetchArtifact; do not edit or remove them"
        problems.add("conflict", f"{draft.path}:1", msg)
        return item
    if item.art_id is not None:
        _base(store, item, problems)
    item.key = kind.key(item.doc.header)
    if item.key is not None:
        found = store.query("MATCH (a:Artifact {key: $key}) RETURN a.id AS id, a.title AS title", key=item.key)
        if found and found[0]["id"] != item.art_id:
            msg = (
                f"{found[0]['id']} ({found[0]['title']}) already has this identity; "
                "call FetchArtifact on it and edit that one"
            )
            problems.add("identity", f"{draft.path}:1", msg)
    item.used = _resolve(store, item, kind.mentions(given), problems)
    if problems:
        return item

    sha = Document(stored).sha256
    if item.versions:
        if item.versions[-1].material["content_hash"] == sha:
            item.action = "noop"
            item.changes = Changes()
            return item
        item.action = "update"
        item.changes = _compare(store, item, me, problems)
    elif item.key is None and (existing := _retry(store, kind.name, me, sha)) is not None:
        item.art_id, item.action = existing, "existing"
        item.changes = Changes()
        return item
    else:
        item.changes = compare([], kind.units(item.doc), me)
    if item.changes is not None:
        _rules(store, item, problems)
    return item


def _rules(store: Store, item: Item, problems: Problems) -> None:
    """类型的轻度规则，只作用于这次新增与修改的行：拒绝的记入 ``problems``，其余记为警告。"""
    assert item.kind is not None and item.doc is not None and item.changes is not None
    changed = {c["at"] for c in (*item.changes.added, *item.changes.modified)}

    def warn(rule: str, line: int, msg: str) -> None:
        item.warnings.append({"rule": rule, "at": item.at(line), "msg": msg})

    def report(rule: str, line: int, msg: str) -> None:
        problems.add(rule, item.at(line), msg)

    item.kind.rules(item.doc, changed, lookup(store), report, warn)


def _base(store: Store, item: Item, problems: Problems) -> None:
    """更新：``id`` 是同类型的产物，``base`` 是它最新版本的提交。"""
    assert item.kind is not None
    where = f"{item.draft.path}:1"
    found = store.query("MATCH (a:Artifact {id: $id}) RETURN a.op AS op", id=item.art_id)
    if not found:
        problems.add("conflict", where, f"{item.art_id} is not an artifact in the store; do not edit the id line")
        return
    if found[0]["op"] != item.kind.name:
        msg = f"{item.art_id} is a {found[0]['op']}, not a {item.kind.name}; do not change the type"
        problems.add("conflict", where, msg)
        return
    item.versions = history(store, str(item.art_id))
    if not item.versions:
        problems.add("conflict", where, f"{item.art_id} has no versioned document; it cannot be edited")
        return
    latest = item.versions[-1]
    if item.base != latest.commit:
        msg = (
            f"base {item.base} is not the latest version of {item.art_id} (v{latest.number}, {latest.commit} by "
            f"{latest.author}); call FetchArtifact again, redo your edits on it, then check in"
        )
        problems.add("conflict", where, msg)


def _across(items: list[Item], problems: Problems) -> None:
    """一次交的几份文档之间：不能是同一份产物，新建的不能是同一个身份键。"""
    seen: dict[str, str] = {}
    for item in items:
        for mark in filter(None, (item.art_id, item.key)):
            if mark in seen:
                msg = f"the same artifact as {seen[mark]}; check in one document per artifact"
                problems.add("identity", f"{item.draft.path}:1", msg)
            seen.setdefault(mark, item.draft.path)


def _resolve(store: Store, item: Item, mentions: list[Mention], problems: Problems) -> dict[str, dict[str, Any]]:
    """核对文档中的引用，返回 ``USED`` 的终点 → 边属性。同一终点只有一条边，``role`` 与 ``locators`` 合成列表。"""
    parsed = [(m, parse_ref(m.text)) for m in mentions]
    heads = {r.head for _, r in parsed if r is not None}
    kinds = store.kinds(heads)
    sources = materials(store, {r.head for _, r in parsed if r is not None and r.kind == "source"})
    current = materials(store, {h for h in heads if kinds.get(h) == ARTIFACT})
    lines: dict[str, list[str] | None] = {}
    keys: dict[str, set[str]] = {}
    roles: dict[str, list[str]] = {}
    locators: dict[str, list[str]] = {}
    pinned: dict[str, str] = {}

    def report(m: Mention, msg: str) -> None:
        problems.add("reference", f"{item.draft.path}:{m.line}", msg)

    for m, ref in parsed:
        if ref is None:
            report(
                m,
                f"not a reference: {m.text!r}; an object id, <material or node>::<section>::<start>:<end>, "
                "or <artifact>#<row key>",
            )
            continue
        if item.art_id is not None and ref.head == item.art_id:
            report(m, "an artifact cannot use itself")
            continue
        if ref.kind == "source":
            material = sources.get(ref.head)
            if material is None or material["owner"] is None:
                report(m, f"{ref.head} is not a material or a node with a material")
                continue
            if material["id"] not in lines:
                lines[material["id"]] = load_lines(store, material)
            total = lines[material["id"]]
            match = LOCATOR.fullmatch(ref.locator or "")
            assert match is not None
            if total is None:
                report(m, f"material {material['id']} is missing or changed since it was registered")
                continue
            if not 1 <= int(match["start"]) <= int(match["end"]) <= len(total):
                report(m, f"lines {match['start']}:{match['end']} are outside 1:{len(total)} of {material['id']}")
                continue
            target = material["owner"]
            pinned.setdefault(target, material["id"])
            locators.setdefault(target, []).append(ref.locator or "")
        elif ref.head not in kinds:
            report(m, f"{ref.head} is not in the store")
            continue
        elif kinds[ref.head] is None:
            report(m, f"{ref.head} is a system record; use the object it belongs to")
            continue
        elif ref.kind == "record":
            if kinds[ref.head] != ARTIFACT:
                report(m, f"{ref.head} is not an artifact")
                continue
            if ref.head not in keys:
                keys[ref.head] = _records(store, ref.head)
            if (ref.key or "").casefold() not in keys[ref.head]:
                report(m, f"{ref.head} has no row {ref.key!r} in its current version")
                continue
            target = ref.head
            roles.setdefault(target, []).append(ref.key or "")
        else:
            target = ref.head
        if kinds.get(target) == ARTIFACT and target in current:
            pinned.setdefault(target, current[target]["id"])  # 固定到引用时的当前版本
        roles.setdefault(target, [])
        if m.role is not None:
            roles[target].append(m.role)
    edges: dict[str, dict[str, Any]] = {}
    for target, names in roles.items():
        props: dict[str, Any] = {}
        if names:
            props["role"] = sorted(set(names))
        if target in pinned:
            props["material_ref"] = pinned[target]
        if target in locators:
            props["locators"] = list(dict.fromkeys(locators[target]))
        edges[target] = props
    return edges


def _records(store: Store, art_id: str) -> set[str]:
    """产物当前版本中可引用的行键（不区分大小写）。旧版 Agent 算子的产物取数据块中的记录键。"""
    info = documents(store, [art_id]).get(art_id)
    if info is None or info["material"] is None:
        return set()
    text = document_text(store, info["material"])
    if text is None:
        return set()
    kind = TYPES.get(info["op"] or "")
    if kind is None:
        return {k.casefold() for k in record_keys(info["op"], data_of(text))}
    try:
        return set(kind.records(parse(strip_checkout(text))))
    except HeaderError:
        return set()


def _compare(store: Store, item: Item, me: str, problems: Problems) -> Changes | None:
    """与基础版本（最新版本）比对：先按各版本推出归属。"""
    assert item.kind is not None and item.doc is not None
    history_docs: list[tuple[str, int, Parsed]] = []
    for version in item.versions:
        doc = load(store, version)
        if doc is None:
            msg = f"the document of v{version.number} of {item.art_id} is missing or changed; the store needs repair"
            problems.add("document", f"{item.draft.path}:1", msg)
            return None
        history_docs.append((version.author, version.number, doc))
    item.history = history_docs
    return compare(blame(item.kind, history_docs), item.kind.units(item.doc), me)


def _retry(store: Store, op: str, me: str, sha: str) -> str | None:
    """没有身份键的类型：同一编辑者写的同类产物中，有版本内容相同的那一份。"""
    found = store.query(
        """MATCH (m:Material {content_hash: $sha})-[:MATERIAL_OF]->(a:Artifact {op: $op, formed_by: $me})
           RETURN a.id AS id ORDER BY id LIMIT 1""",
        sha=sha,
        op=op,
        me=me,
    )
    return found[0]["id"] if found else None


# ── 返回 ──────────────────────────────────────────────────────────────


def _position(item: Item, entry: dict[str, Any]) -> str:
    """改动所在的位置：交上来的文档中的行；删除的行写成基础版本中的行。"""
    if entry.get("change") == "deleted":
        base = item.versions[-1].number if item.versions else 0
        return f"v{base}:{entry['at']}"
    return item.at(entry["at"])


def _entry(item: Item) -> dict[str, Any]:
    out: dict[str, Any] = {"doc": item.draft.path, "type": item.kind.name if item.kind else None}
    if item.art_id is not None:
        out["artifact"] = item.art_id
    out["action"] = item.action
    if item.versions:
        out["base_version"] = item.versions[-1].number
    return out


def _checked(items: list[Item], others: list[tuple[Item, dict[str, Any]]]) -> dict[str, Any]:
    entries = []
    for item in items:
        entry = _entry(item)
        if item.changes is not None and item.action in ("create", "update"):
            summary = item.changes.summary()
            for row in summary.get("modified", []):
                row["at"] = item.at(row["at"])
            for row in summary.get("deleted", []):
                row["at"] = f"v{item.versions[-1].number}:{row['at']}" if item.versions else row["at"]
            entry["changes"] = summary
            entry["others"] = [{**o, "at": _position(item, o)} for o in item.changes.others]
            assert item.kind is not None and item.doc is not None
            if stats := item.kind.stats(item.doc):
                entry["stats"] = stats
            entry["warnings"] = item.warnings
        entries.append(entry)
    steps = "Nothing was written. To write, call CheckIn again with the same artifact_doc and update_abstract"
    steps += " and confirm: true"
    if others:
        steps += ", plus reason: why you changed lines written by others"
    return {"status": "checked", "items": entries, "next": steps + "."}


# ── 写入 ──────────────────────────────────────────────────────────────


def _write(
    store: Store,
    items: list[Item],
    update_abstract: str,
    reason: str | None,
    *,
    at: str,
    session: str,
    formed_by: str,
    agent: str | None,
    sync: Callable[[], int] | None,
) -> dict[str, Any]:
    setup_database(store.graph, store.driver, database=store.database)  # 确实要写入时才建约束与索引
    writing = [item for item in items if item.action in ("create", "update")]
    creates = sum(1 for i in writing if i.action == "create")
    fresh: Iterator[str] = iter(store.graph.allocate_ids(PREFIX, creates) if creates else [])
    old = [i.versions[-1].material["id"] for i in writing if i.versions]
    state = store.graph.local_state([*(i.art_id for i in writing if i.art_id), *old])
    nodes: list[NodeChange] = []
    edges: list[EdgeChange] = []
    files: list[FileRef] = []
    done: dict[int, dict[str, Any]] = {}
    for item in writing:
        assert item.kind is not None and item.doc is not None
        kind, header = item.kind, item.doc.header
        art_id = item.art_id or next(fresh)
        number = len(item.versions) + 1
        document = Document(item.doc.text)
        title = kind.title(header)
        path = _place(store, title, number, document)
        material = "material_" + hashlib.sha256(f"{art_id}\n{number}\n{document.sha256}".encode()).hexdigest()[:12]
        _store_file(store, path, document)
        files.append(FileRef(path, document.sha256))
        props = {"op": kind.name, "op_version": kind.version, "title": title, "abs": kind.abstract(header)}
        if item.key is not None:
            props["key"] = item.key
        if item.action == "create":
            nodes.append(NodeChange.create(art_id, [ARTIFACT], props | {"formed_by": formed_by, "formed_at": at}))
        else:
            node = state.nodes[art_id]
            before, after = _delta(node.props, {k: v for k, v in node.props.items() if k != "key"} | props)
            if before:
                nodes.append(NodeChange.update(art_id, node.labels, before, after))
            old_id = item.versions[-1].material["id"]
            superseded = ({"superseded_by": None}, {"superseded_by": material})
            nodes.append(NodeChange.update(old_id, state.nodes[old_id].labels, *superseded))
        nodes.append(
            NodeChange.create(
                material, ["Material"], {"path": path, "format": "markdown", "content_hash": document.sha256}
            )
        )
        edges.append(EdgeChange.create(material, "MATERIAL_OF", art_id))
        edges += _used_changes(state, art_id, item.used)
        item.art_id = art_id
        done[id(item)] = {"version": number, "document": {"path": path, "material_ref": material}}
        if notes := _notes(store, item, formed_by, number):
            done[id(item)]["notes"] = notes
        if item.warnings:
            done[id(item)]["warnings"] = item.warnings

    meta: dict[str, Any] = {
        "artifacts": [
            {"id": i.art_id, "version": done[id(i)]["version"], "action": i.action, "doc": i.draft.path}
            for i in writing
        ],
        "session": session,
    }
    if reason:
        meta["reason"] = reason.strip()
    if agent:
        meta["agent"] = agent
    text = dump(
        {"update_abstract": update_abstract, "reason": reason, "docs": {i.draft.path: i.draft.text for i in items}}
    )
    try:
        record = store.graph.commit(
            Changeset(nodes=tuple(nodes), edges=tuple(edges), files=tuple(files)),
            author=formed_by,
            message=update_abstract.strip(),
            source=SOURCE,
            input=text,
            meta=meta,
        )
    except ConflictError as exc:  # 校验之后有人检入了同一份产物，或所引的对象被改动
        msg = f"the store changed while checking in ({exc}); call FetchArtifact again and redo your edits"
        raise ContractError([{"rule": "conflict", "at": items[0].draft.path, "msg": msg}], status="conflict") from exc

    warnings: list[dict[str, str]] = []
    if sync is not None:
        try:
            sync()
        except (httpx.HTTPError, ValueError) as exc:
            warnings.append(
                {"rule": "embedding", "at": record.id, "msg": f"embeddings not synced ({exc}); run make embed"}
            )
    out_items = []
    for item in items:
        entry = _entry(item)
        entry.pop("base_version", None)
        entry.update(done.get(id(item), {}))
        out_items.append(entry)
    return {"status": "committed", "commit": record.id, "items": out_items, "warnings": warnings}


def _notes(store: Store, item: Item, me: str, number: int) -> dict[str, Any]:
    """新版本读取时现算的附注（如 Leaderboard 的每位编辑者写的行数、同一格的多个值），行号换算成写者文件中的。"""
    assert item.kind is not None and item.doc is not None
    blamed = blame(item.kind, [*item.history, (me, number, item.doc)])
    authors = {b.unit.line: (b.author, b.version) for b in blamed}
    pinned = {t: p["material_ref"] for t, p in item.used.items() if "material_ref" in p}
    return relocate(item.kind.notes(item.doc, authors, lookup(store, pinned)), item.at)


def relocate(value: Any, at: Callable[[int], Any]) -> Any:
    """把附注中各处的 ``at``（文档中的行号）换算成调用者给的位置。"""
    if isinstance(value, dict):
        return {k: at(v) if k == "at" and isinstance(v, int) else relocate(v, at) for k, v in value.items()}
    if isinstance(value, list):
        return [relocate(v, at) for v in value]
    return value


def _used_changes(state: Any, art_id: str, used: dict[str, dict[str, Any]]) -> list[EdgeChange]:
    """按新版本重写 ``USED`` 边：删掉不再用的，改动属性变了的，新增新用到的。"""
    existing = {k.dst: props for k, props in state.edges.items() if k.src == art_id and k.type == "USED"}
    out = [EdgeChange.delete(art_id, "USED", dst, props) for dst, props in existing.items() if dst not in used]
    for dst, props in used.items():
        if dst not in existing:
            out.append(EdgeChange.create(art_id, "USED", dst, props))
        elif existing[dst] != props:
            out.append(EdgeChange.update(art_id, "USED", dst, *_delta(existing[dst], props)))
    return out


def _delta(before: dict[str, Any], after: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """graph-vc 的更新只列出改变的属性，没有的属性写成 ``None``。"""
    keys = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
    return {k: before.get(k) for k in keys}, {k: after.get(k) for k in keys}


def _place(store: Store, title: str, version: int, document: Document) -> str:
    """版本文档的路径（相对于材料根目录）：``artifacts/<标题>.v<版本>.md``，被内容不同的文件占用时加序号。"""
    n = 0
    while True:
        path = f"{DIRECTORY}/{version_file_name(title or 'artifact', version, n)}"
        file = store.material_root / path
        if not file.exists() or hashlib.sha256(file.read_bytes()).hexdigest() == document.sha256:
            return path
        n += 1


def _store_file(store: Store, path: str, document: Document) -> None:
    """先写临时文件再改名；同名文件内容相同时沿用。事务失败时文件留在原处：没有节点引用它，重试时直接沿用。"""
    file = store.material_root / path
    if file.exists():
        return
    file.parent.mkdir(parents=True, exist_ok=True)
    partial = file.with_name(file.name + ".partial")
    partial.write_bytes(document.text.encode("utf-8"))
    partial.replace(file)


__all__ = ["SOURCE", "check_in", "relocate"]
