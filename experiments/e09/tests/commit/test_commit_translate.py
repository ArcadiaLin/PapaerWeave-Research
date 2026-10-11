"""写入路径在内存状态上的行为：commit.md §6 的 W1–W7 场景与各条检查。不需要数据库。"""

from __future__ import annotations

import hashlib

from conftest import DLINEAR, MemoryGraph, doc, rules, with_confirm

from e09.model.namekey import name_key
from graph_vc import EdgeKey, FileRef, NodeState


def test_seed_registers_names_as_namekeys(graph: MemoryGraph) -> None:
    state = graph.state
    assert state.nodes["task_0002"].labels == {"Concept", "Task"}
    key = name_key("LTSF", "Task")
    assert state.nodes[key].labels == {"NameKey"}
    assert state.nodes[key].props["raw"] == "LTSF"
    assert state.nodes[key].props["registered_from"] == "seed:tsf"
    assert state.nodes[key].props["registered_by"] == "seed"
    assert EdgeKey(key, "NAMES", "task_0002") in state.edges
    assert EdgeKey("task_0002", "BROADER", "task_0001") in state.edges
    assert "aliases" not in state.nodes["task_0002"].props


def test_w1_new_paper(ingested: MemoryGraph, tmp_path) -> None:
    state = ingested.state
    digest = hashlib.sha256((tmp_path / "papers/2023-DLinear/paper.md").read_bytes()).hexdigest()
    material = f"material_{digest[:12]}"
    assert state.nodes[material] == NodeState(
        frozenset({"Material"}), {"path": "papers/2023-DLinear/paper.md", "format": "markdown", "content_hash": digest}
    )
    assert EdgeKey(material, "MATERIAL_OF", "paper_0001") in state.edges
    assert state.edges[EdgeKey("exp_0001", "FROM", "paper_0001")] == {
        "locators": ["5.2 Comparison::198:240"],
        "material_ref": material,
    }
    assert state.nodes["exp_0001"].props["exp_key"] == "paper_0001::S5.T2"
    assert state.nodes["claim_0001"].props["content_key"] == "paper_0001::Claim::claim"
    assert state.nodes["contrib_0001"].props["content_key"] == "paper_0001::Contribution::contrib"
    assert "formed_by" not in state.nodes["claim_0001"].props
    assert EdgeKey(name_key("D-Linear", "Method"), "NAMES", "method_0002") in state.edges


def test_w1_changeset_registers_the_material_file(graph: MemoryGraph, tmp_path) -> None:
    prepared = graph.submit(DLINEAR)
    digest = hashlib.sha256((tmp_path / "papers/2023-DLinear/paper.md").read_bytes()).hexdigest()
    assert prepared.changeset is not None
    assert prepared.changeset.files == (FileRef("papers/2023-DLinear/paper.md", digest),)
    assert prepared.ids == {
        "$paper": "paper_0001",
        "$dlinear": "method_0002",
        "$exp": "exp_0001",
        "$claim": "claim_0001",
        "$contrib": "contrib_0001",
    }


def test_dry_run_uses_temporary_references_and_writes_nothing(graph: MemoryGraph) -> None:
    before = graph.state
    prepared = graph.dry_run(DLINEAR)
    assert prepared.ok
    assert graph.state is before
    created = {n.id: n for n in prepared.changeset.nodes if n.op == "create"}
    assert created["$exp"].after["exp_key"] == "$paper::S5.T2"


def test_submitting_the_same_paper_twice_is_blocked(ingested: MemoryGraph) -> None:
    prepared = ingested.dry_run(DLINEAR)
    # dry_run 中自然键由临时引用 $paper 拼成，不会与已有的键相撞；重复由标识、名称与材料发现
    assert rules(prepared) == {"identifier-taken", "name-taken", "material"}
    taken = {p.at: p.candidates for p in prepared.errors}
    assert taken["nodes.$paper.identifiers[0]"] == ("paper_0001",)
    assert taken["nodes.$dlinear"] == ("method_0002",)


def test_w3_edit_existing_nodes(ingested: MemoryGraph) -> None:
    prepared = ingested.submit(
        doc("""
        method_0002:
          aliases: [Decomposition-Linear]
          definition: A linear model on a moving-average trend and a remainder.
        exp_0001:
          EVALUATES:
            - {to: method_0002, role: target}
            - {to: method_0001, role: baseline}
            - {to: method_0002, role: baseline}
        dataset_0002:
          kind: Benchmark
          PART_OF: []
        """)
    )
    assert not prepared.ok and rules(prepared) == {"format"}  # 重复的 EVALUATES 目标

    prepared = ingested.submit(
        doc("""
        method_0002:
          aliases: [Decomposition-Linear]
          definition: A linear model on a moving-average trend and a remainder.
        dataset_0002:
          kind: Benchmark
          PART_OF: []
        """)
    )
    assert prepared.ok, prepared.errors
    state = ingested.state
    assert state.nodes["method_0002"].props["definition"].startswith("A linear model on a moving-average")
    assert name_key("D-Linear", "Method") not in state.nodes
    assert EdgeKey(name_key("Decomposition-Linear", "Method"), "NAMES", "method_0002") in state.edges
    assert EdgeKey(name_key("DLinear", "Method"), "NAMES", "method_0002") in state.edges

    assert state.nodes["dataset_0002"].labels == {"Entity", "Benchmark"}
    assert name_key("ETTh1", "Dataset") not in state.nodes
    assert EdgeKey(name_key("ETTh1", "Benchmark"), "NAMES", "dataset_0002") in state.edges
    assert EdgeKey("dataset_0002", "PART_OF", "dataset_0001") not in state.edges
    assert EdgeKey("dataset_0002", "FOR_TASK", "task_0002") in state.edges  # 没写的关系不动


def test_w4_agent_records_carry_formation(ingested: MemoryGraph) -> None:
    prepared = ingested.submit(
        with_confirm(
            doc("""
        $issue:
          kind: Issue
          text: Can linear models replace Transformers for long-term forecasting?
        claim_0001:
          ABOUT: [method_0002, task_0002, $issue]
        $claim2:
          kind: Claim
          text: Transformers remain competitive with longer look-back windows.
          FROM:
            - {to: paper_0001, locators: ["5.3 More Analyses::250:260"]}
          ABOUT: [method_0001]
          OPPOSES:
            - to: claim_0001
              stated_by: agent
              description: With a 336-step window the conclusion reverses.
        $obs:
          kind: Observation
          text: The two papers use different look-back windows.
          ABOUT: [exp_0001]
          FROM:
            - {to: paper_0001, locators: ["5.1 Settings::160:172"]}
        $contrib-agent:
          kind: Contribution
          stated_by: agent
          text: Prompted later work to report the look-back window.
          FROM: [paper_0001]
          ABOUT: [paper_0001]
        """),
            'claim_0001: {revise: {reason: "also about the open issue", anchor: "Abstract::10:14"}}',
        )
    )
    assert prepared.ok, prepared.errors
    ids, state = prepared.ids, ingested.state
    assert state.nodes[ids["$obs"]].props["formed_by"] == "claude"
    assert state.nodes[ids["$obs"]].props["formed_at"] == "2026-10-05T12:00:00+00:00"
    assert state.nodes[ids["$contrib-agent"]].props["formed_by"] == "claude"
    assert "content_key" not in state.nodes[ids["$contrib-agent"]].props
    stance = state.edges[EdgeKey(ids["$claim2"], "OPPOSES", "claim_0001")]
    assert stance["formed_by"] == "claude" and stance["stated_by"] == "agent"
    assert EdgeKey("claim_0001", "ABOUT", ids["$issue"]) in state.edges
    assert state.edges[EdgeKey(ids["$contrib-agent"], "FROM", "paper_0001")]["material_ref"].startswith("material_")


REVISE_ALL = """
exp_0001: {revise: {reason: "drop the merged method", anchor: "5.2 Comparison::198:240"}}
claim_0001: {revise: {reason: "drop the merged method", anchor: "Abstract::10:14"}}
contrib_0001: {revise: {reason: "drop the merged method", anchor: "1 Introduction::40:44"}}
"""


def test_w5_delete_takes_names_and_relationships(ingested: MemoryGraph) -> None:
    prepared = ingested.submit(
        with_confirm(
            doc("""
        exp_0001:
          EVALUATES:
            - {to: method_0001, role: baseline}
        claim_0001:
          ABOUT: [task_0002]
        contrib_0001:
          ABOUT: [task_0002]
        method_0002: null
        """),
            REVISE_ALL,
        )
    )
    assert prepared.ok, prepared.errors
    state = ingested.state
    assert "method_0002" not in state.nodes
    assert name_key("DLinear", "Method") not in state.nodes
    assert name_key("D-Linear", "Method") not in state.nodes
    assert not any("method_0002" in (k.src, k.dst) for k in state.edges)


def test_w5_delete_leaving_a_required_edge_missing_is_blocked(ingested: MemoryGraph) -> None:
    prepared = ingested.dry_run(doc("method_0002: null"))
    assert rules(prepared) == {"required-edge"}
    assert {p.at for p in prepared.errors} == {"nodes.contrib_0001.ABOUT"}


def test_w6_merge_moves_names_without_recreating_them(ingested: MemoryGraph) -> None:
    assert ingested.submit(
        doc("""
        $dlinear2:
          kind: Method
          name: Linear decomposition model
          aliases: [DLinear-S]
          definition: Duplicate of DLinear.
        """)
    ).ok
    moved = name_key("DLinear-S", "Method")
    assert EdgeKey(moved, "NAMES", "method_0003") in ingested.state.edges

    prepared = ingested.submit(
        doc("""
        method_0002:
          aliases: [D-Linear, DLinear-S, Linear decomposition model]
        method_0003: null
        """)
    )
    assert prepared.ok, prepared.errors
    # 改指，而不是删了再建：NameKey 节点本身不变，只换掉 NAMES 边
    assert moved not in {n.id for n in prepared.changeset.nodes}
    assert {(str(e.key), e.op) for e in prepared.changeset.edges if e.key.src == moved} == {
        (f"{moved}-[NAMES]->method_0003", "delete"),
        (f"{moved}-[NAMES]->method_0002", "create"),
    }
    assert "method_0003" not in ingested.state.nodes
    assert EdgeKey(moved, "NAMES", "method_0002") in ingested.state.edges


def test_w7_rejections(ingested: MemoryGraph) -> None:
    ingested.state.nodes["art_0001"] = NodeState(frozenset({"Artifact"}), {"op": "Check", "title": "t"})
    cases = {
        "art_0001:\n  title: changed": "readonly",
        "art_0001:\n  _op: Check": None,  # 读视图原样带回：忽略
        "art_0001: null": "readonly",
        "method_0002:\n  EVALUATES: [method_0001]": "endpoint",
        "$orphan:\n  kind: Observation\n  text: x": "required-edge",
        "claim_0001:\n  ABOUT: [method_9999]": "reference",
        "method_9999:\n  note: x": "reference",
        "$x:\n  name: no kind": "format",
        "method_0002:\n  kind: Dataset": "format",
        "method_0002:\n  exp_key: x": "field",
        "method_0002:\n  year: 2023": "field",
        "claim_0001:\n  NAMES: [method_0002]": "relationship",
        "claim_0001:\n  SUPPORTS:\n    - {to: claim_0001}": "required-field",
        "exp_0001:\n  EVALUATES:\n    - {to: method_0002, role: winner}": "field",
        "exp_0001:\n  FROM:\n    - {to: paper_0001, locators: ['5.2::298:400']}": "locator",
        "exp_0001:\n  FROM:\n    - {to: paper_0001, locators: ['no lines']}": "locator",
        "exp_0001:\n  FROM:\n    - {to: method_0002, locators: ['a::1:2']}": "locator",
        "method_0002:\n  BROADER: [task_0001]": "endpoint",
        "$p:\n  kind: Paper\n  name: B\n  description: x\n  identifiers: ['arxiv:2205.13504']": "identifier-taken",
        "$p:\n  kind: Paper\n  name: B\n  description: x\n  identifiers: ['isbn:1']": "identifier",
        "paper_0001:\n  material: papers/2023-PatchTST/paper.md": "material",
        "paper_0001:\n  material: papers/missing.md": "material",
    }
    for body, rule in cases.items():
        prepared = ingested.dry_run(doc(body))
        if rule is None:
            assert prepared.ok and not prepared.changeset, (body, prepared.errors)
        else:
            assert rule in rules(prepared), (body, prepared.errors)


def test_readonly_fields_echoed_unchanged_are_accepted(ingested: MemoryGraph) -> None:
    material = ingested.state.edges[EdgeKey("exp_0001", "FROM", "paper_0001")]["material_ref"]
    echoed = doc(f"""
    paper_0001:
      _material: {material}
    exp_0001:
      FROM:
        - {{to: paper_0001, locators: ["5.2 Comparison::198:240"], _material: {material}}}
    """)
    prepared = ingested.dry_run(echoed)
    assert prepared.ok and not prepared.changeset, prepared.errors

    changed = doc("paper_0001:\n  _material: material_000000000000")
    assert rules(ingested.dry_run(changed)) == {"readonly"}


def test_source_refs_name_a_node_or_a_material(graph: MemoryGraph) -> None:
    prepared = graph.dry_run(
        DLINEAR
        + """
  $patchtst-paper:
    kind: Paper
    name: "A Time Series is Worth 64 Words"
    description: PatchTST.
    material: papers/2023-PatchTST/paper.md
    CITES:
      - to: $paper
        description: Table 3 results for DLinear come from this paper
        source_refs: ["$patchtst-paper::4.1 Long-term Forecasting::210:212"]
"""
    )
    assert prepared.ok, prepared.errors
    cites = next(e for e in prepared.changeset.edges if e.key.type == "CITES")
    assert cites.after["source_refs"][0].startswith("material_")
    assert cites.after["source_refs"][0].endswith("::4.1 Long-term Forecasting::210:212")


def test_open_entity_fields_warn_but_concept_fields_fail(ingested: MemoryGraph) -> None:
    entity = ingested.dry_run(doc("dataset_0002:\n  license: MIT"))
    assert entity.ok and [p.rule for p in entity.problems] == ["field"]
    assert entity.problems[0].severity == "warning"
    concept = ingested.dry_run(doc("task_0002:\n  license: MIT"))
    assert rules(concept) == {"field"}


def test_stub_needs_only_a_name(graph: MemoryGraph) -> None:
    prepared = graph.submit(doc("$timesnet:\n  kind: Method\n  name: TimesNet\n  stub: true"))
    assert prepared.ok, prepared.errors
    filled = graph.submit(doc("method_0002:\n  stub: null"))
    assert rules(filled) == {"required-field"}  # 补全桩节点时要给出定义
