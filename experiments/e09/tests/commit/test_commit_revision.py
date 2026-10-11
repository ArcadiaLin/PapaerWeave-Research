"""有据层修订与解释层并存的写入守卫（e09.commit.revision）。

``ingested`` 中 exp_0001、claim_0001、contrib_0001（stated_by: paper）是有据层记录，来自 paper_0001 的材料（300 行）。
"""

from __future__ import annotations

from conftest import MemoryGraph, doc, rules, with_confirm

from graph_vc import EdgeKey

REVISE_CLAIM = 'claim_0001: {revise: {reason: "the abstract says most, not all", anchor: "Abstract::10:14"}}'
EDIT_CLAIM = doc("claim_0001:\n  text: DLinear outperforms Transformer methods in most long-horizon settings.")


def by(text: str, writer: str) -> str:
    return text.replace("by: claude\n", f"by: {writer}\n", 1)


def test_changing_a_grounded_record_needs_a_revision(ingested: MemoryGraph) -> None:
    prepared = ingested.dry_run(EDIT_CLAIM)
    assert rules(prepared) == {"revision"}
    assert [p.at for p in prepared.errors] == ["nodes.claim_0001"]


def test_a_revision_with_reason_and_anchor_is_accepted_and_recorded(ingested: MemoryGraph) -> None:
    prepared = ingested.submit(with_confirm(EDIT_CLAIM, REVISE_CLAIM))
    assert prepared.ok, prepared.errors
    assert prepared.revisions == {
        "claim_0001": {"reason": "the abstract says most, not all", "anchor": "Abstract::10:14"}
    }
    assert ingested.state.nodes["claim_0001"].props["text"].endswith("long-horizon settings.")


def test_changing_relations_of_a_grounded_record_is_a_revision(ingested: MemoryGraph) -> None:
    prepared = ingested.dry_run(doc("exp_0001:\n  ON_TASK: [task_0001]"))
    assert rules(prepared) == {"revision"}
    assert [p.at for p in prepared.errors] == ["nodes.exp_0001"]


def test_an_update_needs_an_anchor_inside_the_paper(ingested: MemoryGraph) -> None:
    no_anchor = ingested.dry_run(with_confirm(EDIT_CLAIM, 'claim_0001: {revise: {reason: "most"}}'))
    assert [p.at for p in no_anchor.errors] == ["confirm.claim_0001.revise.anchor"]

    outside = ingested.dry_run(
        with_confirm(EDIT_CLAIM, 'claim_0001: {revise: {reason: "most", anchor: "Abstract::290:310"}}')
    )
    assert rules(outside) == {"locator"}

    malformed = ingested.dry_run(with_confirm(EDIT_CLAIM, 'claim_0001: {revise: {reason: "most", page: 3}}'))
    assert rules(malformed) == {"format"}


def test_deleting_a_grounded_record_needs_only_a_reason(ingested: MemoryGraph) -> None:
    assert rules(ingested.dry_run(doc("claim_0001: null"))) == {"revision"}
    prepared = ingested.submit(with_confirm(doc("claim_0001: null"), 'claim_0001: {revise: {reason: "retracted"}}'))
    assert prepared.ok, prepared.errors
    assert prepared.revisions == {"claim_0001": {"reason": "retracted"}}


def test_notes_and_new_records_pointing_at_grounded_ones_are_free(ingested: MemoryGraph) -> None:
    prepared = ingested.dry_run(
        doc("""
        exp_0001:
          note: Horizon labels in the ILI rows look misprinted.
        $claim2:
          kind: Claim
          text: DLinear is competitive on ETTh1.
          FROM:
            - {to: paper_0001, locators: ["5.2 Comparison::198:240"]}
          SUPPORTED_BY: [exp_0001]
        """)
    )
    assert prepared.ok, prepared.errors
    assert prepared.revisions == {}


def test_an_unneeded_revise_only_warns(ingested: MemoryGraph) -> None:
    prepared = ingested.dry_run(
        with_confirm(doc("method_0002:\n  note: x"), 'method_0002: {revise: {reason: "x", anchor: "Abstract::10:14"}}')
    )
    assert prepared.ok, prepared.errors
    assert [(p.rule, p.severity) for p in prepared.problems if p.rule == "revision"] == [("revision", "warning")]


def _with_observation(graph: MemoryGraph) -> str:
    prepared = graph.submit(
        doc("""
        $obs:
          kind: Observation
          text: DLinear uses a longer look-back window than its baselines.
          ABOUT: [exp_0001]
        $claim2:
          kind: Claim
          text: Transformers remain competitive with longer look-back windows.
          FROM:
            - {to: paper_0001, locators: ["5.3 More Analyses::250:260"]}
          OPPOSES:
            - {to: claim_0001, stated_by: agent, description: With a 336-step window the conclusion reverses.}
        """)
    )
    assert prepared.ok, prepared.errors
    return prepared.ids["$obs"]


def test_interpretations_of_other_writers_cannot_be_changed(ingested: MemoryGraph) -> None:
    obs = _with_observation(ingested)
    edit = doc(f"{obs}:\n  text: The look-back windows match.")
    assert rules(ingested.dry_run(by(edit, "gpt"))) == {"coexist"}
    assert rules(ingested.dry_run(by(doc(f"{obs}: null"), "gpt"))) == {"coexist"}
    assert ingested.dry_run(edit).ok  # 形成者自己可以改


def test_agent_stances_of_other_writers_cannot_be_changed(ingested: MemoryGraph) -> None:
    _with_observation(ingested)
    claim2 = next(k.src for k in ingested.state.edges if k.type == "OPPOSES" and k.dst == "claim_0001")
    change = doc(f"""
        {claim2}:
          OPPOSES:
            - {{to: claim_0001, stated_by: agent, description: Only on ETTh2.}}
        """)
    assert rules(ingested.dry_run(by(change, "gpt"))) == {"coexist"}
    assert ingested.dry_run(change).ok
    assert EdgeKey(claim2, "OPPOSES", "claim_0001") in ingested.state.edges
