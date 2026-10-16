"""graph-doc v0.2 → 物理目标状态（:class:`~graph_doc.Fragment`）：数据模型 V3 的写入规则。

翻译只处理“文档写了什么、与现状是否相符”，属性与边的具体改动由 :func:`graph_doc.diff` 求出，写入后的状态是否
合规留给 :mod:`paperweave.commit.checks`。

**动词与现状。** ``create`` 的 ``$`` 名是新节点，已有 id 下只写新边：边已存在时，写到的属性都与现值相同视为无改动，
否则报错并给出现值，提示改用 ``set``。``set`` 的节点与边必须已存在。``delete`` 的节点与边必须已存在。

**字段的物理写法**（docs/designs/v3/data_model.md）：

- ``kind`` → 主 Label、次级 Label 与公共 Label ``Searchable``；``set`` 中写了 kind 必须与现状相同。
- ``name`` 与 ``alias`` → ``(:NameKey)-[:NAMES]->(对象)``；同一文档中从一个对象移到另一个对象的名称改指，而不是删了再建。
- ``extra`` → 一个 JSON 字符串属性；``set`` 中按键合并，键写 ``null`` 即删除。边上的 ``extra`` 相同。
- Content 的 ``paper`` → 指向论文的 ``FROM`` 边，边上记下写入时论文的材料（``material_ref``）。
- 节点与边的 ``anchor`` 是论文 Markdown 的行号范围，写入时按论文的当前材料检查不越界；带锚点的边另记 ``material_ref``。
  边的论文取起点所在的论文（Content 的 ``paper``、Paper 本身），起点是 Entity 或 Concept 时边上另写 ``paper``。
- Paper 的 ``material`` → ``(:Material)-[:MATERIAL_OF]->(Paper)``；换成新文件即为新版本，旧材料留着并记上
  ``superseded_by``，已有的锚点按材料 id 固定在旧版本上。
- 新建的节点与边补上 ``formed_by``、``formed_at``；Experiment 补查重键 ``exp_key``（``<论文 id>::<主表图>``）。
- 桩（``stub: true``）在 ``set`` 中补上 ``description`` 时自动去掉 ``stub``。
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from graph_doc import DocEdge, DocNode, Document, Fragment, FragmentNode, is_temp
from graph_vc import EdgeKey, FileRef, GraphState, NodeState

from ..model.namekey import NORMALIZER, name_key, normalize
from ..model.schema import (
    ANCHOR,
    ARTIFACT,
    CHOICES,
    CONTENT,
    EDGE_FIELDS,
    FIELDS,
    FROM,
    KIND_SPECS,
    LIST_FIELDS,
    NAMED,
    NAMESPACES,
    RELATIONSHIPS,
    ROLES,
    SYSTEM_FIELDS,
    SYSTEM_RELS,
    endpoints,
    kind_of,
    labels_of,
)
from .problems import Problem
from .reader import Reader
from .review import Deduper

_MISSING = object()
_ARXIV_VERSION = re.compile(r"(\d{4}\.\d{4,5})v\d+")


@dataclass(frozen=True, slots=True)
class Context:
    """一次写入的环境：读取现状的入口、来源标签（记入 NameKey.registered_from 与提交的 source）、形成时间、
    材料的根目录、查重的入口（``None`` 表示不查重）。``user`` 是写入者的登录身份，记为 ``formed_by``；
    ``agent`` 是所用的 Agent 与模型，记入提交的 ``meta.agent``。二者由服务端给出，不由写入者声明。"""

    reader: Reader
    source: str
    at: str
    material_root: Path
    user: str | None
    deduper: Deduper | None = None
    agent: str | None = None


@dataclass(frozen=True, slots=True)
class Translation:
    fragment: Fragment
    files: tuple[FileRef, ...]
    local: GraphState  # 求差与检查用的局部现状
    problems: tuple[Problem, ...]
    refs: dict[str, str]  # 节点 id → 文档中的引用，用于问题定位
    added_edges: dict[str, list[tuple[str, str, bool]]]  # 已有节点 id → 本次新加的出边 (类型, 终点, 带锚点)


def translate(doc: Document, ctx: Context, ids: Mapping[str, str] | None = None) -> Translation:
    """翻译 ``doc``。``ids`` 把 ``$`` 名换成分配到的 id；不给时 ``$`` 名原样作 id（dry_run）。"""
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
    names: dict[str, tuple[Any, Any]] = field(default_factory=dict)  # 写了 name 或 alias 的节点 → (name, alias)
    new_materials: dict[str, _Material] = field(default_factory=dict)  # Paper id → 本次登记的材料
    papers: dict[str, str] = field(default_factory=dict)  # 本次新建或改了 paper 的 Content id → 论文 id
    lines: dict[str, int | None] = field(default_factory=dict)  # 材料 id → 行数
    added: dict[str, list[tuple[str, str, bool]]] = field(default_factory=dict)

    def run(self) -> Translation:
        if not self.ctx.user:
            self.error("identity", "", "the writer is unknown: the server was started without PAPERWEAVE_USER")
        if self.doc.is_empty():
            self.error("format", "", "nothing to do: write the changes under create, set or delete")
        self.fetch()
        for ref, node in self.doc.create.items():  # 先登记新节点的 kind：引用可以出现在定义之前
            kind = node.props.get("kind")
            if is_temp(ref) and isinstance(kind, str) and kind in KIND_SPECS:
                self.kinds[self.r(ref)] = kind
        for ref, node in self.doc.create.items():
            if is_temp(ref):
                self.create_node(ref, node)
        for ref, node in self.doc.create.items():
            if not is_temp(ref):
                self.create_edges(ref, node)
        for ref, node in self.doc.set.items():
            self.set_node(ref, node)
        for ref, rels in self.doc.delete.items():
            self.delete(ref, rels)
        self.namekeys()
        self.exp_keys()
        fragment = Fragment(self.nodes, frozenset(self.deletes))
        refs = {self.r(ref): ref for ref in self.doc.refs()}
        return Translation(fragment, tuple(self.files), self.local, tuple(self.problems), refs, self.added)

    # ── 基础 ──────────────────────────────────────────────────────────

    def r(self, ref: str) -> str:
        return self.ids.get(ref, ref)

    def ref(self, node_id: str) -> str:
        return next((ref for ref in self.doc.refs() if self.r(ref) == node_id), node_id)

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

    def frag(self, node_id: str) -> FragmentNode:
        if node_id not in self.nodes:
            self.nodes[node_id] = FragmentNode()
        return self.nodes[node_id]

    # ── 读取现状 ──────────────────────────────────────────────────────

    def fetch(self) -> None:
        """取出文档涉及的局部现状：节点、关系终点、``paper`` 指向的论文，以及要登记的材料。"""
        wanted: set[str] = set()
        for section in (self.doc.create, self.doc.set):
            for ref, node in section.items():
                wanted.add(self.r(ref))
                for _, edge in node.edges():
                    wanted.add(self.r(edge.to))
                    if isinstance(edge.props.get("paper"), str):
                        wanted.add(self.r(edge.props["paper"]))
                if isinstance(node.props.get("paper"), str):
                    wanted.add(self.r(node.props["paper"]))
                path = node.props.get("material")
                if isinstance(path, str):
                    material = self.hash_material(f"{self.section_of(ref)}.{ref}.material", path)
                    if material is not None:
                        self.new_materials[self.r(ref)] = material
                        wanted.add(material.id)
        for ref, rels in self.doc.delete.items():
            wanted.add(self.r(ref))
            wanted.update(self.r(to) for targets in (rels or {}).values() for to in targets)
        self.local = self.ctx.reader.local_state(sorted(wanted))
        # 论文的材料：论文常常只是邻居（局部现状只含它的节点，不含它的 MATERIAL_OF），补取论文的局部现状
        papers = {k.dst for k in self.local.edges if k.type == FROM}
        papers |= {i for i, n in self.local.nodes.items() if "Paper" in n.labels}
        if papers:
            self.merge(self.ctx.reader.local_state(sorted(papers)))

    def merge(self, extra: GraphState) -> None:
        self.local = GraphState({**extra.nodes, **self.local.nodes}, {**extra.edges, **self.local.edges})

    def section_of(self, ref: str) -> str:
        return "create" if ref in self.doc.create else "set"

    def hash_material(self, at: str, path: str) -> _Material | None:
        if Path(path).is_absolute() or ".." in Path(path).parts:
            self.error("material", at, "the material path is relative to the material root, like papers/<id>/paper.md")
            return None
        file = self.ctx.material_root / path
        if not file.is_file():
            self.error("material", at, f"{path} does not exist under the material root")
            return None
        return _Material(path, hashlib.sha256(file.read_bytes()).hexdigest())

    # ── create ────────────────────────────────────────────────────────

    def create_node(self, ref: str, doc_node: DocNode) -> None:
        node_id, at = self.r(ref), f"create.{ref}"
        kind = doc_node.props.get("kind")
        if not isinstance(kind, str) or kind not in KIND_SPECS:
            hint = f"one of {', '.join(KIND_SPECS)}"
            self.error("format", f"{at}.kind", f"a new node needs kind: {hint}" if kind is None else f"unknown kind {kind!r}; {hint}")
            return
        if node_id in self.local.nodes:  # 只在提交时分配的 id 与库中已有冲突时发生
            self.error("reference", at, f"{node_id} already exists")
            return
        self.kinds[node_id] = kind
        props: dict[str, Any] = {"formed_by": self.ctx.user, "formed_at": self.ctx.at}
        for key, value in doc_node.props.items():
            if key != "kind" and value is not None:
                self.node_prop(f"{at}.{key}", node_id, kind, key, value, props, None)
        node = self.frag(node_id)  # paper 已经在上面写进了 FROM
        self.nodes[node_id] = FragmentNode(labels=labels_of(kind), props=props, rels=node.rels, new=True)
        if "anchor" in props:
            self.check_anchor(f"{at}.anchor", self.paper_of(node_id), props["anchor"])
        for rel_type, edge in doc_node.edges():
            self.edge(f"{at}.{rel_type}.{edge.to}", node_id, rel_type, edge, "create")

    def create_edges(self, ref: str, doc_node: DocNode) -> None:
        node_id, at = self.r(ref), f"create.{ref}"
        if not self.exists(at, ref, "create"):
            return
        for rel_type, edge in doc_node.edges():
            self.edge(f"{at}.{rel_type}.{edge.to}", node_id, rel_type, edge, "create")

    def exists(self, at: str, ref: str, verb: str) -> bool:
        node = self.local.nodes.get(self.r(ref))
        if node is None:
            hint = " (to make a new node, give it a $ name under create)" if verb != "delete" else ""
            self.error("reference", at, f"{ref} does not exist{hint}")
            return False
        if kind_of(node.labels) is None:
            what = "an artifact (edit it as a document and commit the file)" if ARTIFACT in node.labels else "a system record"
            self.error("readonly", at, f"{ref} is {what}; graph-doc cannot change it")
            return False
        return True

    # ── set ───────────────────────────────────────────────────────────

    def set_node(self, ref: str, doc_node: DocNode) -> None:
        node_id, at = self.r(ref), f"set.{ref}"
        if not self.exists(at, ref, "set"):
            return
        current = self.local.nodes[node_id]
        kind = kind_of(current.labels)
        assert kind is not None
        self.kinds[node_id] = kind
        written = doc_node.props.get("kind", _MISSING)
        if written is not _MISSING and written != kind:
            self.error("format", f"{at}.kind", f"{ref} is a {kind}; kind cannot be changed (create a new node instead)")
        props: dict[str, Any] = {}
        for key, value in doc_node.props.items():
            if key != "kind":
                self.node_prop(f"{at}.{key}", node_id, kind, key, value, props, current)
        if current.props.get("stub") is True and "stub" not in doc_node.props and props.get("description"):
            props["stub"] = None  # 补全桩
        if props:
            self.frag(node_id).props.update(props)
        if kind in CONTENT and ("anchor" in props or node_id in self.papers):
            anchor = props.get("anchor") or current.props.get("anchor") or []
            self.check_anchor(f"{at}.anchor", self.paper_of(node_id), anchor)
        for rel_type, edge in doc_node.edges():
            self.edge(f"{at}.{rel_type}.{edge.to}", node_id, rel_type, edge, "set")

    # ── delete ────────────────────────────────────────────────────────

    def delete(self, ref: str, rels: dict[str, list[str]] | None) -> None:
        node_id, at = self.r(ref), f"delete.{ref}"
        if not self.exists(at, ref, "delete"):
            return
        self.kinds.setdefault(node_id, kind_of(self.local.nodes[node_id].labels) or "")
        if rels is None:
            if node_id in self.nodes:
                self.error("format", at, f"{ref} is deleted and also changed in this file")
            self.deletes.add(node_id)
            return
        removed = set()
        for rel_type, targets in rels.items():
            for to in targets:
                edge_at = f"{at}.{rel_type}.{to}"
                if rel_type in SYSTEM_RELS:
                    hint = " (change the record's paper with set instead)" if rel_type == FROM else ""
                    self.error("relationship", edge_at, f"{rel_type} is maintained by the system{hint}")
                elif EdgeKey(node_id, rel_type, self.r(to)) not in self.local.edges:
                    self.error("reference", edge_at, f"there is no {rel_type} edge from {ref} to {to}")
                else:
                    removed.add((rel_type, self.r(to)))
        if removed:
            node = self.frag(node_id)
            self.nodes[node_id] = FragmentNode(node.labels, node.props, node.rels, node.new, node.edge_deletes | removed)

    # ── 节点字段 ──────────────────────────────────────────────────────

    def node_prop(
        self, at: str, node_id: str, kind: str, key: str, value: Any, props: dict[str, Any], current: NodeState | None
    ) -> None:
        if key in SYSTEM_FIELDS:
            self.error("field", at, f"{key} is set by the system")
            return
        if key not in FIELDS[kind]:
            self.error("field", at, f"{kind} has no field {key}; {self.fields_hint(kind)}")
            return
        if value is None:
            self.clear(at, node_id, kind, key, props, current)
            return
        if key in LIST_FIELDS and isinstance(value, str):
            value = [value]  # 只有一项时写成了标量
        if key == "name":
            if not (isinstance(value, str) and normalize(value)):
                self.error("field", at, "name must be a non-empty string")
                return
            self.names[node_id] = (value, self.names.get(node_id, (_MISSING, _MISSING))[1])
            props[key] = value
        elif key == "alias":
            if not (isinstance(value, list) and all(isinstance(a, str) and normalize(a) for a in value)):
                self.error("field", at, "alias is a list of names")
                return
            self.names[node_id] = (self.names.get(node_id, (_MISSING, _MISSING))[0], value)
        elif key == "identities":
            self.identities(at, node_id, value)
            props[key] = value
        elif key == "extra":
            if not isinstance(value, Mapping):
                self.error("field", at, "extra is a mapping of keys to values, written as a block")
                return
            props[key] = merge_extra(current.props.get("extra") if current else None, value)
        elif key == "material":
            self.attach_material(at, node_id)
        elif key == "paper":
            self.set_paper(at, node_id, value, current)
        elif key in ("anchor", "figures"):
            if not (isinstance(value, list) and value and all(isinstance(v, str) for v in value)):
                self.error("field", at, f"{key} is a non-empty list")
                return
            props[key] = value
        elif key == "stub":
            if value is not True:
                self.error("field", at, "stub is true, or null to clear it")
                return
            if not KIND_SPECS[kind].stub:
                self.error("field", at, f"a {kind} cannot be a stub")
                return
            props[key] = True
        elif key == "year":
            if not isinstance(value, int) or isinstance(value, bool):
                self.error("field", at, "year is a number such as 2024")
                return
            props[key] = value
        elif key == "description":
            if not isinstance(value, str) or not value.strip():
                self.error("field", at, "description is text; write it as a block (description: |)")
                return
            props[key] = value.strip()
        else:
            props[key] = value

    def clear(self, at: str, node_id: str, kind: str, key: str, props: dict[str, Any], current: NodeState | None) -> None:
        if current is None:
            return  # 新节点上写 null：等于没写
        if key in ("paper", "material"):
            self.error("field", at, f"{key} cannot be cleared")
        elif key == "name":
            self.error("field", at, "name cannot be cleared")
        elif key == "alias":
            self.names[node_id] = (self.names.get(node_id, (_MISSING, _MISSING))[0], [])
        else:
            props[key] = None

    def fields_hint(self, kind: str) -> str:
        fields = sorted(FIELDS[kind])
        return f"its fields are {', '.join(fields)}; put other details under extra"

    def identities(self, at: str, node_id: str, value: Any) -> None:
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            self.error("identity", at, "identities is a list of <namespace>:<value>, like arxiv:2211.14730")
            return
        for i, identity in enumerate(value):
            namespace, sep, rest = identity.partition(":")
            if not sep or not rest or namespace not in NAMESPACES:
                self.error("identity", f"{at}[{i}]", f"{identity!r}: the namespace is one of {', '.join(NAMESPACES)}")
            elif namespace == "arxiv" and (bare := _ARXIV_VERSION.fullmatch(rest)):
                msg = f"write the arXiv id without its version: arxiv:{bare[1]} (the version is the paper's material)"
                self.error("identity", f"{at}[{i}]", msg)
            elif NAMESPACES[namespace]:
                others = self.ctx.reader.find("identities", identity, label="Entity") - {node_id} - self.deleted()
                if others:
                    self.error("identity-taken", f"{at}[{i}]", f"{identity} already identifies {', '.join(sorted(others))}", tuple(sorted(others)))

    def deleted(self) -> set[str]:
        return {self.r(ref) for ref in self.doc.deleted_nodes()}

    # ── 论文、材料与锚点 ──────────────────────────────────────────────

    def set_paper(self, at: str, node_id: str, value: Any, current: NodeState | None) -> None:
        if not isinstance(value, str):
            self.error("field", at, "paper is the id of the paper (or its $ name in this file)")
            return
        paper = self.r(value)
        if self.kind(paper) != "Paper":
            what = "does not exist" if self.kind(paper) is None else f"is a {self.kind(paper)}"
            self.error("reference", at, f"paper must be a Paper; {value} {what}")
            return
        old = self.paper_of(node_id) if current is not None else None
        if old == paper:
            return
        node = self.frag(node_id)
        node.rels.setdefault(FROM, {})[paper] = self.material_ref(paper)
        self.papers[node_id] = paper
        if old is not None:
            self.nodes[node_id] = FragmentNode(node.labels, node.props, node.rels, node.new, node.edge_deletes | {(FROM, old)})

    def paper_of(self, node_id: str) -> str | None:
        """Content 写入后的论文：本次写了 ``paper`` 的取它，否则取现有的 ``FROM``。"""
        if node_id in self.papers:
            return self.papers[node_id]
        papers = sorted(k.dst for k in self.local.edges if k.src == node_id and k.type == FROM)
        return papers[0] if papers else None

    def material(self, paper: str) -> str | None:
        if paper in self.new_materials:
            return self.new_materials[paper].id
        owners = sorted(
            k.src
            for k in self.local.edges
            if k.dst == paper
            and k.type == "MATERIAL_OF"
            and not (k.src in self.local.nodes and self.local.nodes[k.src].props.get("superseded_by"))
        )
        return owners[0] if owners else None

    def material_ref(self, paper: str) -> dict[str, Any]:
        material = self.material(paper)
        return {"material_ref": material} if material else {}

    def attach_material(self, at: str, node_id: str) -> None:
        material = self.new_materials.get(node_id)
        if material is None:
            return  # 路径有误，已在 fetch 中报告
        owners = sorted(
            k.src
            for k in self.local.edges
            if k.dst == node_id
            and k.type == "MATERIAL_OF"
            and not (k.src in self.local.nodes and self.local.nodes[k.src].props.get("superseded_by"))
        )
        current = owners[0] if owners else None
        if current == material.id:
            return
        if current is not None:  # 新版本：旧材料留着，标出被谁取代
            self.nodes[current] = FragmentNode(props={"superseded_by": material.id})
        existing = self.local.nodes.get(material.id)
        if existing is None:
            props = {"path": material.path, "format": "markdown", "content_hash": material.sha256}
            self.nodes[material.id] = FragmentNode(
                frozenset({"Material"}), props, {"MATERIAL_OF": {node_id: {}}}, new=True
            )
        else:
            taken = [k.dst for k in self.local.edges if k.src == material.id and k.type == "MATERIAL_OF"]
            if taken:
                self.error("material", at, f"{material.path} is already the material of {taken[0]}", tuple(taken))
                return
            self.nodes[material.id] = FragmentNode(rels={"MATERIAL_OF": {node_id: {}}})
        self.files.append(FileRef(material.path, material.sha256))

    def check_anchor(self, at: str, paper: str | None, value: list[str]) -> None:
        """锚点的格式，以及在论文当前材料中不越界。"""
        if paper is None:
            return  # 没有论文：由必填检查或边的 paper 规则报告
        material = self.material(paper)
        if material is None:
            self.error(
                "anchor",
                at,
                f"{self.ref(paper)} has no material to anchor in: give the Paper material: <path of the paper's Markdown "
                "file, as you read it, e.g. papers/2211.14730v2/paper.md> (a stub paper has no text)",
            )
            return
        total = self.material_lines(material)
        for i, anchor in enumerate(value):
            m = ANCHOR.fullmatch(anchor.strip()) if isinstance(anchor, str) else None
            item_at = f"{at}[{i}]"
            if m is None:
                self.error("anchor", item_at, f"{anchor!r} is not <start>:<end>, the paper's line numbers like 120:135")
            elif total is None:
                self.error("anchor", item_at, f"material {material} cannot be read")
            elif not 1 <= int(m["start"]) <= int(m["end"]) <= total:
                self.error("anchor", item_at, f"lines {anchor} are outside the paper (1:{total})")

    def material_lines(self, material: str) -> int | None:
        if material not in self.lines:
            path = next((m.path for m in self.new_materials.values() if m.id == material), None)
            node = self.local.nodes.get(material)
            if path is None and node is not None:
                path = node.props.get("path")
            file = self.ctx.material_root / path if isinstance(path, str) else None
            self.lines[material] = (
                len(file.read_text(encoding="utf-8").splitlines()) if file is not None and file.is_file() else None
            )
        return self.lines[material]

    # ── 边 ────────────────────────────────────────────────────────────

    def edge(self, at: str, src: str, rel_type: str, edge: DocEdge, verb: str) -> None:
        spec = RELATIONSHIPS.get(rel_type)
        if spec is None:
            if rel_type in SYSTEM_RELS:
                hint = "; write the record's paper field instead" if rel_type == FROM else ""
                self.error("relationship", at, f"{rel_type} is maintained by the system{hint}")
            else:
                self.error("relationship", at, f"{rel_type} is not a relationship type; use RELATES_TO with a description")
            return
        dst = self.r(edge.to)
        if self.kind(dst) is None and dst not in self.kinds:
            hint = "" if is_temp(edge.to) else " (ids come from search or get; new nodes need a $ name under create)"
            self.error("reference", at, f"{edge.to} does not exist{hint}")
            return
        src_kind, dst_kind = self.kind(src), self.kind(dst)
        if not any(src_kind in srcs and dst_kind in dsts for srcs, dsts in spec.ends):
            fits = [t for t, s in RELATIONSHIPS.items() if any(src_kind in a and dst_kind in b for a, b in s.ends)]
            hint = f"; types from {src_kind} to {dst_kind}: {', '.join(fits)}" if fits else ""
            self.error("endpoint", at, f"{rel_type} goes {endpoints(rel_type)}, not {src_kind} → {dst_kind}{hint}")
            return
        key = EdgeKey(src, rel_type, dst)
        current = self.local.edges.get(key)
        props: dict[str, Any] = {}
        for name, value in edge.props.items():
            self.edge_prop(f"{at}.{name}", src, rel_type, name, value, props, current, edge)
        if verb == "create":
            if current is not None:
                differ = {
                    k: current.get(k) for k, v in props.items() if k in edge.props and k != "extra" and v != current.get(k)
                }
                if "extra" in props and props["extra"] != current.get("extra"):
                    differ["extra"] = current.get("extra")
                if differ:
                    shown = ", ".join(f"{k}: {v!r}" for k, v in differ.items())
                    self.error("exists", at, f"this {rel_type} edge already exists ({shown}); to change it, write it under set")
                return
            if not self.nodes.get(src, FragmentNode()).new:
                self.added.setdefault(src, []).append((rel_type, dst, bool(props.get("anchor"))))
            props |= {"formed_by": self.ctx.user, "formed_at": self.ctx.at}
        elif current is None:
            self.error("reference", at, f"there is no {rel_type} edge from {self.ref(src)} to {edge.to}; to add one, write it under create")
            return
        if not props and verb == "set":
            return
        self.frag(src).rels.setdefault(rel_type, {})[dst] = props

    def edge_prop(
        self,
        at: str,
        src: str,
        rel_type: str,
        name: str,
        value: Any,
        props: dict[str, Any],
        current: dict[str, Any] | None,
        edge: DocEdge,
    ) -> None:
        spec = RELATIONSHIPS[rel_type]
        allowed = (*EDGE_FIELDS, *spec.props)
        if name not in allowed:
            self.error("field", at, f"{rel_type} has no property {name}; its properties are {', '.join(allowed)}")
            return
        if value is None:
            if current is not None and name in current:
                props[name] = None
            return
        if name == "role":
            roles = ROLES[rel_type]
            values = value if isinstance(value, list) else [value]
            if not values or not all(v in roles for v in values):
                self.error("field", at, f"{rel_type}.role is one of {', '.join(roles)} (a list when it plays two roles)")
                return
        elif (rel_type, name) in CHOICES and value not in CHOICES[(rel_type, name)]:
            self.error("field", at, f"{rel_type}.{name} is one of {', '.join(CHOICES[(rel_type, name)])}")
            return
        elif name == "extra":
            if not isinstance(value, Mapping):
                self.error("field", at, "extra is a mapping, written as a block")
                return
            value = merge_extra(current.get("extra") if current else None, value)
        elif name == "description":
            if not isinstance(value, str) or not value.strip():
                self.error("field", at, "description is text; write it as a block (description: |)")
                return
            value = value.strip()
        elif name == "paper":
            if self.kind(src) in CONTENT | {"Paper"}:
                self.error("field", at, "the anchor's paper is the record's own paper here; do not write paper on this edge")
                return
            if not isinstance(value, str) or self.kind(self.r(value)) != "Paper":
                self.error("reference", at, "paper is the id of the paper the anchor lines are in")
                return
            value = self.r(value)
        elif name == "anchor":
            if isinstance(value, str):
                value = [value]
            if not (isinstance(value, list) and value and all(isinstance(v, str) for v in value)):
                self.error("field", at, "anchor is a list of line ranges like [120:135]")
                return
            paper = self.edge_paper(src, edge, current)
            if paper is None:
                self.error("anchor", at, "say which paper these lines are in: add paper: <paper id> to this edge")
                return
            self.check_anchor(at, paper, value)
            props.update(self.material_ref(paper))
        elif name == "printed_as" and not isinstance(value, str):
            self.error("field", at, "printed_as is the name as printed in the paper")
            return
        props[name] = value

    def edge_paper(self, src: str, edge: DocEdge, current: dict[str, Any] | None) -> str | None:
        kind = self.kind(src)
        if kind == "Paper":
            return src
        if kind in CONTENT:
            return self.paper_of(src)
        written = edge.props.get("paper")
        if isinstance(written, str):
            return self.r(written)
        return current.get("paper") if current else None

    # ── 名称与查重键 ──────────────────────────────────────────────────

    def namekeys(self) -> None:
        """名称与别名 → NameKey 节点：新建、改指或删除。"""
        desired: dict[str, dict[str, str]] = {}  # 节点 id → {key: raw}
        for node_id, (name, alias) in self.names.items():
            kind = self.kinds.get(node_id)
            if kind in NAMED:
                desired[node_id] = self.names_of(node_id, kind, name, alias)
        for node_id in self.nodes:
            kind = self.kinds.get(node_id)
            if self.nodes[node_id].new and kind in NAMED and node_id not in desired:
                desired[node_id] = {}

        claimed: dict[str, str] = {}
        for node_id, keys in desired.items():
            for key, raw in keys.items():
                if key in claimed and claimed[key] != node_id:
                    self.error("name-taken", f"create.{self.ref(node_id)}", f"{raw!r} is also claimed by {self.ref(claimed[key])}")
                claimed[key] = node_id

        released: set[str] = set()
        for node_id in desired:
            released |= self.owned_keys(node_id) - desired[node_id].keys()
        for node_id in self.deletes & set(self.local.nodes):
            released |= self.owned_keys(node_id)

        unknown = [key for key in claimed if key not in self.local.nodes]
        if unknown:
            self.merge(self.ctx.reader.local_state(unknown))

        for key, owner in claimed.items():
            raw = desired[owner][key]
            at = f"{self.section_of(self.ref(owner))}.{self.ref(owner)}"
            if key not in self.local.nodes:
                props = {
                    "key": key,
                    "normalized": normalize(raw),
                    "raw": raw,
                    "kind": self.kinds[owner],
                    "normalizer_ref": NORMALIZER,
                    "registered_by": self.ctx.user,
                    "registered_from": self.ctx.source,
                }
                self.nodes[key] = FragmentNode(frozenset({"NameKey"}), props, {"NAMES": {owner: {}}}, True)
                continue
            holders = sorted(k.dst for k in self.local.edges if k.src == key and k.type == "NAMES")
            if holders == [owner]:
                continue
            if key in released or not holders:
                released.discard(key)
                props = {"raw": raw, "registered_by": self.ctx.user, "registered_from": self.ctx.source}
                moved = frozenset(("NAMES", holder) for holder in holders)  # 从别的节点移过来：删掉旧的 NAMES
                self.nodes[key] = FragmentNode(props=props, rels={"NAMES": {owner: {}}}, edge_deletes=moved)
            else:
                holder = holders[0]
                name = self.local.nodes[holder].props.get("name", holder) if holder in self.local.nodes else holder
                self.error("name-taken", at, f"{raw!r} already names {holder} ({name})", tuple(holders))
        self.deletes |= released

    def names_of(self, node_id: str, kind: str, name: Any, alias: Any) -> dict[str, str]:
        current = self.local.nodes.get(node_id)
        current_name = current.props.get("name") if current is not None else None
        if name is _MISSING:
            name = current_name
        if alias is _MISSING:
            owned = [self.local.nodes[k].props.get("raw") for k in sorted(self.owned_keys(node_id)) if k in self.local.nodes]
            alias = [raw for raw in owned if isinstance(raw, str) and normalize(raw) != normalize(current_name or "")]
        keys: dict[str, str] = {}
        for raw in ([name] if isinstance(name, str) else []) + list(alias):
            keys.setdefault(name_key(raw, kind), raw)
        return keys

    def owned_keys(self, node_id: str) -> set[str]:
        return {k.src for k in self.local.edges if k.dst == node_id and k.type == "NAMES"}

    def exp_keys(self) -> None:
        """Experiment 的查重键 ``<论文 id>::<主表图>``，随论文与主表图更新。"""
        seen: dict[str, str] = {}
        for node_id, node in self.nodes.items():
            if self.kinds.get(node_id) != "Experiment":
                continue
            current = self.local.nodes.get(node_id)
            figures = node.props.get("figures", current.props.get("figures") if current else None)
            paper = self.paper_of(node_id)
            key = f"{paper}::{figures[0]}" if figures and paper else None
            if current is not None and current.props.get("exp_key") == key:
                continue
            node.props["exp_key"] = key
            if key is None:
                continue
            at = f"{self.section_of(self.ref(node_id))}.{self.ref(node_id)}.figures"
            others = self.ctx.reader.find("exp_key", key, label="Experiment") - {node_id} - self.deleted()
            if key in seen:
                others.add(seen[key])
            seen[key] = node_id
            if others:
                self.error("exp-taken", at, f"this paper's experiment on {figures[0]} is already recorded", tuple(sorted(others)))


def merge_extra(current: Any, written: Mapping[str, Any]) -> str | None:
    """``extra`` 按键合并：写到的键覆盖，写 ``null`` 的键删除。存为 JSON 字符串；合并后为空时为 ``None``。"""
    base = json.loads(current) if isinstance(current, str) else {}
    for key, value in written.items():
        if value is None:
            base.pop(key, None)
        else:
            base[key] = value
    return json.dumps(base, ensure_ascii=False, sort_keys=True) if base else None


def extra_of(props: Mapping[str, Any]) -> dict[str, Any]:
    """节点或边上存储的 ``extra``（JSON 字符串）→ 映射。"""
    value = props.get("extra")
    return json.loads(value) if isinstance(value, str) else {}


__all__ = ["Context", "Translation", "extra_of", "merge_extra", "translate"]
