"""查重与 confirm、删除影响面，以及返回给 Agent 的 graph-plan / graph-result。不需要数据库。"""

from __future__ import annotations

from conftest import DLINEAR, MemoryGraph, doc, with_confirm

from paperweave.commit import Candidate, Lookup, MemoryReader, plan, result
from paperweave.model.schema import kind_of
from graph_vc import Changeset, CommitRecord


class NeighbourDeduper:
    """模仿没有阈值的向量通道：库中同 kind 的对象都作为候选返回。"""

    def __init__(self, graph: MemoryGraph, errors: tuple[str, ...] = ()):
        self.graph = graph
        self.errors = errors
        self.calls: list[tuple[str, str | None, bool]] = []

    def lookup(self, kind, *, name, identifier, text, stub) -> Lookup:
        self.calls.append((kind, name, stub))
        same = sorted(i for i, n in self.graph.state.nodes.items() if kind_of(n.labels) == kind)
        return Lookup(tuple(Candidate(i, ("semantic",)) for i in same), self.errors)


def test_new_concepts_with_unjudged_candidates_are_blocked(graph: MemoryGraph) -> None:
    graph.deduper = NeighbourDeduper(graph)
    prepared = graph.dry_run(DLINEAR)
    dedup = [p for p in prepared.errors if p.rule == "dedup"]
    assert [(p.at, p.candidates) for p in dedup] == [("nodes.$dlinear", ("method_0001",))]
    assert ("Paper", "Are Transformers Effective for Time Series Forecasting?", False) in graph.deduper.calls
    assert not any(kind in ("Experiment", "Claim") for kind, _, _ in graph.deduper.calls)  # Content 不查重

    out = plan(prepared, MemoryReader(graph.state))
    assert out["status"] == "blocked"
    assert out["errors"] == [
        {
            "rule": "dedup",
            "at": "nodes.$dlinear",
            "msg": "1 possible duplicate(s) not yet judged",
            "candidates": [
                {
                    "ref": "method_0001",
                    "kind": "Method",
                    "name": "Transformer-based forecasting",
                    "channels": ["semantic"],
                }
            ],
            "fix": "same object: replace $dlinear with the candidate id; "
            "different: list it in confirm.$dlinear.distinct_from",
        }
    ]


def test_confirm_distinct_from_clears_the_block(graph: MemoryGraph) -> None:
    graph.deduper = NeighbourDeduper(graph)
    confirmed = DLINEAR.replace("by: claude\n", "by: claude\nconfirm:\n  $dlinear: {distinct_from: [method_0001]}\n")
    prepared = graph.submit(confirmed)
    assert prepared.ok, prepared.errors
    assert prepared.ids["$dlinear"] == "method_0002"


def test_stubs_are_looked_up_as_stubs_and_channel_failures_warn(graph: MemoryGraph) -> None:
    graph.deduper = NeighbourDeduper(graph, errors=("semantic: error: ConnectError",))
    prepared = graph.dry_run(
        doc("$timesnet:\n  kind: Method\n  name: TimesNet\n  stub: true").replace(
            "by: claude\n", "by: claude\nconfirm:\n  $timesnet: {distinct_from: [method_0001]}\n"
        )
    )
    assert prepared.ok, prepared.errors
    assert graph.deduper.calls == [("Method", "TimesNet", True)]
    assert [(p.rule, p.severity) for p in prepared.problems] == [("dedup", "warning")]


def test_confirm_must_name_document_nodes_and_existing_ids(graph: MemoryGraph) -> None:
    for confirm, at in [
        ("$other: {distinct_from: [method_0001]}", "confirm.$other"),
        ("$tf2: {same_as: method_0001}", "confirm.$tf2"),
        ("$tf2: {distinct_from: [$tsf]}", "confirm.$tf2.distinct_from"),
    ]:
        text = doc("$tf2:\n  kind: Method\n  name: TF2\n  definition: x").replace(
            "by: claude\n", f"by: claude\nconfirm:\n  {confirm}\n"
        )
        assert [p.at for p in graph.dry_run(text).errors] == [at]


REVISE_EXP_CLAIM = (
    '  exp_0001: {revise: {reason: "baseline only", anchor: "5.2 Comparison::198:240"}}\n'
    '  claim_0001: {revise: {reason: "about the task", anchor: "Abstract::10:14"}}\n'
)


def test_delete_reports_incoming_relationships(ingested: MemoryGraph) -> None:
    prepared = ingested.dry_run(
        with_confirm(doc("claim_0001: null"), 'claim_0001: {revise: {reason: "the paper does not claim this"}}')
    )
    assert prepared.ok
    warnings = [p for p in prepared.problems if p.rule == "delete-impact"]
    assert warnings == []  # 没有其他节点指向 claim_0001

    prepared = ingested.dry_run(
        doc("""
        exp_0001:
          EVALUATES:
            - {to: method_0001, role: baseline}
        claim_0001:
          ABOUT: [task_0002]
        method_0002: null
        """).replace("by: claude\n", "by: claude\nconfirm:\n" + REVISE_EXP_CLAIM, 1)
    )
    impact = [p for p in prepared.problems if p.rule == "delete-impact"]
    assert [p.at for p in impact] == ["nodes.method_0002"]
    assert "contrib_0001-[ABOUT]->method_0002" in impact[0].msg
    assert impact[0].severity == "warning"


def test_plan_summarizes_changes_by_node(ingested: MemoryGraph) -> None:
    prepared = ingested.dry_run(
        doc("""
        method_0002:
          aliases: [Decomposition-Linear]
          definition: Changed.
        dataset_0002:
          kind: Benchmark
          PART_OF: []
        """)
    )
    out = plan(prepared, MemoryReader(ingested.state))
    assert out["status"] == "ready"
    assert out["changes"]["update"] == {
        "method_0002": ["definition", "names"],
        "dataset_0002": ["PART_OF", "kind", "names"],
    }
    assert out["changes"]["create"] == [] and out["changes"]["delete"] == []
    assert out["changes"]["edges"] == {"create": 0, "update": 0, "delete": 1}
    assert out["changes"]["names"] == {"create": 2, "delete": 2}

    assert plan(ingested.dry_run(doc("method_0002:\n  name: DLinear")), MemoryReader(ingested.state)) == {
        "graph-plan": "v0.1",
        "status": "noop",
    }


def test_plan_for_a_new_paper_and_the_result_after_apply(graph: MemoryGraph) -> None:
    out = plan(graph.dry_run(DLINEAR), MemoryReader(graph.state))
    assert out["changes"]["create"] == ["$paper", "$dlinear", "$exp", "$claim", "$contrib"]
    assert out["changes"]["materials"] == ["papers/2023-DLinear/paper.md"]

    prepared = graph.submit(DLINEAR)
    record = CommitRecord("commit_000002", "main", 2, "commit_000001", "claude", "t", "", "test", Changeset())
    out = result(prepared, record)
    assert out["commit"] == "commit_000002"
    assert out["ids"]["$exp"] == "exp_0001"
    assert out["counts"]["nodes_created"] == 5 + 1 + 3  # 模型节点、材料、三个名称
    assert out["counts"]["nodes_deleted"] == 0
