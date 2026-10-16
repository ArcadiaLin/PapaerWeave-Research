"""写入管线（graph-doc v0.2 → 变更集）在内存图上的行为：三个动词、字段的物理写法、查重与有据层修订。"""

from __future__ import annotations

import json

import pytest

from graph_vc import EdgeKey

from paperweave.commit import Candidate, Lookup
from paperweave.model.schema import labels_of

from .conftest import DLINEAR, MemoryGraph, doc, rules


@pytest.fixture
def ingested(graph: MemoryGraph) -> MemoryGraph:
    prepared = graph.submit(DLINEAR)
    assert prepared.ok, prepared.errors
    return graph


def edges(graph: MemoryGraph, src: str, rel_type: str) -> dict[str, dict]:
    return {k.dst: v for k, v in graph.state.edges.items() if k.src == src and k.type == rel_type}


# ── create ────────────────────────────────────────────────────────────


def test_paper_form_is_written_in_physical_form(ingested: MemoryGraph) -> None:
    state = ingested.state
    paper = state.nodes["paper_0001"]
    assert paper.labels == labels_of("Paper")
    assert json.loads(paper.props["extra"]) == {"venue": "AAAI 2023"}
    assert paper.props["formed_by"] == "claude"
    exp = state.nodes["exp_0001"]
    assert exp.props["anchor"] == ["198:240"]
    assert exp.props["exp_key"] == "paper_0001::S5.T2"
    assert "paper" not in exp.props
    material = next(iter(edges(ingested, "exp_0001", "FROM").values()))["material_ref"]
    assert material.startswith("material_")
    assert edges(ingested, "exp_0001", "EVALUATES")["method_0001"]["result"] == "cited"
    assert edges(ingested, "exp_0001", "USES")["dataset_0002"]["printed_as"] == "ETTh1"
    implements = edges(ingested, "code_0001", "IMPLEMENTS")["method_0002"]
    assert implements["paper"] == "paper_0001" and implements["material_ref"] == material
    assert implements["formed_by"] == "claude"
    # D-Linear 是别名：NameKey 指向 DLinear
    names = {state.nodes[k.src].props["raw"] for k in state.edges if k.type == "NAMES" and k.dst == "method_0002"}
    assert names == {"DLinear", "D-Linear"}


def test_restating_a_create_edge_is_a_noop_and_a_different_one_is_an_error(ingested: MemoryGraph) -> None:
    same = ingested.dry_run(doc("""
        create:
          exp_0001:
            EVALUATES:
              method_0001:
                role: baseline
        """))
    assert same.ok and not same.changeset
    other = ingested.dry_run(doc("""
        create:
          exp_0001:
            EVALUATES:
              method_0001:
                role: target
        """))
    assert rules(other) == {"exists"}
    assert "role: 'baseline'" in other.errors[0].msg


def test_create_reports_missing_ids_and_unknown_types(graph: MemoryGraph) -> None:
    prepared = graph.dry_run(doc("""
        create:
          $m:
            kind: Method
            name: X
            description: x
            BROADER: [method_0099]
            USES: [dataset_0001]
            FROM: [task_0001]
            DERIVED_FROM: [method_0001]
          method_0098:
            BROADER: [method_0001]
        """))
    msgs = {p.at: p.msg for p in prepared.errors}
    assert "does not exist" in msgs["create.$m.BROADER.method_0099"]
    assert "maintained by the system" in msgs["create.$m.FROM.task_0001"]
    assert "RELATES_TO" in msgs["create.$m.DERIVED_FROM.method_0001"]
    assert "does not exist" in msgs["create.method_0098"]
    assert "Experiment → Dataset | Code | Model | Tool" in msgs["create.$m.USES.dataset_0001"]


def test_fields_are_checked_against_the_kind(graph: MemoryGraph) -> None:
    prepared = graph.dry_run(doc("""
        create:
          $m:
            kind: Method
            name: X
            description: x
            venue: ICLR
          $p:
            kind: Paper
            name: P
            identities: [arxiv]
          $e:
            kind: Experiment
            paper: $p
            anchor: [1:2]
            description: x
            EVALUATES:
              $m:
                role: winner
        """))
    msgs = {p.at: p.msg for p in prepared.errors}
    assert "extra" in msgs["create.$m.venue"]
    assert "namespace" in msgs["create.$p.identities[0]"]
    assert "no material" in msgs["create.$e.anchor"]  # 论文是桩：没有正文
    assert "target" in msgs["create.$e.EVALUATES.$m.role"]


def test_anchor_lines_are_checked_against_the_material(graph: MemoryGraph) -> None:
    text = DLINEAR.replace("anchor: [198:240]", "anchor: [198:999]")
    prepared = graph.dry_run(text)
    assert [p.at for p in prepared.errors] == ["create.$exp.anchor[0]"]
    assert "outside the paper (1:300)" in prepared.errors[0].msg


def test_required_fields_and_edges(graph: MemoryGraph) -> None:
    prepared = graph.dry_run(doc("""
        create:
          $p:
            kind: Paper
            name: P
            material: papers/2023-DLinear/paper.md
          $e:
            kind: Experiment
            paper: $p
            anchor: [1:2]
          $c:
            kind: Contribution
            anchor: [1:2]
            description: x
          $t:
            kind: Task
            name: T
        """))
    found = {(p.rule, p.at) for p in prepared.errors}
    assert ("required-field", "$e.description") in found
    assert ("required-edge", "$e.EVALUATES") in found
    assert ("required-field", "$c.paper") in found
    assert ("required-edge", "$c.ABOUT") in found
    assert ("required-field", "$t.description") in found


def test_relates_to_needs_a_description_and_hints_named_types(ingested: MemoryGraph) -> None:
    prepared = ingested.dry_run(doc("""
        create:
          code_0001:
            RELATES_TO:
              method_0001:
                description: |
                  Contains a reimplementation of Transformer baselines.
          method_0002:
            RELATES_TO: [method_0001]
        """))
    assert {(p.rule, p.at) for p in prepared.errors} == {("required-field", "method_0002.RELATES_TO.method_0001.description")}
    assert any("IMPLEMENTS" in p.msg for p in prepared.problems if p.severity == "warning")


# ── set ───────────────────────────────────────────────────────────────


def test_set_changes_only_written_fields_and_merges_extra(ingested: MemoryGraph) -> None:
    prepared = ingested.submit(doc("""
        set:
          paper_0001:
            kind: Paper
            extra:
              venue: null
              authors: [Ailing Zeng]
          method_0002:
            alias: [DLinear model]
        """))
    assert prepared.ok, prepared.errors
    paper = ingested.state.nodes["paper_0001"]
    assert json.loads(paper.props["extra"]) == {"authors": ["Ailing Zeng"]}
    assert paper.props["year"] == 2023
    names = {
        ingested.state.nodes[k.src].props["raw"]
        for k in ingested.state.edges
        if k.type == "NAMES" and k.dst == "method_0002"
    }
    assert names == {"DLinear", "DLinear model"}


def test_set_requires_existing_nodes_and_edges(ingested: MemoryGraph) -> None:
    prepared = ingested.dry_run(doc("""
        set:
          method_0099:
            description: x
          method_0002:
            kind: Task
            BROADER:
              method_0003:
                description: x
        """))
    msgs = {p.at: p.msg for p in prepared.errors}
    assert "does not exist" in msgs["set.method_0099"]
    assert "kind cannot be changed" in msgs["set.method_0002.kind"]
    assert "does not exist" in msgs["set.method_0002.BROADER.method_0003"]


def test_pasting_a_read_back_into_set_changes_nothing(ingested: MemoryGraph) -> None:
    prepared = ingested.dry_run(doc("""
        set:
          exp_0001:
            kind: Experiment
            paper: paper_0001
            anchor: [198:240]
            figures: [S5.T2, A3.T9]
            description: |
              Compare DLinear with Transformer baselines on nine datasets.
            _edges_in:
              SUPPORTS: 0
            EVALUATES:
              method_0001:
                role: baseline
                result: cited
                _formed_by: claude
        """))
    assert prepared.ok, prepared.errors
    assert not prepared.changeset


def test_filling_a_stub_drops_stub(graph: MemoryGraph) -> None:
    assert graph.submit(doc("""
        create:
          $n:
            kind: Method
            name: N-BEATS
            stub: true
        """)).ok
    assert graph.submit(doc("""
        set:
          method_0002:
            description: |
              A deep stack of fully connected blocks with backward and forward residual links.
        """)).ok
    assert "stub" not in graph.state.nodes["method_0002"].props


# ── delete ────────────────────────────────────────────────────────────


def test_delete_edges_and_nodes(ingested: MemoryGraph) -> None:
    prepared = ingested.submit(doc("""
        delete:
          method_0002:
            BROADER: [method_0001]
          code_0001:
        """))
    assert prepared.ok, prepared.errors
    assert EdgeKey("method_0002", "BROADER", "method_0001") not in ingested.state.edges
    assert "code_0001" not in ingested.state.nodes
    missing = ingested.dry_run(doc("""
        delete:
          method_0002:
            BROADER: [method_0001]
        """))
    assert rules(missing) == {"reference"}


def test_change_an_edge_target(ingested: MemoryGraph) -> None:
    prepared = ingested.submit(doc("""
        delete:
          exp_0001:
            USES: [dataset_0002]
        create:
          exp_0001:
            USES:
              dataset_0001:
                role: evaluation_data
        confirm:
          exp_0001:
            revise:
              reason: |
                The table reports ETT as a whole, not ETTh1.
              anchor: [198:205]
        """))
    assert prepared.ok, prepared.errors
    assert set(edges(ingested, "exp_0001", "USES")) == {"dataset_0001"}
    assert prepared.revisions["exp_0001"]["anchor"] == ["198:205"]


# ── 查重 ──────────────────────────────────────────────────────────────


class FakeDeduper:
    def __init__(self, hits: dict[str, list[str]]):
        self.hits = hits

    def lookup(self, kind, *, name, identities, description, stub):  # noqa: ANN001
        return Lookup(tuple(Candidate(c, ("name",)) for c in self.hits.get(name or "", [])))


def test_dedup_blocks_until_judged(graph: MemoryGraph) -> None:
    graph.deduper = FakeDeduper({"Transformer": ["method_0001"]})
    text = doc("""
        create:
          $tr:
            kind: Method
            name: Transformer
            description: x
        """)
    blocked = graph.dry_run(text)
    assert rules(blocked) == {"dedup"} and blocked.errors[0].candidates == ("method_0001",)
    judged = graph.dry_run(text + "confirm:\n  $tr:\n    distinct_from: [method_0001]\n")
    assert judged.ok, judged.errors


def test_names_and_identities_are_unique(ingested: MemoryGraph) -> None:
    prepared = ingested.dry_run(doc("""
        create:
          $d:
            kind: Method
            name: D-Linear
            description: x
          $p:
            kind: Paper
            name: Copy
            identities: ["arxiv:2205.13504"]
        """))
    assert rules(prepared) == {"name-taken", "identity-taken"}


# ── 有据层修订 ────────────────────────────────────────────────────────


def test_grounded_edits_need_reason_and_anchor(ingested: MemoryGraph) -> None:
    text = doc("""
        set:
          claim_0001:
            description: |
              DLinear outperforms Transformers in most of the 9 datasets.
        """)
    assert rules(ingested.dry_run(text)) == {"revision"}
    fixed = text + "confirm:\n  claim_0001:\n    revise:\n      reason: closer to the abstract\n      anchor: [10:12]\n"
    prepared = ingested.submit(fixed)
    assert prepared.ok, prepared.errors
    assert prepared.revisions == {"claim_0001": {"reason": "closer to the abstract", "anchor": ["10:12"]}}


def test_adding_an_edge_to_a_record_needs_only_an_anchor(ingested: MemoryGraph) -> None:
    bare = doc("""
        create:
          exp_0001:
            USES:
              dataset_0001:
                role: evaluation_data
        """)
    assert rules(ingested.dry_run(bare)) == {"revision"}
    anchored = bare.replace("role: evaluation_data", "role: evaluation_data\n        anchor: [200:201]")
    assert ingested.dry_run(anchored).ok


def test_deleting_a_record_needs_a_reason(ingested: MemoryGraph) -> None:
    text = doc("""
        delete:
          contrib_0001:
        """)
    assert rules(ingested.dry_run(text)) == {"revision"}
    assert ingested.dry_run(text + "confirm:\n  contrib_0001:\n    revise:\n      reason: duplicate of another\n").ok


def test_entities_and_concepts_change_freely(ingested: MemoryGraph) -> None:
    assert ingested.dry_run(doc("""
        set:
          method_0002:
            description: |
              Decomposition plus two linear layers.
        """)).ok


def test_changing_a_records_paper_moves_from_and_rechecks_anchors(ingested: MemoryGraph) -> None:
    ingested.state  # noqa: B018
    text = doc("""
        create:
          $p2:
            kind: Paper
            name: PatchTST
            material: papers/2023-PatchTST/paper.md
        set:
          claim_0001:
            paper: $p2
        confirm:
          claim_0001:
            revise:
              reason: it is PatchTST's claim
              anchor: [10:14]
        """)
    prepared = ingested.submit(text)
    assert prepared.ok, prepared.errors
    assert set(edges(ingested, "claim_0001", "FROM")) == {"paper_0002"}


def test_writer_is_required(graph: MemoryGraph) -> None:
    prepared = graph.dry_run(doc("""
        create:
          $t:
            kind: Task
            name: T
            description: t
        """), user="")
    assert rules(prepared) == {"identity"}
