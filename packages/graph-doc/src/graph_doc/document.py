"""graph-doc 的语法层：把 YAML 文本解析成 :class:`Document`，检查与数据模型无关的规则。

一份 graph-doc 是对图的一组改动，借用 Cypher 的动词分成三节，一份文件就是一个提交：

- ``graph-doc``：格式版本，必填，``v0.2``；
- ``create``：新建节点与边。键是 ``$`` 名（新节点，下面写字段与出边），或已有 id（只写要新建的出边）；
- ``set``：修改已有节点的字段与已有边的属性。键只能是已有 id；
- ``delete``：键是已有 id。值为空时删除节点及其全部边；值是关系键时只删列出的边；
- ``confirm``：写入时的确认，内容由上层解释。

字段类别看拼写：小写是属性，全大写是从这个节点出发的关系，``_`` 开头是只读字段（写入时忽略）。关系键下是一个映射，
键是终点（id 或 ``$`` 名），值是这条边的属性；边没有属性时可以写成终点的列表。

``$`` 名是本文件内的临时名，只能在 ``create`` 中定义，在本文件任何地方都可以引用；不带 ``$`` 的是库中已有的 id。
同一条边出现在两节中、一个节点被整体删除又出现在别的节中，都是错误。

本模块不认识数据模型：``kind``、``alias``、``paper``、``extra`` 等在这里只是普通属性，由上层翻译。属性值可以是
标量、标量的列表，或一层映射（如 ``extra``），能否存储由上层决定。

YAML 按 1.2 核心模式解析标量：只有 ``null``、``true`` / ``false``、十进制整数与有限浮点数会转换类型，
其余一律是字符串。因此 ``2026-10-04T15:30:00Z``、``yes``、``on``、``52:58`` 都保持为字符串原文。
同一映射中重复的键视为错误，而不是后者覆盖前者。
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import yaml

from .errors import DocError

VERSION = "v0.2"
VERSIONS = frozenset({VERSION})
SECTIONS = ("create", "set", "delete")
TOP_LEVEL = ("graph-doc", *SECTIONS, "confirm")

TEMP_REF = re.compile(r"\$[A-Za-z0-9][A-Za-z0-9_.-]*")
ID_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]*")
PROPERTY = re.compile(r"[a-z][a-z0-9_]*")
RELATIONSHIP = re.compile(r"[A-Z][A-Z0-9_]*")
READONLY = re.compile(r"_[A-Za-z][A-Za-z0-9_]*")


@dataclass(frozen=True, slots=True)
class DocEdge:
    """一条出边。``props`` 中值为 ``None`` 的属性表示清除（只在 ``set`` 中有意义）。"""

    to: str
    props: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DocNode:
    """一个节点在某一节中的内容。``rels``：关系类型 → 终点 → 边。"""

    props: dict[str, Any] = field(default_factory=dict)
    rels: dict[str, dict[str, DocEdge]] = field(default_factory=dict)

    def edges(self) -> list[tuple[str, DocEdge]]:
        return [(rel_type, edge) for rel_type, edges in self.rels.items() for edge in edges.values()]


@dataclass(frozen=True, slots=True)
class Document:
    """``delete`` 中值为 ``None`` 的节点整体删除，否则是要删的边：关系类型 → 终点列表。"""

    version: str
    create: dict[str, DocNode] = field(default_factory=dict)
    set: dict[str, DocNode] = field(default_factory=dict)
    delete: dict[str, dict[str, list[str]] | None] = field(default_factory=dict)
    confirm: dict[str, Any] = field(default_factory=dict)

    def temp_refs(self) -> list[str]:
        return [ref for ref in self.create if is_temp(ref)]

    def deleted_nodes(self) -> list[str]:
        return [ref for ref, rels in self.delete.items() if rels is None]

    def refs(self) -> list[str]:
        """文档中作为节点键出现的全部引用，按出现顺序去重。"""
        return list(dict.fromkeys([*self.create, *self.set, *self.delete]))

    def is_empty(self) -> bool:
        return not (self.create or self.set or self.delete)


def is_temp(ref: str) -> bool:
    return ref.startswith("$")


def parse(text: str) -> Document:
    """解析 graph-doc 文本；不合法时抛出 :class:`DocError`，列出全部问题。"""
    return from_data(load(text))


def load(text: str) -> Any:
    """按本模块的 YAML 规则（1.2 核心标量、禁止重复键）加载文本，不做 graph-doc 检查。"""
    try:
        return yaml.load(text, Loader=_Loader)  # _Loader 继承 SafeLoader，不构造任意对象
    except yaml.MarkedYAMLError as exc:
        mark = exc.problem_mark or exc.context_mark
        where = f"line {mark.line + 1}: " if mark is not None else ""
        raise DocError([f"invalid YAML: {where}{exc.problem or exc}"]) from exc
    except yaml.YAMLError as exc:
        raise DocError([f"invalid YAML: {exc}"]) from exc


def from_data(data: Any) -> Document:
    """从已加载的数据（YAML 或 JSON 解析结果）构造 :class:`Document`。"""
    problems: list[str] = []
    if not isinstance(data, Mapping):
        raise DocError(["a graph-doc must be a mapping"])

    for key in data:
        if key not in TOP_LEVEL:
            hint = " (nodes is v0.1; v0.2 uses create, set and delete)" if key == "nodes" else ""
            problems.append(f"{key}: unknown top-level key; expected one of {', '.join(TOP_LEVEL)}{hint}")

    version = data.get("graph-doc")
    if version is None:
        problems.append(f"graph-doc: the format version is required; write graph-doc: {VERSION}")
    elif not isinstance(version, str) or version not in VERSIONS:
        problems.append(f"graph-doc: unsupported version {version!r}; write graph-doc: {VERSION}")

    create: dict[str, DocNode] = {}
    for ref, value in _mapping(data.get("create"), "create", problems).items():
        at = f"create.{ref}"
        if not _check_ref(ref, at, problems):
            continue
        if not isinstance(value, Mapping):
            problems.append(f"{at}: a node must be a mapping of fields and relationships")
            continue
        node = _node(value, at, problems)
        if not is_temp(ref) and node.props:
            problems.append(
                f"{at}: {ref} already exists; under create an existing id only takes new relationships "
                f"(change its fields under set)"
            )
        create[ref] = node

    sets: dict[str, DocNode] = {}
    for ref, value in _mapping(data.get("set"), "set", problems).items():
        at = f"set.{ref}"
        if not _check_ref(ref, at, problems):
            continue
        if is_temp(ref):
            problems.append(f"{at}: set changes existing nodes; write the fields of a new node under create.{ref}")
            continue
        if not isinstance(value, Mapping):
            problems.append(f"{at}: a node must be a mapping of the fields and relationships to change")
            continue
        sets[ref] = _node(value, at, problems)

    deletes: dict[str, dict[str, list[str]] | None] = {}
    for ref, value in _mapping(data.get("delete"), "delete", problems).items():
        at = f"delete.{ref}"
        if not _check_ref(ref, at, problems):
            continue
        if is_temp(ref):
            problems.append(f"{at}: a $ name is a node created in this file; it cannot be deleted")
            continue
        deletes[ref] = None if value is None else _deleted_edges(value, at, problems)

    confirm = dict(_mapping(data.get("confirm"), "confirm", problems))
    doc = Document(version=version, create=create, set=sets, delete=deletes, confirm=confirm)
    problems += _check_references(doc)
    if problems:
        raise DocError(problems)
    return doc


# ── 节点与边 ──────────────────────────────────────────────────────────


def _node(data: Mapping[Any, Any], where: str, problems: list[str]) -> DocNode:
    node = DocNode()
    for key, value in data.items():
        at = f"{where}.{key}"
        if not isinstance(key, str):
            problems.append(f"{at}: field names must be strings")
        elif READONLY.fullmatch(key):
            continue  # 只读字段：读取结果原样贴回时出现，写入时忽略
        elif RELATIONSHIP.fullmatch(key):
            node.rels[key] = _edges(value, at, problems)
        elif PROPERTY.fullmatch(key):
            if key == "id":
                problems.append(f"{at}: the node's id is its key, not a field")
            elif _check_value(value, at, problems):
                node.props[key] = value
        else:
            problems.append(_bad_field(at))
    return node


def _edges(value: Any, where: str, problems: list[str]) -> dict[str, DocEdge]:
    """``{终点: 属性 | null}``，或终点的列表。"""
    edges: dict[str, DocEdge] = {}
    if isinstance(value, list):
        for i, item in enumerate(value):
            at = f"{where}[{i}]"
            if isinstance(item, Mapping):
                problems.append(f"{at}: write the target as a key: {where.rsplit('.', 1)[-1]}: {{<target>: <properties>}}")
            elif _check_ref(item, at, problems):
                if item in edges:
                    problems.append(f"{at}: {item} appears more than once")
                edges[item] = DocEdge(item)
        return edges
    if not isinstance(value, Mapping):
        problems.append(f"{where}: a mapping from target id (or $ name) to the edge's properties, or a list of targets")
        return edges
    for to, props in value.items():
        at = f"{where}.{to}"
        if not _check_ref(to, at, problems):
            continue
        if props is None:
            edges[to] = DocEdge(to)
        elif isinstance(props, Mapping):
            edge = DocEdge(to)
            for key, v in props.items():
                prop_at = f"{at}.{key}"
                if not isinstance(key, str):
                    problems.append(f"{prop_at}: field names must be strings")
                elif READONLY.fullmatch(key):
                    continue
                elif PROPERTY.fullmatch(key):
                    if key == "to":
                        problems.append(f"{prop_at}: the target is the key {to}; do not write to")
                    elif _check_value(v, prop_at, problems):
                        edge.props[key] = v
                elif RELATIONSHIP.fullmatch(key):
                    problems.append(f"{prop_at}: relationships cannot have relationships")
                else:
                    problems.append(_bad_field(prop_at))
            edges[to] = edge
        else:
            problems.append(f"{at}: the edge's properties must be a mapping (or empty)")
    return edges


def _deleted_edges(value: Any, where: str, problems: list[str]) -> dict[str, list[str]]:
    if not isinstance(value, Mapping):
        problems.append(f"{where}: leave it empty to delete the node, or list relationships: {{TYPE: [targets]}}")
        return {}
    out: dict[str, list[str]] = {}
    for rel_type, targets in value.items():
        at = f"{where}.{rel_type}"
        if not isinstance(rel_type, str) or not RELATIONSHIP.fullmatch(rel_type):
            problems.append(f"{at}: under delete, a node lists only relationship types (UPPERCASE) and their targets")
            continue
        if isinstance(targets, Mapping):
            targets = list(targets)
        if not isinstance(targets, list) or not targets:
            problems.append(f"{at}: a list of the targets whose {rel_type} edges are deleted")
            continue
        out[rel_type] = [t for i, t in enumerate(targets) if _check_ref(t, f"{at}[{i}]", problems)]
    return out


def _check_references(doc: Document) -> list[str]:
    """文档内的一致性：``$`` 名必须在 ``create`` 中定义；被整体删除的节点不能在别处出现；同一条边只在一节中出现。"""
    problems = []
    defined = set(doc.temp_refs())
    deleted = set(doc.deleted_nodes())
    for section, nodes in (("create", doc.create), ("set", doc.set)):
        for ref, node in nodes.items():
            if ref in deleted:
                problems.append(f"{section}.{ref}: {ref} is deleted in this file")
            for rel_type, edge in node.edges():
                at = f"{section}.{ref}.{rel_type}.{edge.to}"
                if is_temp(edge.to) and edge.to not in defined:
                    problems.append(f"{at}: {edge.to} is not defined under create")
                if edge.to in deleted:
                    problems.append(f"{at}: {edge.to} is deleted in this file")
    for ref, rels in doc.delete.items():
        for rel_type, targets in (rels or {}).items():
            for to in targets:
                if is_temp(to):
                    problems.append(f"delete.{ref}.{rel_type}: {to} is created in this file; there is no edge to delete")

    seen: dict[tuple[str, str, str], str] = {}
    edges = [
        (section, ref, rel_type, edge.to)
        for section, nodes in (("create", doc.create), ("set", doc.set))
        for ref, node in nodes.items()
        for rel_type, edge in node.edges()
    ]
    edges += [(
        "delete", ref, rel_type, to) for ref, rels in doc.delete.items() for rel_type, targets in (rels or {}).items() for to in targets
    ]
    for section, ref, rel_type, to in edges:
        key = (ref, rel_type, to)
        if key in seen and seen[key] != section:
            problems.append(f"{section}.{ref}.{rel_type}.{to}: this edge also appears under {seen[key]}")
        seen.setdefault(key, section)
    return problems


# ── 取值与拼写 ────────────────────────────────────────────────────────


def _check_ref(ref: Any, where: str, problems: list[str]) -> bool:
    if isinstance(ref, str) and (TEMP_REF.fullmatch(ref) or ID_REF.fullmatch(ref)):
        return True
    problems.append(f"{where}: {ref!r} is neither an id nor a $ name")
    return False


def _check_value(value: Any, where: str, problems: list[str]) -> bool:
    """属性值：``null``、标量、标量的列表，或一层映射（值为 ``null``、标量或标量的列表）。"""
    if value is None or _scalar(value) or _scalars(value):
        return True
    if isinstance(value, Mapping):
        bad = [k for k, v in value.items() if not isinstance(k, str) or not (v is None or _scalar(v) or _scalars(v))]
        if not bad:
            return True
        problems.append(f"{where}: a mapping value holds scalars or lists of scalars, one level deep")
        return False
    if isinstance(value, list):
        problems.append(f"{where}: a list holds scalars (strings, numbers, booleans)")
        return False
    problems.append(f"{where}: unsupported value of type {type(value).__name__}")
    return False


def _scalar(value: Any) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    return isinstance(value, bool | int | str)


def _scalars(value: Any) -> bool:
    return isinstance(value, list) and all(_scalar(v) for v in value)


def _bad_field(where: str) -> str:
    return f"{where}: field names are lowercase (property), UPPERCASE (relationship), or start with _ (read-only)"


def _mapping(value: Any, where: str, problems: list[str]) -> Mapping[Any, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return value
    problems.append(f"{where}: must be a mapping")
    return {}


# ── YAML：1.2 核心标量，禁止重复键 ─────────────────────────────────────


class _Loader(yaml.SafeLoader):
    yaml_implicit_resolvers: dict[str, list[tuple[str, re.Pattern[str]]]] = {}  # noqa: RUF012 —— PyYAML 的类属性

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        seen: set[Any] = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in seen
            except TypeError:
                raise yaml.constructor.ConstructorError(
                    None, None, f"unhashable key {key!r}", key_node.start_mark
                ) from None
            if duplicate:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping", node.start_mark, f"duplicate key {key!r}", key_node.start_mark
                )
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def _construct_int(loader: _Loader, node: yaml.ScalarNode) -> int:
    return int(loader.construct_scalar(node))


def _construct_float(loader: _Loader, node: yaml.ScalarNode) -> float:
    return float(loader.construct_scalar(node))


_Loader.add_implicit_resolver("tag:yaml.org,2002:null", re.compile(r"^(?:~|null|Null|NULL|)$"), ["~", "n", "N", ""])
_Loader.add_implicit_resolver(
    "tag:yaml.org,2002:bool", re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"), list("tTfF")
)
_Loader.add_implicit_resolver("tag:yaml.org,2002:int", re.compile(r"^[-+]?[0-9]+$"), list("-+0123456789"))
_Loader.add_implicit_resolver(
    "tag:yaml.org,2002:float",
    re.compile(r"^[-+]?(?:\.[0-9]+|[0-9]+(?:\.[0-9]*)?)(?:[eE][-+]?[0-9]+)?$"),
    list("-+.0123456789"),
)
_Loader.add_constructor("tag:yaml.org,2002:int", _construct_int)
_Loader.add_constructor("tag:yaml.org,2002:float", _construct_float)


__all__ = ["SECTIONS", "VERSION", "VERSIONS", "DocEdge", "DocNode", "Document", "from_data", "is_temp", "load", "parse"]
