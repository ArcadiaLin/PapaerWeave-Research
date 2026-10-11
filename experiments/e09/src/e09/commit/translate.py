"""graph-doc → 物理目标状态（:class:`~graph_doc.Fragment`）：E09 数据模型的写入规则。

翻译只处理“文档写了什么”，与库中现状的比较留给 :func:`graph_doc.diff`，写入后的状态是否合规留给
:mod:`e09.commit.checks`。模型相关的翻译（docs/experiments/e09/operators/commit.md §2–§3）：

- ``kind`` → 主 Label 与次级 Label；改 kind 只能在同一类别内。
- ``name`` 与 ``aliases`` → ``(:NameKey {id: key})-[:NAMES]->(对象)``；名称变动时增删 NameKey，
  同一文档中从一个对象移到另一个对象的名称改指，而不是删了再建。
- Paper 的 ``material`` → ``(:Material)-[:MATERIAL_OF]->(Paper)``，文件登记进变更集；暂不支持更换材料。
- ``FROM`` 边补上 ``material_ref``；边上的 ``source_refs`` 把 ``<节点>::<定位>`` 换成 ``<材料 id>::<定位>``。
- Agent 形成的记录与正反关系补上 ``formed_by``、``formed_at``；Experiment 补 ``exp_key``，
  论文陈述的 Claim、Contribution 新建时补 ``content_key``。
- 只读字段（``_`` 开头）与库中现状比对，改动即报错。
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from graph_doc import DocEdge, DocNode, Document, Fragment, FragmentNode, is_temp
from graph_vc import EdgeKey, FileRef, GraphState, NodeState

from ..model.namekey import NORMALIZER, name_key, normalize
from ..model.schema import (
    ARTIFACT,
    EVALUATES_ROLES,
    FAMILY,
    FIELDS,
    GENERIC_REL_PROPS,
    LOCATOR,
    NAMED,
    NAMESPACES,
    OPEN_KINDS,
    RELATIONSHIPS,
    STANCE_RELS,
    STATED_BY,
    SYSTEM_FIELDS,
    SYSTEM_REL_PROPS,
    SYSTEM_RELS,
    USES_ROLES,
    Relationship,
    kind_of,
)
from ..query.view import edge_readonly, material_of, node_readonly
from .problems import Problem
from .reader import Reader
from .review import Deduper

_MISSING = object()


@dataclass(frozen=True, slots=True)
class Context:
    """一次写入的环境：读取现状的入口、来源标签（记入 NameKey.registered_from 与提交的 source）、
    形成时间（``formed_at``）、材料路径的根目录，以及查重的入口（``None`` 表示不查重，如种子批量入库）。

    ``user`` 是调用方的登录身份：给出时文档的 ``by`` 可以省略（取 ``user``），写了就必须与它相同；``agent`` 是
    所用的 Agent 与模型，记入提交的 ``meta.agent``。二者由服务端给出，不由写入者声明。"""

    reader: Reader
    source: str
    at: str
    material_root: Path
    deduper: Deduper | None = None
    user: str | None = None
    agent: str | None = None


@dataclass(frozen=True, slots=True)
class Translation:
    fragment: Fragment
    files: tuple[FileRef, ...]
    local: GraphState  # 求差与检查用的局部现状
    problems: tuple[Problem, ...]
    refs: dict[str, str]  # 节点 id → 文档中的引用，用于问题定位


def translate(doc: Document, ctx: Context, ids: Mapping[str, str] | None = None) -> Translation:
    """翻译 ``doc``。``ids`` 把临时引用换成分配到的 id；不给时临时引用原样作 id（dry_run）。"""
    return _Translator(doc, ctx, dict(ids or {})).run()


@dataclass
class _Material:
    path: str
    sha256: str

    @property
    def id(self) -> str:
        return f"material_{self.sha256[:12]}"


@dataclass
class _Translator:
    doc: Document
    ctx: Context
    ids: dict[str, str]
    problems: list[Problem] = field(default_factory=list)
    local: GraphState = field(default_factory=GraphState)
    nodes: dict[str, FragmentNode] = field(default_factory=dict)
    deletes: set[str] = field(default_factory=set)
    files: list[FileRef] = field(default_factory=list)
    kinds: dict[str, str] = field(default_factory=dict)  # 文档中节点 id → 写入后的 kind
    aliases: dict[str, list[str]] = field(default_factory=dict)  # 文档写了 aliases 的节点
    materials: dict[str, _Material] = field(default_factory=dict)  # 文档登记材料的节点 id → 材料
    new_materials: dict[str, str] = field(default_factory=dict)  # 节点 id → 本次登记的材料 id
    lines: dict[str, int | None] = field(default_factory=dict)  # 材料 id → 行数

    def run(self) -> Translation:
        if self.doc.by is None:
            self.error("format", "by", "the writer is required")
        self.fetch()
        for ref, node in self.doc.nodes.items():
            if node is None:
                self.delete(ref)
            else:
                self.node(ref, node)
        self.namekeys()
        self.derived_keys()
        fragment = Fragment(self.nodes, frozenset(self.deletes))
        refs = {self.r(ref): ref for ref in self.doc.nodes}
        return Translation(fragment, tuple(self.files), self.local, tuple(self.problems), refs)

    # ── 基础 ──────────────────────────────────────────────────────────

    def r(self, ref: str) -> str:
        return self.ids.get(ref, ref)

    def error(self, rule: str, at: str, msg: str, candidates: tuple[str, ...] = ()) -> None:
        self.problems.append(Problem(rule, at, msg, "error", candidates))

    def warn(self, rule: str, at: str, msg: str) -> None:
        self.problems.append(Problem(rule, at, msg, "warning"))

    def kind(self, node_id: str) -> str | None:
        """写入后的 kind；Artifact 返回 ``Artifact``。"""
        if node_id in self.kinds:
            return self.kinds[node_id]
        node = self.local.nodes.get(node_id)
        if node is None:
            return None
        return kind_of(node.labels) or (ARTIFACT if ARTIFACT in node.labels else None)

    def material(self, node_id: str) -> str | None:
        return self.new_materials.get(node_id) or material_of(node_id, self.local)

    # ── 读取现状 ──────────────────────────────────────────────────────

    def fetch(self) -> None:
        """取出文档涉及的局部现状：节点、关系终点、来源引用指向的节点，以及要登记的材料。"""
        wanted: set[str] = set()
        for ref, node in self.doc.nodes.items():
            wanted.add(self.r(ref))
            if node is None:
                continue
            for edges in node.rels.values():
                for edge in edges:
                    wanted.add(self.r(edge.to))
                    for source_ref in _strings(edge.props.get("source_refs")):
                        wanted.add(self.r(source_ref.partition("::")[0]))
            path = node.props.get("material")
            if isinstance(path, str):
                material = self.hash_material(f"nodes.{ref}.material", path)
                if material is not None:
                    # 先登记，使文档中任何位置的 FROM 与来源引用都能用上新论文的材料。
                    # 登记被拒绝时也保留，避免引用它的定位再各报一遍“没有材料”。
                    self.materials[self.r(ref)] = material
                    self.new_materials[self.r(ref)] = material.id
                    wanted.add(material.id)
        self.local = self.ctx.reader.local_state(sorted(wanted))

    def hash_material(self, at: str, path: str) -> _Material | None:
        if Path(path).is_absolute() or ".." in Path(path).parts:
            self.error("material", at, "the material path must be relative to the material root")
            return None
        file = self.ctx.material_root / path
        if not file.is_file():
            self.error("material", at, f"{path} does not exist")
            return None
        return _Material(path, hashlib.sha256(file.read_bytes()).hexdigest())

    # ── 节点 ──────────────────────────────────────────────────────────

    def delete(self, ref: str) -> None:
        node_id, at = self.r(ref), f"nodes.{ref}"
        current = self.local.nodes.get(node_id)
        if current is None:
            self.error("reference", at, f"{ref} does not exist")
        elif kind_of(current.labels) is None:
            self.error("readonly", at, "Artifacts and system records cannot be deleted through graph-doc")
        else:
            self.deletes.add(node_id)

    def node(self, ref: str, doc_node: DocNode) -> None:
        node_id, at = self.r(ref), f"nodes.{ref}"
        current = self.local.nodes.get(node_id)
        if not is_temp(ref) and current is None:
            self.error("reference", at, f"{ref} does not exist")
            return
        if current is not None and kind_of(current.labels) is None:
            if ARTIFACT in current.labels and not doc_node.props and not doc_node.rels:
                return  # 读视图原样带回的 Artifact：只读字段，忽略
            self.error("readonly", at, "Artifacts and system records cannot be written through graph-doc")
            return
        kind = self.resolve_kind(at, doc_node, current)
        if kind is None:
            return
        self.kinds[node_id] = kind

        props: dict[str, Any] = {}
        for key, value in doc_node.props.items():
            self.node_prop(f"{at}.{key}", node_id, kind, key, value, props)
        self.check_readonly(at, doc_node.readonly, node_readonly(node_id, self.local) if current else None)
        if current is None and (kind == "Observation" or props.get("stated_by") == "agent"):
            props["formed_by"] = self.doc.by
            props["formed_at"] = self.ctx.at

        rels: dict[str, dict[str, dict[str, Any]]] = {}
        for rel_type, edges in doc_node.rels.items():
            spec = RELATIONSHIPS.get(rel_type)
            rel_at = f"{at}.{rel_type}"
            if spec is None:
                reason = "is maintained by the system" if rel_type in SYSTEM_RELS else "is not in the graph model"
                self.error("relationship", rel_at, f"relationship type {rel_type} {reason}")
                continue
            rels[rel_type] = {
                self.r(edge.to): self.edge_props(f"{rel_at}[{i}]", node_id, rel_type, spec, edge)
                for i, edge in enumerate(edges)
            }

        labels = frozenset({FAMILY[kind], kind})
        self.nodes[node_id] = FragmentNode(
            labels=labels if current is None or labels != current.labels else None,
            props=props,
            rels=rels,
            new=current is None,
        )

    def resolve_kind(self, at: str, doc_node: DocNode, current: NodeState | None) -> str | None:
        written = doc_node.props.get("kind", _MISSING)
        current_kind = kind_of(current.labels) if current is not None else None
        if written is _MISSING:
            if current_kind is None:
                self.error("format", f"{at}.kind", "a new node needs kind")
            return current_kind
        if written is None:
            self.error("format", f"{at}.kind", "kind cannot be cleared")
            return None
        if not isinstance(written, str) or written not in FAMILY:
            self.error("format", f"{at}.kind", f"unknown kind {written!r}")
            return None
        if current_kind is not None and FAMILY[written] != FAMILY[current_kind]:
            self.error("format", f"{at}.kind", f"cannot change {current_kind} into {written} (another family)")
            return None
        return written

    def node_prop(self, at: str, node_id: str, kind: str, key: str, value: Any, props: dict[str, Any]) -> None:
        if key == "kind":
            return
        if key in SYSTEM_FIELDS:
            self.error("field", at, f"{key} is set by the system")
            return
        if key not in FIELDS[kind]:
            if kind in OPEN_KINDS:
                self.warn("field", at, f"{key} is not a field of {kind} in the graph model; stored as given")
                props[key] = value
            else:
                self.error("field", at, f"{key} is not a field of {kind}")
            return
        if key == "aliases":
            aliases = [] if value is None else value
            if not isinstance(aliases, list) or not all(isinstance(a, str) and normalize(a) for a in aliases):
                self.error("field", at, "aliases must be a list of non-empty strings")
            else:
                self.aliases[node_id] = aliases
        elif key == "material":
            self.attach_material(at, node_id)
        elif key == "name" and value is not None and not (isinstance(value, str) and normalize(value)):
            self.error("field", at, "name must be a non-empty string")
        elif key == "identifiers" and value is not None:
            self.check_identifiers(at, node_id, value)
            props[key] = value
        elif key == "stub" and value not in (True, None):
            self.error("field", at, "stub is either true or absent")
        elif key == "stated_by" and value is not None and value not in STATED_BY:
            self.error("field", at, f"stated_by is one of {sorted(STATED_BY)}")
        elif key == "anchors" and value is not None and not (isinstance(value, list) and value):
            self.error("field", at, "anchors must be a non-empty list; the first one is the primary anchor")
        else:
            props[key] = value

    def check_readonly(self, at: str, written: Mapping[str, Any], view: Mapping[str, Any] | None) -> None:
        for key, value in written.items():
            if view is None:
                self.error("readonly", f"{at}.{key}", "read-only fields only appear on existing records")
            elif key not in view:
                self.error("readonly", f"{at}.{key}", f"{key} is not a read-only field of this record")
            elif value != view[key]:
                self.error("readonly", f"{at}.{key}", f"{key} is read-only (currently {view[key]!r})")

    # ── 关系 ──────────────────────────────────────────────────────────

    def edge_props(self, at: str, src: str, rel_type: str, spec: Relationship, edge: DocEdge) -> dict[str, Any]:
        dst = self.r(edge.to)
        current = self.local.edges.get(EdgeKey(src, rel_type, dst))
        props: dict[str, Any] = {}
        for key, value in edge.props.items():
            prop_at = f"{at}.{key}"
            if key in SYSTEM_REL_PROPS:
                self.error("field", prop_at, f"{key} is set by the system")
            elif key not in GENERIC_REL_PROPS | spec.props:
                self.error("field", prop_at, f"{rel_type} has no property {key}")
            elif key == "source_refs":
                props[key] = None if value is None else self.source_refs(prop_at, value)
            elif key == "locators":
                props[key] = value
                if value is not None:
                    self.check_locators(prop_at, dst, value)
            elif key == "role" and value is not None:
                roles = EVALUATES_ROLES if rel_type == "EVALUATES" else USES_ROLES
                if value not in roles:
                    self.error("field", prop_at, f"{rel_type}.role is one of {sorted(roles)}")
                props[key] = value
            elif key == "stated_by" and value is not None and value not in STATED_BY:
                self.error("field", prop_at, f"stated_by is one of {sorted(STATED_BY)}")
            else:
                props[key] = value
        if rel_type == "FROM":
            material = self.material(dst)
            if material is not None:
                props["material_ref"] = material
        if rel_type in STANCE_RELS and current is None and props.get("stated_by") == "agent":
            props["formed_by"] = self.doc.by
            props["formed_at"] = self.ctx.at
        if edge.readonly:
            self.check_readonly(at, edge.readonly, edge_readonly(rel_type, current) if current is not None else None)
        return props

    def source_refs(self, at: str, value: Any) -> list[str]:
        """``<材料 id 或节点引用>::<定位>`` → ``<材料 id>::<定位>``。"""
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            self.error("source-ref", at, "source_refs must be a list of strings")
            return []
        out = []
        for i, source_ref in enumerate(value):
            head, sep, locator = source_ref.partition("::")
            item_at = f"{at}[{i}]"
            if not sep:
                self.error("source-ref", item_at, "write <material or node>::<section>::<start>:<end>")
                continue
            head_node = self.local.nodes.get(head)
            if head_node is not None and "Material" in head_node.labels:
                material = head
            else:
                material = self.material(self.r(head))
                if material is None:
                    self.error("source-ref", item_at, f"{head} is not a material or a node with a material")
                    continue
            self.check_locator(item_at, material, locator)
            out.append(f"{material}::{locator}")
        return out

    def check_locators(self, at: str, dst: str, value: Any) -> None:
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            self.error("locator", at, "locators must be a list of strings")
            return
        material = self.material(dst)
        if material is None:
            self.error("locator", at, f"{dst} has no material to locate in")
            return
        for i, locator in enumerate(value):
            self.check_locator(f"{at}[{i}]", material, locator)

    def check_locator(self, at: str, material: str, locator: str) -> None:
        m = LOCATOR.fullmatch(locator)
        if m is None:
            self.error("locator", at, f"{locator!r} is not <section>::<start>:<end>")
            return
        start, end = int(m["start"]), int(m["end"])
        total = self.material_lines(material)
        if total is None:
            self.error("locator", at, f"material {material} cannot be read")
        elif not 1 <= start <= end <= total:
            self.error("locator", at, f"lines {start}:{end} are outside {material} (1:{total})")

    def material_lines(self, material: str) -> int | None:
        if material not in self.lines:
            path = next((m.path for m in self.materials.values() if m.id == material), None)
            node = self.local.nodes.get(material)
            if path is None and node is not None:
                path = node.props.get("path")
            file = self.ctx.material_root / path if isinstance(path, str) else None
            self.lines[material] = (
                len(file.read_text(encoding="utf-8").splitlines()) if file is not None and file.is_file() else None
            )
        return self.lines[material]

    # ── 材料、标识与名称 ──────────────────────────────────────────────

    def attach_material(self, at: str, node_id: str) -> None:
        material = self.materials.get(node_id)
        if material is None:
            if node_id not in self.materials and not any(p.at == at for p in self.problems):
                self.error("material", at, "material must be a path; it cannot be cleared")
            return
        current = material_of(node_id, self.local)
        if current == material.id:
            return
        if current is not None:
            self.error("material", at, f"changing a paper's material ({current}) is not supported yet")
            return
        existing = self.local.nodes.get(material.id)
        if existing is None:
            props = {"path": material.path, "format": "markdown", "content_hash": material.sha256}
            self.nodes[material.id] = FragmentNode(
                frozenset({"Material"}), props, {"MATERIAL_OF": {node_id: {}}}, new=True
            )
        else:
            owners = [k.dst for k in self.local.edges if k.src == material.id and k.type == "MATERIAL_OF"]
            if owners:
                self.error("material", at, f"{material.path} is already the material of {owners[0]}", tuple(owners))
                return
            self.nodes[material.id] = FragmentNode(rels={"MATERIAL_OF": {node_id: {}}})
        self.files.append(FileRef(material.path, material.sha256))

    def check_identifiers(self, at: str, node_id: str, value: Any) -> None:
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            self.error("identifier", at, "identifiers must be a list of <namespace>:<value> strings")
            return
        for i, identifier in enumerate(value):
            namespace, sep, rest = identifier.partition(":")
            if not sep or not rest or namespace not in NAMESPACES:
                self.error("identifier", f"{at}[{i}]", f"{identifier!r}: namespace must be one of {sorted(NAMESPACES)}")
            elif NAMESPACES[namespace]:
                others = self.ctx.reader.find("identifiers", identifier, label="Entity") - {node_id}
                others -= self.deletes_in_doc()
                if others:
                    self.error(
                        "identifier-taken", f"{at}[{i}]", f"{identifier} already identifies", tuple(sorted(others))
                    )

    def deletes_in_doc(self) -> set[str]:
        return {self.r(ref) for ref, node in self.doc.nodes.items() if node is None}

    def namekeys(self) -> None:
        """名称与别名 → NameKey 节点：新建、改指或删除。"""
        desired: dict[str, dict[str, str]] = {}  # 节点 id → {key: raw}
        for node_id, kind in self.kinds.items():
            if kind in NAMED and node_id in self.nodes:
                desired[node_id] = self.names_of(node_id, kind)

        claimed: dict[str, str] = {}
        for node_id, keys in desired.items():
            for key in keys:
                if key in claimed and claimed[key] != node_id:
                    self.error(
                        "name-taken", f"nodes.{self.ref(node_id)}", f"{keys[key]!r} is also claimed by {claimed[key]}"
                    )
                claimed[key] = node_id

        released = set()
        for node_id in desired:
            released |= self.owned_keys(node_id) - desired[node_id].keys()
        for node_id in self.deletes & set(self.local.nodes):
            released |= self.owned_keys(node_id)

        unknown = [key for key in claimed if key not in self.local.nodes]
        if unknown:
            extra = self.ctx.reader.local_state(unknown)
            self.local = GraphState({**extra.nodes, **self.local.nodes}, {**extra.edges, **self.local.edges})

        for key, owner in claimed.items():
            raw = desired[owner][key]
            if key not in self.local.nodes:
                self.nodes[key] = FragmentNode(
                    frozenset({"NameKey"}),
                    self.namekey_props(key, raw, self.kinds[owner]),
                    {"NAMES": {owner: {}}},
                    True,
                )
                continue
            holders = sorted(k.dst for k in self.local.edges if k.src == key and k.type == "NAMES")
            if holders == [owner]:
                continue
            if key in released or not holders:
                released.discard(key)
                props = {
                    "raw": raw,
                    "status": "active",
                    "registered_by": self.doc.by,
                    "registered_from": self.ctx.source,
                }
                self.nodes[key] = FragmentNode(props=props, rels={"NAMES": {owner: {}}})
            else:
                self.error(
                    "name-taken",
                    f"nodes.{self.ref(owner)}",
                    f"{raw!r} already names {', '.join(holders)}",
                    tuple(holders),
                )
        self.deletes |= released

    def names_of(self, node_id: str, kind: str) -> dict[str, str]:
        doc_props = self.doc.nodes[self.ref(node_id)].props  # type: ignore[union-attr]
        current = self.local.nodes.get(node_id)
        current_name = current.props.get("name") if current is not None else None
        name = doc_props.get("name", current_name)
        if node_id in self.aliases:
            aliases = self.aliases[node_id]
        else:
            owned = [self.local.nodes[k].props.get("raw") for k in sorted(self.owned_keys(node_id))]
            aliases = [raw for raw in owned if isinstance(raw, str) and normalize(raw) != normalize(current_name or "")]
        keys: dict[str, str] = {}
        for raw in ([name] if isinstance(name, str) else []) + aliases:
            keys.setdefault(name_key(raw, kind), raw)
        return keys

    def owned_keys(self, node_id: str) -> set[str]:
        return {k.src for k in self.local.edges if k.dst == node_id and k.type == "NAMES"}

    def namekey_props(self, key: str, raw: str, kind: str) -> dict[str, Any]:
        return {
            "key": key,
            "normalized": normalize(raw),
            "raw": raw,
            "kind": kind,
            "scope": "global",
            "normalizer_ref": NORMALIZER,
            "status": "active",
            "registered_by": self.doc.by,
            "registered_from": self.ctx.source,
        }

    def ref(self, node_id: str) -> str:
        return next((ref for ref in self.doc.nodes if self.r(ref) == node_id), node_id)

    # ── 自然键 ────────────────────────────────────────────────────────

    def derived_keys(self) -> None:
        """自然键：Experiment 的 ``exp_key`` 随主锚点与来源论文更新；
        论文陈述的 Claim、Contribution 新建时生成 ``content_key``，之后不变。"""
        seen: dict[tuple[str, str], str] = {}
        for node_id, kind in self.kinds.items():
            node = self.nodes.get(node_id)
            if node is None:
                continue
            current = self.local.nodes.get(node_id)
            at = f"nodes.{self.ref(node_id)}"
            if kind == "Experiment":
                anchors = node.props.get("anchors", current.props.get("anchors") if current else None)
                paper = self.source_paper(at, node_id)
                if paper is None or not anchors:
                    continue
                key, prop = f"{paper}::{anchors[0]}", "exp_key"
                if current is not None and current.props.get(prop) == key:
                    continue
            elif node.new and (kind == "Claim" or (kind == "Contribution" and node.props.get("stated_by") == "paper")):
                paper = self.source_paper(at, node_id)
                if paper is None:
                    continue
                key, prop = f"{paper}::{kind}::{self.ref(node_id).removeprefix('$')}", "content_key"
            else:
                continue
            node.props[prop] = key
            label = "Experiment" if prop == "exp_key" else "Content"
            others = self.ctx.reader.find(prop, key, label=label) - {node_id} - self.deletes_in_doc()
            if (prop, key) in seen:
                others.add(seen[(prop, key)])
            seen[(prop, key)] = node_id
            if others:
                self.error("key-taken", at, f"{prop} {key} is already used", tuple(sorted(others)))

    def source_paper(self, at: str, node_id: str) -> str | None:
        node = self.nodes[node_id]
        if "FROM" in node.rels:
            targets = list(node.rels["FROM"])
        else:
            targets = [k.dst for k in self.local.edges if k.src == node_id and k.type == "FROM"]
        papers = sorted(t for t in targets if self.kind(t) == "Paper")
        if len(papers) > 1:
            self.error("relationship", f"{at}.FROM", f"comes from more than one paper: {', '.join(papers)}")
            return None
        return papers[0] if papers else None


def _strings(value: Any) -> list[str]:
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


__all__ = ["Context", "Translation", "translate"]
