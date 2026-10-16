"""求差层：目标状态与现状比对得到变更集。内存状态，不需要数据库。"""

from __future__ import annotations

import pytest

from graph_doc import DiffError, Fragment, FragmentNode, diff
from graph_vc import Changeset, EdgeChange, EdgeKey, GraphState, NodeChange, NodeState

M = frozenset({"Concept", "Method"})
E = frozenset({"Content", "Experiment"})


def state() -> GraphState:
    return GraphState(
        nodes={
            "method_0016": NodeState(M, {"name": "DLinear", "note": "old"}),
            "method_0004": NodeState(M, {"name": "Transformer forecasting"}),
            "method_0005": NodeState(M, {"name": "FEDformer"}),
            "exp_0001": NodeState(E, {"text": "…", "anchors": ["S5.T2"]}),
        },
        edges={
            EdgeKey("exp_0001", "EVALUATES", "method_0016"): {"role": "target", "note": "n"},
            EdgeKey("exp_0001", "EVALUATES", "method_0005"): {"role": "baseline"},
            EdgeKey("exp_0001", "USES", "method_0004"): {},
            EdgeKey("method_0016", "BROADER", "method_0004"): {},
        },
    )


def check(fragment: Fragment, before: GraphState | None = None) -> Changeset:
    """求差，并确认：变更集能在现状上执行、可以逆向回去；在新状态上重述目标状态不再产生改动。"""
    before = before or state()
    cs = diff(fragment, before)
    cs.validate()
    after = before.apply(cs)
    assert after.apply(cs.invert()) == before
    restated = Fragment({ref: FragmentNode(node.labels, node.props, node.rels) for ref, node in fragment.nodes.items()
                         if ref not in fragment.deletes})
    assert not diff(restated, after), "restating the target on the new state must change nothing"
    return cs


def test_restating_current_values_changes_nothing() -> None:
    fragment = Fragment(
        {
            "method_0016": FragmentNode(labels=M, props={"name": "DLinear", "missing": None}),
            "exp_0001": FragmentNode(
                props={"anchors": ["S5.T2"]},
                rels={"EVALUATES": {"method_0016": {"role": "target"}, "method_0005": {}}},
            ),
        }
    )
    assert not diff(fragment, state())


def test_properties_are_set_cleared_or_left_alone() -> None:
    cs = check(Fragment({"method_0016": FragmentNode(props={"note": None, "year": 2023, "name": "DLinear"})}))
    assert cs.nodes == (
        NodeChange.update("method_0016", M, {"note": "old", "year": None}, {"note": None, "year": 2023}),
    )
    assert cs.edges == ()


def test_labels_are_replaced_as_a_whole() -> None:
    cs = check(Fragment({"method_0016": FragmentNode(labels=frozenset({"Concept", "Task"}))}))
    assert cs.nodes == (NodeChange.update("method_0016", M, {}, {}, labels_after={"Concept", "Task"}),)


def test_listed_edges_are_upserted_and_deletions_are_explicit() -> None:
    fragment = Fragment(
        {
            "exp_0001": FragmentNode(
                rels={
                    "EVALUATES": {
                        "method_0016": {"role": "baseline"},  # 改一个边属性，note 没写：不动
                        "method_0004": {"role": "baseline", "note": None},  # 新边，None 的属性不写入
                    },
                    # method_0005 没列出：不动；USES 没写：不动
                }
            ),
            "method_0016": FragmentNode(edge_deletes=frozenset({("BROADER", "method_0004")})),
        }
    )
    cs = check(fragment)
    assert cs.nodes == ()
    assert sorted(cs.edges, key=lambda e: str(e.key)) == [
        EdgeChange.create("exp_0001", "EVALUATES", "method_0004", {"role": "baseline"}),
        EdgeChange.update("exp_0001", "EVALUATES", "method_0016", {"role": "target"}, {"role": "baseline"}),
        EdgeChange.delete("method_0016", "BROADER", "method_0004"),
    ]


def test_new_nodes_and_edges_between_them() -> None:
    fragment = Fragment(
        {
            "method_0022": FragmentNode(
                labels=M, props={"name": "PatchTST", "note": None}, rels={"BROADER": {"method_0004": {}}}, new=True
            ),
            "exp_0002": FragmentNode(
                labels=E, props={"text": "…"}, rels={"EVALUATES": {"method_0022": {"role": "target"}}}, new=True
            ),
        }
    )
    cs = check(fragment)
    assert cs.nodes == (
        NodeChange.create("method_0022", M, {"name": "PatchTST"}),
        NodeChange.create("exp_0002", E, {"text": "…"}),
    )
    assert {str(e.key) for e in cs.edges} == {
        "method_0022-[BROADER]->method_0004",
        "exp_0002-[EVALUATES]->method_0022",
    }


def test_delete_removes_every_relationship_once() -> None:
    fragment = Fragment(
        {"method_0016": FragmentNode(edge_deletes=frozenset({("BROADER", "method_0004")}))},  # 也因删除 method_0004 而删除，只列一次
        deletes=frozenset({"method_0004"}),
    )
    cs = check(fragment)
    assert cs.nodes == (NodeChange.delete("method_0004", M, {"name": "Transformer forecasting"}),)
    assert sorted(str(e.key) for e in cs.edges) == [
        "exp_0001-[USES]->method_0004",
        "method_0016-[BROADER]->method_0004",
    ]
    assert all(e.op == "delete" for e in cs.edges)


def test_merge_by_composition() -> None:
    """W6：把 method_0005 并入 method_0016——边改指到保留的节点，再删除被并入的节点。"""
    fragment = Fragment(
        {
            "exp_0001": FragmentNode(
                rels={"EVALUATES": {"method_0016": {"role": "target"}, "method_0004": {"role": "baseline"}}}
            )
        },
        deletes=frozenset({"method_0005"}),
    )
    after = state().apply(check(fragment))
    assert "method_0005" not in after.nodes
    assert after.edges[EdgeKey("exp_0001", "EVALUATES", "method_0004")] == {"role": "baseline"}


@pytest.mark.parametrize(
    ("fragment", "fragment_problem"),
    [
        (Fragment({"method_0016": FragmentNode(labels=M, new=True)}), "a new node's id already exists"),
        (Fragment({"method_0099": FragmentNode(new=True)}), "a new node needs labels"),
        (Fragment({"method_0099": FragmentNode(props={"a": 1})}), "method_0099: node does not exist"),
        (Fragment(deletes=frozenset({"method_0099"})), "cannot delete a node that does not exist"),
        (
            Fragment({"method_0004": FragmentNode()}, deletes=frozenset({"method_0004"})),
            "listed both as a node and as a deletion",
        ),
        (
            Fragment({"method_0016": FragmentNode(rels={"BROADER": {"method_0005": {}}})}, frozenset({"method_0005"})),
            "the target is deleted in the same fragment",
        ),
        (
            Fragment({"method_0016": FragmentNode(rels={"BROADER": {"method_0099": {}}})}),
            "the target does not exist",
        ),
        (
            Fragment({"method_0016": FragmentNode(edge_deletes=frozenset({("BROADER", "method_0005")}))}),
            "cannot delete an edge that does not exist",
        ),
    ],
)
def test_impossible_targets_are_rejected(fragment: Fragment, fragment_problem: str) -> None:
    with pytest.raises(DiffError) as err:
        diff(fragment, state())
    assert any(fragment_problem in p for p in err.value.problems), err.value.problems


def test_ids_and_rename() -> None:
    fragment = Fragment(
        {
            "$patchtst": FragmentNode(labels=M, rels={"BROADER": {"method_0004": {}}}, new=True),
            "$exp": FragmentNode(labels=E, rels={"EVALUATES": {"$patchtst": {"role": "target"}}}, new=True),
        },
        deletes=frozenset({"method_0005"}),
    )
    assert fragment.ids() == {"$patchtst", "$exp", "method_0004", "method_0005"}

    renamed = fragment.rename({"$patchtst": "method_0022", "$exp": "exp_0002"})
    assert set(renamed.nodes) == {"method_0022", "exp_0002"}
    assert renamed.nodes["exp_0002"].rels == {"EVALUATES": {"method_0022": {"role": "target"}}}
    assert renamed.deletes == {"method_0005"}
    assert fragment.nodes["$exp"].rels == {"EVALUATES": {"$patchtst": {"role": "target"}}}

    with pytest.raises(ValueError):
        fragment.rename({"$patchtst": "x", "$exp": "x"})
