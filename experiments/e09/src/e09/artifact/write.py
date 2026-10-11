"""Agent 算子的共同写入路径（docs/designs/v2/operators.md §4.1、§5）：校验 → 文档 → 一次提交。

    write_artifact(store, request, validators, at=…)
      -> {artifact-result, status, artifact, commit, document, warnings, render}

请求是 ``{op, title?, abs, inputs, params, payload, session, formed_by}``。

1. **共同校验**，任一不过即整次拒绝、不写入（:class:`OperatorError`）：

   - ``inputs`` 中的对象引用、Artifact 与记录引用都在库中；来源引用格式正确，所指材料在库中、文件与登记的哈希
     一致、行号不越界；
   - ``params`` 与 ``payload`` 符合该算子的 schema，判断类的每个单元恰有一条判断（各算子的 ``validate``，
     见 :mod:`e09.operators.agent`）；
   - ``params`` 与 ``payload`` 中出现的每个引用都由 ``inputs`` 覆盖：与某一项相同；或是来源引用，所指的行落在
     同一材料的某个来源引用的行范围内（章节名不比较）；或是记录引用，所属的 Artifact 列在 ``inputs`` 中（记录须
     存在）；或是对象引用，正是某一项 ``USED`` 的终点（如论文，它的材料中的行已列在 ``inputs`` 中）。来源引用的
     开头写材料 id 或材料所属的节点 id 都算同一个引用；文档头部的 ``nodes_used`` 统一写成材料 id，与 ReadEvidence
     读取的写法相同。

2. **幂等**：相同 ``artifact_key``（``op``、``inputs``、``params``、``payload`` 与 ``formed_by`` 的哈希）视为重试，
   返回已有的 Artifact，不重复写入。

3. **写入**：文档按标题写到材料根目录的 ``artifacts/`` 下，标题重复时加 `` (1)``、`` (2)``；内容相同的文档已有
   Material 时沿用它的文件，同名文件内容相同时直接沿用（:func:`_place`）。再经 graph-vc 在一个事务中写 Artifact
   节点、``USED`` 边、Material 与 ``MATERIAL_OF``，产生一个提交（``source`` 为 ``operator:<op>``，``meta`` 记
   Artifact 的 id 与会话）。事务失败时文件留在原处：没有节点引用，不影响库，重试时按内容相同直接沿用。

4. 提交后补算 ``title`` 与 ``abs`` 的向量；失败不影响已完成的提交，只在 ``warnings`` 中提示。

``USED`` 边：同一终点只有一条边（graph-vc 的边以起点、类型、终点标识）。对象引用连到该对象，``role`` 取它在参数
中的角色（Check、Filter 的项键，MatrixConstruct 的行列键，Verify 的 ``claim``）；记录引用连到记录所属的
Artifact，``role`` 是记录键；来源引用连到材料所属的节点（论文或 Artifact），边上带 ``material_ref`` 与
``locators``。``role`` 与 ``locators`` 都是列表。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx

from graph_vc import Changeset, ConflictError, EdgeChange, FileRef, NodeChange

from ..model.refs import Ref, parse_ref
from ..model.schema import ARTIFACT, LOCATOR
from ..query.materials import load_lines, materials
from ..store.database import setup_database
from ..store.store import ContractError, Store
from ..yamlfmt import dump
from .document import DIRECTORY, Document, compose, data_of, file_name, header_of, record_keys
from .stale import document_text, documents

VERSION = "v0.1"
REQUEST_KEYS = ("op", "title", "abs", "inputs", "params", "payload", "session", "formed_by")
REQUIRED = frozenset(REQUEST_KEYS) - {"title"}
PREFIX = "art"


class Problems:
    """调用中的错误：``{rule, at, msg}``，与 Commit 阻塞项的形状相同。"""

    def __init__(self) -> None:
        self.items: list[dict[str, str]] = []

    def add(self, rule: str, at: str, msg: str) -> None:
        self.items.append({"rule": rule, "at": at, "msg": msg})

    def __bool__(self) -> bool:
        return bool(self.items)


@dataclass
class Output:
    title: str
    body: str
    data: Any = None  # 正文末尾的数据块；只有 Extract、Check、Filter、MatrixConstruct 有
    refs: list[tuple[str, str]] = field(default_factory=list)  # (位置, 引用)：必须由 inputs 覆盖
    roles: dict[str, list[str]] = field(default_factory=dict)  # 引用 → 它在参数中的角色（USED.role）
    stats: dict[str, Any] = field(default_factory=dict)


Validate = Callable[[Mapping[str, Any], Mapping[str, Any], Problems], Output]
"""一个 Agent 算子的校验：``(params, payload, problems) -> Output``，问题记入 ``problems``。"""


class OperatorError(ContractError):
    """Agent 算子的调用没有通过校验，或提交时冲突（``status`` 为 ``conflict``），什么也没有写入。"""


@dataclass(frozen=True, slots=True)
class Input:
    """``inputs`` 中的一项。``target`` 是 ``USED`` 的终点；``spelling`` 是写进 ``nodes_used`` 的写法。"""

    ref: Ref
    target: str
    spelling: str
    material: str | None = None


def write_artifact(
    store: Store,
    request: Mapping[str, Any],
    validators: Mapping[str, Validate],
    *,
    at: str,
    text: str | None = None,
    sync: Callable[[], int] | None = None,
    agent: str | None = None,
    draft: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """校验并写入一次 Agent 算子调用的产物。``validators`` 是各算子的校验，按 ``op`` 取用；``at`` 是形成时间；
    ``text`` 是交上来的请求原文（记入提交），不给时用请求的 YAML；``sync`` 在提交后补算向量；``agent``（所用的 Agent 与模型）记入提交的 ``meta.agent``；
    ``draft``（内容来自草稿文件时，文件的路径与哈希，见 :mod:`e09.draft`）记入提交的 ``meta.draft``。

    Raises:
        OperatorError: 调用没有通过校验。
    """
    problems = Problems()
    _shape(request, validators, problems)
    if problems:
        raise OperatorError(problems.items)
    op = request["op"]
    output = validators[op](request["params"], request["payload"], problems)
    inputs, owner = _resolve(store, request["inputs"], output, problems)
    if problems:
        raise OperatorError(problems.items)

    warnings = _unused(inputs, output, owner)
    key = artifact_key(request)
    found = store.query("MATCH (a:Artifact {artifact_key: $key}) RETURN a.id AS id", key=key)
    if found:
        return _existing(store, found[0]["id"], warnings, output)

    setup_database(store.graph, store.driver, database=store.database)  # 通过校验、确实要写入时才建约束与索引
    title = request.get("title") or output.title
    nodes_used = [i.spelling for i in inputs]
    document = compose(title, nodes_used, request["abs"].strip(), output.body, output.data)
    path = _place(store, document, title)
    _store_file(store, path, document)
    art_id = store.graph.allocate_ids(PREFIX, 1)[0]
    props = {
        "op": op,
        "title": title,
        "abs": request["abs"].strip(),
        "params": json.dumps(request["params"], ensure_ascii=False, sort_keys=True, default=str),
        "formed_by": request["formed_by"],
        "formed_at": at,
        "session": request["session"],
        "artifact_key": key,
    }
    changeset = _changeset(store, art_id, props, document, path, _used(inputs, output, owner))
    try:
        record = store.graph.commit(
            changeset,
            author=request["formed_by"],
            message=title,
            source=f"operator:{op}",
            input=text if text is not None else dump(dict(request)),
            meta={"artifact": art_id, "session": request["session"]}
            | ({"agent": agent} if agent else {})
            | ({"draft": dict(draft)} if draft else {}),
        )
    except ConflictError as exc:  # 校验之后有对象被删除或改动
        raise OperatorError([{"rule": "conflict", "at": "inputs", "msg": str(exc)}], status="conflict") from exc

    if sync is not None:
        try:
            sync()
        except (httpx.HTTPError, ValueError) as exc:
            msg = f"embeddings not synced ({exc}); run make embed"
            warnings.append({"rule": "embedding", "at": art_id, "msg": msg})
    return _result("created", art_id, record.id, path, document.material_id, warnings, output)


def artifact_key(request: Mapping[str, Any]) -> str:
    """幂等键：``op``、``inputs``、``params``、``payload`` 与 ``formed_by`` 的哈希。"""
    keyed = {k: request.get(k) for k in ("op", "inputs", "params", "payload", "formed_by")}
    text = json.dumps(keyed, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# ── 校验 ──────────────────────────────────────────────────────────────


def _shape(request: Any, validators: Mapping[str, Validate], problems: Problems) -> None:
    if not isinstance(request, Mapping):
        problems.add("format", "request", f"a mapping with {list(REQUEST_KEYS)}")
        return
    if unknown := sorted(set(request) - set(REQUEST_KEYS)):
        problems.add("format", "request", f"unknown keys {unknown}; a call has {list(REQUEST_KEYS)}")
    for key in sorted(REQUIRED - set(request)):
        problems.add("format", key, "required")
    op = request.get("op")
    if op not in validators and "op" in request:
        problems.add("format", "op", f"one of {list(validators)}")
    for key in ("title", "abs", "session", "formed_by"):
        value = request.get(key)
        if key in request and not (isinstance(value, str) and value.strip()):
            problems.add("format", key, "a non-empty string")
    inputs = request.get("inputs")
    if "inputs" in request:
        if not isinstance(inputs, list) or not inputs or not all(isinstance(i, str) for i in inputs):
            problems.add("format", "inputs", "a non-empty list of references to what was used")
        elif len(set(inputs)) != len(inputs):
            problems.add("format", "inputs", "lists a reference more than once")
    for key in ("params", "payload"):
        if key in request and not isinstance(request[key], Mapping):
            problems.add("format", key, "a mapping")


Owner = Callable[[str], "Input | None"]


def _resolve(store: Store, texts: list[str], output: Output, problems: Problems) -> tuple[list[Input], Owner]:
    """核对 ``inputs`` 都在库中，并核对 ``params`` 与 ``payload`` 中的引用都由 ``inputs`` 覆盖。

    返回 ``inputs`` 与找出覆盖一个引用的那一项的函数（没有时为 ``None``）。"""
    parsed = [(i, text, parse_ref(text)) for i, text in enumerate(texts)]
    mentioned = [parse_ref(text) for _, text in output.refs]
    heads = {r.head for r in [*(r for _, _, r in parsed), *mentioned] if r is not None}
    kinds = store.kinds(heads)
    found = materials(store, {r.head for r in [*(r for _, _, r in parsed), *mentioned] if r and r.kind == "source"})

    def spell(text: str) -> str | None:
        ref = parse_ref(text)
        if ref is None:
            return None
        if ref.kind == "source" and ref.head in found:
            return f"{found[ref.head]['id']}::{ref.locator}"
        return ref.text

    inputs: list[Input] = []
    lines: dict[str, list[str] | None] = {}
    keys: dict[str, list[str]] = {}
    for i, _, ref in parsed:
        at = f"inputs[{i}]"
        if ref is None:
            msg = "an object id, <material or node>::<section>::<start>:<end>, or <artifact>#<key>"
            problems.add("reference", at, msg)
        elif ref.kind == "object":
            if ref.head not in kinds:
                problems.add("reference", at, f"{ref.head} is not in the store")
            elif kinds[ref.head] is None:
                problems.add("reference", at, f"{ref.head} is a system record; use the object it belongs to")
            else:
                inputs.append(Input(ref, ref.head, ref.text))
        elif ref.kind == "record":
            if kinds.get(ref.head) != ARTIFACT:
                problems.add("reference", at, f"{ref.head} is not an artifact in the store")
                continue
            if ref.head not in keys:
                keys[ref.head] = _record_keys(store, ref.head)
            if ref.key not in keys[ref.head]:
                problems.add("reference", at, f"{ref.head} has no record {ref.key!r}")
            else:
                inputs.append(Input(ref, ref.head, ref.text))
        else:
            material = found.get(ref.head)
            if material is None:
                problems.add("reference", at, f"{ref.head} is not a material or a node with a material")
                continue
            if material["owner"] is None:
                problems.add("reference", at, f"material {material['id']} belongs to no object")
                continue
            if material["id"] not in lines:
                lines[material["id"]] = load_lines(store, material)
            total = lines[material["id"]]
            match = LOCATOR.fullmatch(ref.locator or "")
            assert match is not None
            if total is None:
                msg = f"material {material['id']} is missing or changed since it was registered"
                problems.add("reference", at, msg)
            elif not 1 <= int(match["start"]) <= int(match["end"]) <= len(total):
                problems.add("reference", at, f"lines {match['start']}:{match['end']} are outside 1:{len(total)}")
            else:
                inputs.append(Input(ref, material["owner"], spell(ref.text) or ref.text, material["id"]))

    by_spelling = {i.spelling: i for i in inputs} | {i.ref.text: i for i in inputs}

    def owner(text: str) -> Input | None:
        ref = parse_ref(text)
        if ref is None:
            return None
        exact = by_spelling.get(text) or by_spelling.get(spell(text) or "")
        if exact is not None:
            return exact
        if ref.kind == "record":
            return next((i for i in inputs if i.ref.kind == "object" and i.ref.head == ref.head), None)
        if ref.kind == "object":  # 如论文：它的材料中的行已列在 inputs 中
            return next((i for i in inputs if i.target == ref.head), None)
        material = found.get(ref.head) if ref.kind == "source" else None
        if material is None:
            return None
        span = _span(ref.locator)
        return next((i for i in inputs if i.material == material["id"] and _within(span, _span(i.ref.locator))), None)

    for at, text in output.refs:
        ref = parse_ref(text)
        holder = owner(text)
        if ref is None:
            problems.add("reference", at, f"not a reference: {text!r}")
        elif holder is None:
            if not _failed(text, texts, spell):
                problems.add("reference", at, f"{text} is not among inputs or within a source reference in inputs")
        elif ref.kind == "record" and holder.ref.kind == "object":
            if ref.head not in keys:
                keys[ref.head] = _record_keys(store, ref.head)
            if ref.key not in keys[ref.head]:
                problems.add("reference", at, f"{ref.head} has no record {ref.key!r}")
    return inputs, owner


def _span(locator: str | None) -> tuple[int, int]:
    match = LOCATOR.fullmatch(locator or "")
    return (int(match["start"]), int(match["end"])) if match else (0, -1)


def _within(inner: tuple[int, int], outer: tuple[int, int]) -> bool:
    return outer[0] <= inner[0] <= inner[1] <= outer[1]


def _failed(text: str, inputs: list[str], spell: Callable[[str], str | None]) -> bool:
    """引用列在 inputs 中，只是自身没有通过核对（已另行报告），不再重复报告。"""
    return text in inputs or spell(text) in {spell(i) for i in inputs}


def _record_keys(store: Store, art_id: str) -> list[str]:
    info = documents(store, [art_id]).get(art_id)
    if info is None or info["material"] is None:
        return []
    text = document_text(store, info["material"])
    return record_keys(info["op"], data_of(text)) if text is not None else []


def _unused(inputs: list[Input], output: Output, owner: Owner) -> list[dict[str, str]]:
    """``inputs`` 中没有覆盖参数或内容里任何引用的项：不阻塞，提示。"""
    used = {id(i) for _, text in output.refs if (i := owner(text)) is not None}
    return [
        {"rule": "unused-input", "at": f"inputs[{n}]", "msg": f"{i.ref.text} is not referenced in params or payload"}
        for n, i in enumerate(inputs)
        if id(i) not in used
    ]


# ── 写入 ──────────────────────────────────────────────────────────────


def _used(inputs: list[Input], output: Output, owner: Owner) -> dict[str, dict[str, Any]]:
    """``USED`` 的终点 → 边属性；同一终点的角色与定位合成列表。"""
    roles: dict[str, list[str]] = {}
    locators: dict[str, list[str]] = {}
    material: dict[str, str] = {}
    for i in inputs:
        roles.setdefault(i.target, [])
        if i.ref.kind == "record" and i.ref.key is not None:
            roles[i.target].append(i.ref.key)
        if i.ref.kind == "source" and i.material is not None and i.ref.locator is not None:
            material[i.target] = i.material
            locators.setdefault(i.target, []).append(i.ref.locator)
    for text, names in output.roles.items():
        holder = owner(text)
        if holder is not None:
            roles[holder.target] += names
    edges: dict[str, dict[str, Any]] = {}
    for target in roles:
        props: dict[str, Any] = {}
        if roles[target]:
            props["role"] = sorted(set(roles[target]))
        if target in material:
            props["material_ref"] = material[target]
            props["locators"] = list(dict.fromkeys(locators[target]))
        edges[target] = props
    return edges


def _place(store: Store, document: Document, title: str) -> str:
    """文档的路径（相对于材料根目录）。内容相同的文档已有 Material 时沿用它的路径；否则取标题对应的文件名，已被
    内容不同的文件占用时依次加序号。写入逐个执行，选定的名字不会被同时占用。"""
    existing = store.graph.local_state([document.material_id]).nodes.get(document.material_id)
    if existing is not None:
        return str(existing.props["path"])
    n = 0
    while True:
        path = f"{DIRECTORY}/{file_name(title, n)}"
        file = store.material_root / path
        if not file.exists() or hashlib.sha256(file.read_bytes()).hexdigest() == document.sha256:
            return path
        n += 1


def _store_file(store: Store, path: str, document: Document) -> None:
    file = store.material_root / path
    if file.exists():
        if hashlib.sha256(file.read_bytes()).hexdigest() != document.sha256:
            raise RuntimeError(f"{path} exists with other content; artifact documents are never rewritten")
        return
    file.parent.mkdir(parents=True, exist_ok=True)
    partial = file.with_name(file.name + ".partial")
    partial.write_bytes(document.text.encode("utf-8"))
    partial.replace(file)


def _changeset(
    store: Store, art_id: str, props: dict[str, Any], document: Document, path: str, used: dict[str, dict[str, Any]]
) -> Changeset:
    nodes = [NodeChange.create(art_id, [ARTIFACT], props)]
    if document.material_id not in store.graph.local_state([document.material_id]).nodes:
        material = {"path": path, "format": "markdown", "content_hash": document.sha256}
        nodes.append(NodeChange.create(document.material_id, ["Material"], material))
    edges = [EdgeChange.create(document.material_id, "MATERIAL_OF", art_id)]
    edges += [EdgeChange.create(art_id, "USED", target, edge) for target, edge in used.items()]
    return Changeset(nodes=tuple(nodes), edges=tuple(edges), files=(FileRef(path, document.sha256),))


def _existing(store: Store, art_id: str, warnings: list[dict[str, str]], output: Output) -> dict[str, Any]:
    info = documents(store, [art_id])[art_id]
    material = info["material"] or {}
    text = document_text(store, material) if material else None
    out = _result("existing", art_id, None, material.get("path"), material.get("id"), warnings, output)
    out["render"] = _body(text) if text is not None else None
    return out


def _result(
    status: str,
    art_id: str,
    commit: str | None,
    path: str | None,
    material: str | None,
    warnings: list[dict[str, str]],
    output: Output,
) -> dict[str, Any]:
    out: dict[str, Any] = {"artifact-result": VERSION, "status": status, "artifact": art_id, "commit": commit}
    out["document"] = {"path": path, "material_ref": material}
    out["warnings"] = warnings
    if output.stats:
        out["stats"] = output.stats
    out["render"] = _shown(output.body, art_id)
    return out


RENDER_LINES = 40  # 返回给写者的正文行数上限；完整的正文在产物文档中


def _shown(body: str, art_id: str) -> str:
    """返回给写者的正文：写者刚交上的内容不必整份读回，过长时只给开头几行与余下的行数。"""
    lines = body.splitlines()
    if len(lines) <= RENDER_LINES:
        return body
    rest = len(lines) - RENDER_LINES
    return "\n".join([*lines[:RENDER_LINES], f"… {rest} more lines, all kept in the document of {art_id}"])


def _body(text: str) -> str:
    """文档去掉头部后的正文。"""
    header = header_of(text)
    if not header:
        return text
    return text.split("\n---\n", 1)[1].strip() + "\n"


__all__ = ["VERSION", "Input", "OperatorError", "Output", "Problems", "Validate", "artifact_key", "write_artifact"]
