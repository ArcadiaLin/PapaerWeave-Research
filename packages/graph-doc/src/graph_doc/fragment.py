"""求差层：物理目标状态（:class:`Fragment`）与库中现状比对，得到 graph-vc 的变更集。

:class:`Fragment` 是上层把 graph-doc 翻译到物理图之后的结果：Label、属性与关系都已是库中的写法，
引用都已是真实 id（临时引用先由 :meth:`Fragment.rename` 换掉）。语义与 graph-doc 相同：

- 属性：写了就设置，``None`` 就清除，没写就不动；
- Label：给出时是完整的 Label 集合，``None`` 表示不动；
- 关系：``rels`` 中列出的边，不存在的新建，已存在的按边属性更新（写了就设置、``None`` 就清除、没写就不动）；
  没列出的边不动。要删的边列在 ``edge_deletes`` 中；
- 删除：``deletes`` 中的节点连同它的全部关系一起删除。

动词与现状是否相符（``create`` 的边不能已存在、``set`` 的边必须存在）由上层在翻译时检查，这里只做求差。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from graph_vc import Changeset, EdgeChange, EdgeKey, GraphState, NodeChange
from graph_vc.state import same_value

from .errors import DiffError


@dataclass(frozen=True, slots=True)
class FragmentNode:
    """一个节点的目标状态。``new`` 为真表示新建：库中不能已有该 id，且必须给出 Label。"""

    labels: frozenset[str] | None = None
    props: dict[str, Any] = field(default_factory=dict)
    rels: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)  # 类型 → {终点 id: 边属性}
    new: bool = False
    edge_deletes: frozenset[tuple[str, str]] = frozenset()  # 要删除的出边：(类型, 终点 id)


@dataclass(frozen=True, slots=True)
class Fragment:
    nodes: dict[str, FragmentNode] = field(default_factory=dict)
    deletes: frozenset[str] = frozenset()

    def ids(self) -> set[str]:
        """求差需要的现状范围：传给 ``VersionedGraph.local_state`` 的 id。"""
        targets = {dst for node in self.nodes.values() for edges in node.rels.values() for dst in edges}
        targets |= {dst for node in self.nodes.values() for _, dst in node.edge_deletes}
        return set(self.nodes) | set(self.deletes) | targets

    def rename(self, mapping: Mapping[str, str]) -> Fragment:
        """把 id 按 ``mapping`` 换掉（通常是临时引用到分配的 id），未列出的保持不变。"""

        def r(ref: str) -> str:
            return mapping.get(ref, ref)

        nodes = {
            r(ref): FragmentNode(
                labels=node.labels,
                props=dict(node.props),
                rels={t: {r(dst): dict(p) for dst, p in edges.items()} for t, edges in node.rels.items()},
                new=node.new,
                edge_deletes=frozenset((t, r(dst)) for t, dst in node.edge_deletes),
            )
            for ref, node in self.nodes.items()
        }
        deletes = frozenset(r(ref) for ref in self.deletes)
        if len(nodes) != len(self.nodes) or len(deletes) != len(self.deletes):
            raise ValueError("rename maps two references onto the same id")
        return Fragment(nodes, deletes)


def diff(fragment: Fragment, state: GraphState) -> Changeset:
    """求出把 ``state`` 变成 ``fragment`` 所描述状态的变更集；什么都不用改时返回空变更集。

    ``state`` 至少要包含 :meth:`Fragment.ids` 中已存在的节点，以及这些节点的全部关系
    （``VersionedGraph.local_state(fragment.ids())`` 正是如此）。目标状态本身不可能成立时抛出 :class:`DiffError`。
    变更集只核对到这一层，取值是否可存、Label 是否允许等由 ``Changeset.validate`` 负责。
    """
    problems = _check(fragment, state)
    if problems:
        raise DiffError(problems)

    nodes: list[NodeChange] = []
    edges: dict[EdgeKey, EdgeChange] = {}

    for node_id, node in fragment.nodes.items():
        current = state.nodes.get(node_id)
        if current is None:
            nodes.append(NodeChange.create(node_id, node.labels or (), _present(node.props)))
        else:
            before, after = _prop_changes(node.props, current.props)
            labels_after = current.labels if node.labels is None else node.labels
            if before or labels_after != current.labels:
                nodes.append(NodeChange.update(node_id, current.labels, before, after, labels_after=labels_after))
        for rel_type in sorted(node.rels):
            for change in _rel_changes(node_id, rel_type, node.rels[rel_type], state):
                edges[change.key] = change
        for rel_type, dst in sorted(node.edge_deletes):
            key = EdgeKey(node_id, rel_type, dst)
            edges[key] = EdgeChange(key, dict(state.edges[key]), None)

    for node_id in sorted(fragment.deletes):
        current = state.nodes[node_id]
        nodes.append(NodeChange.delete(node_id, current.labels, current.props))
        for key in sorted(state.incident(node_id), key=str):
            edges.setdefault(key, EdgeChange(key, dict(state.edges[key]), None))

    return Changeset(nodes=tuple(nodes), edges=tuple(edges.values()))


def _check(fragment: Fragment, state: GraphState) -> list[str]:
    problems = []
    for node_id in sorted(fragment.deletes):
        if node_id in fragment.nodes:
            problems.append(f"{node_id}: listed both as a node and as a deletion")
        if node_id not in state.nodes:
            problems.append(f"{node_id}: cannot delete a node that does not exist")
    for node_id, node in fragment.nodes.items():
        exists = node_id in state.nodes
        if node.new and exists:
            problems.append(f"{node_id}: a new node's id already exists")
        if node.new and not node.labels:
            problems.append(f"{node_id}: a new node needs labels")
        if not node.new and not exists:
            problems.append(f"{node_id}: node does not exist")
        for rel_type in sorted(node.rels):
            for dst in sorted(node.rels[rel_type]):
                at = f"{node_id}-[{rel_type}]->{dst}"
                if dst in fragment.deletes:
                    problems.append(f"{at}: the target is deleted in the same fragment")
                elif dst not in state.nodes and not (dst in fragment.nodes and fragment.nodes[dst].new):
                    problems.append(f"{at}: the target does not exist")
        for rel_type, dst in sorted(node.edge_deletes):
            at = f"{node_id}-[{rel_type}]->{dst}"
            if EdgeKey(node_id, rel_type, dst) not in state.edges:
                problems.append(f"{at}: cannot delete an edge that does not exist")
            elif dst in fragment.nodes.get(node_id, FragmentNode()).rels.get(rel_type, {}):
                problems.append(f"{at}: listed both as an edge to write and as a deletion")
    return problems


def _rel_changes(
    src: str, rel_type: str, wanted: Mapping[str, Mapping[str, Any]], state: GraphState
) -> list[EdgeChange]:
    current = {k.dst: props for k, props in state.edges.items() if k.src == src and k.type == rel_type}
    changes = []
    for dst in sorted(wanted):
        if dst not in current:
            changes.append(EdgeChange.create(src, rel_type, dst, _present(wanted[dst])))
            continue
        before, after = _prop_changes(wanted[dst], current[dst])
        if before:
            changes.append(EdgeChange.update(src, rel_type, dst, before, after))
    return changes


def _prop_changes(wanted: Mapping[str, Any], current: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """只列出实际改变的属性：清除一个本来就不存在的属性、写入与现值相同的值都不算改动。"""
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    for key, value in wanted.items():
        old = current.get(key)
        if value is None and old is None:
            continue
        if value is not None and old is not None and same_value(value, old):
            continue
        before[key] = old
        after[key] = value
    return before, after


def _present(props: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in props.items() if v is not None}


__all__ = ["Fragment", "FragmentNode", "diff"]
