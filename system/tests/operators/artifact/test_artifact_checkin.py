"""产物的 checkout 与 commit：检出、编辑、检入，版本链与编辑提示（operators.md §3.6、§4.1、§5）。

模块内的测试按顺序共享写入的产物：art_0001 是 Leaderboard，之后各测试在它上面接着做。
"""

from __future__ import annotations

from typing import Any

import pytest
from conftest import LEADERBOARD, MATERIAL, Writer, commit_doc

from paperweave.artifact.checkin import Item
from paperweave.artifact.stale import stale
from paperweave.artifact.versions import history
from paperweave.draft import Draft
from paperweave.operators.db.search import search
from paperweave.store import Store

PATH = "artifacts/ETTh1 multivariate long-term forecasting.md"
ROW = "| method_0001 Transformer |  | paper_0001 DLinear | baseline | 96 | 96 | 0.865 |"


def rules(result: dict[str, Any]) -> list[tuple[str, str]]:
    return [(e["rule"], e["at"]) for e in result.get("errors", [])]


def used(store: Store, art_id: str) -> dict[str, dict[str, Any]]:
    rows = store.query("MATCH (:Artifact {id: $id})-[u:USED]->(x) RETURN x.id AS id, properties(u) AS p", id=art_id)
    return {r["id"]: r["p"] for r in rows}


def test_create_checks_before_writing(store: Store, writers: dict[str, Writer]) -> None:
    claude = writers["claude"]
    claude.write("lb.md", LEADERBOARD)
    head = store.graph.head()
    checked = claude.check_in("lb.md", message="Seed the ETTh1 leaderboard from DLinear Table 2.")
    assert checked["status"] == "checked" and store.graph.head() == head
    assert checked["items"][0]["action"] == "create"
    assert checked["items"][0]["changes"]["rows_added"] == 3  # 两行结果，一行论文覆盖

    done = claude.check_in("lb.md", message="Seed the ETTh1 leaderboard from DLinear Table 2.", confirm=True)
    assert done["status"] == "committed"
    item = done["items"][0]
    assert (item["artifact"], item["version"]) == ("art_0001", 1)
    assert item["document"]["path"] == "artifacts/ETTh1 multivariate long-term forecasting.v1.md"
    node = store.query("MATCH (a:Artifact {id: 'art_0001'}) RETURN properties(a) AS p")[0]["p"]
    assert node["op"] == "Leaderboard" and node["formed_by"] == "claude" and node["key"].startswith("leaderboard|")
    edges = used(store, "art_0001")
    assert set(edges) == {"task_0001", "dataset_0001", "method_0001", "method_0002", "paper_0001"}
    assert edges["dataset_0001"]["role"] == ["dataset"]
    assert edges["paper_0001"]["role"] == ["paper"] and edges["paper_0001"]["material_ref"].startswith("material_")
    assert "5.2 Comparison::10:12" in edges["paper_0001"]["locators"]
    assert stale(store, ["art_0001"]) == {"art_0001": []}


def test_same_identity_is_returned(store: Store, writers: dict[str, Writer]) -> None:
    alice = writers["alice"]
    alice.write("mine.md", LEADERBOARD.replace("dataset: dataset_0001    # ETTh1", "dataset: dataset_0001 ETTh1"))
    result = alice.check_in("mine.md", confirm=True)
    assert result["status"] == "rejected" and rules(result) == [("identity", "mine.md:1")]
    assert "art_0001" in result["errors"][0]["msg"]


def test_fetch_gives_id_base_and_hint(store: Store, writers: dict[str, Writer]) -> None:
    out = writers["bob"].fetch("art_0001")
    item = out["items"][0]
    assert item["path"] == PATH and item["version"] == 1
    text = writers["bob"].read(PATH)
    assert text.splitlines()[1:3] == ["id: art_0001", f"base: {item['base']}"]
    assert item["hint"]["since_your_last_edit"] == "you have not edited it before"
    assert item["hint"]["editors"] == [{"editor": "claude", "versions": [1]}]
    writers["claude"].fetch("art_0001")  # claude 留着 v1，之后用来检验 base 冲突


def test_editing_others_rows_needs_a_reason(store: Store, writers: dict[str, Writer]) -> None:
    bob = writers["bob"]
    text = bob.read(PATH).replace(
        ROW + " paper_0001::5.2 Comparison::12 |", ROW.replace("0.865", "0.866") + " paper_0001::5.2 Comparison::12 |"
    )
    bob.write(PATH, text + "\nBaselines are copied from DLinear's own table.\n")
    checked = bob.check_in(PATH, message="Fix the Transformer MSE; add a note.")
    others = checked["items"][0]["others"]
    assert [(o["editor"], o["change"], o["at"]) for o in others] == [("claude", "modified", f"{PATH}:16")]
    assert bob.check_in(PATH, message="Fix the Transformer MSE.", confirm=True)["status"] == "rejected"

    done = bob.check_in(
        PATH, message="Fix the Transformer MSE; add a note.", confirm=True, reason="Table 2 says 0.866."
    )
    assert done["status"] == "committed" and done["items"][0]["version"] == 2
    versions = history(store, "art_0001")
    assert [(v.number, v.author) for v in versions] == [(1, "claude"), (2, "bob")]
    assert versions[1].reason == "Table 2 says 0.866."
    old = store.query("MATCH (m:Material {id: $id}) RETURN m.superseded_by AS by", id=versions[0].material["id"])
    assert old[0]["by"] == versions[1].material["id"]
    current = store.query(
        "MATCH (m:Material)-[:MATERIAL_OF]->(:Artifact {id: 'art_0001'}) "
        "WHERE m.superseded_by IS NULL RETURN m.id AS id"
    )
    assert [r["id"] for r in current] == [versions[1].material["id"]]


def test_stale_base_is_a_conflict(store: Store, writers: dict[str, Writer]) -> None:
    claude = writers["claude"]
    claude.write(PATH, claude.read(PATH).replace("| 0.375 |", "| 0.376 |"))
    head = store.graph.head()
    result = claude.check_in(PATH, confirm=True)
    assert result["status"] == "conflict" and rules(result) == [("conflict", f"{PATH}:1")]
    assert store.graph.head() == head


def test_since_your_last_edit(store: Store, writers: dict[str, Writer]) -> None:
    hint = writers["claude"].fetch("art_0001")["items"][0]["hint"]
    assert hint["version"] == 2 and hint["last_edit"]["reason"] == "Table 2 says 0.866."
    changed = hint["since_your_last_edit"]["changed_by_others"]
    assert {(c["editor"], c["version"]) for c in changed} == {("bob", 2)}
    assert any(c["what"].startswith("results row method_0001") and c["at"] == 16 for c in changed)


def test_unchanged_document_is_a_noop(store: Store, writers: dict[str, Writer]) -> None:
    head = store.graph.head()
    result = writers["claude"].check_in(PATH, confirm=True)
    assert result["status"] == "unchanged" and result["items"][0]["action"] == "noop"
    assert store.graph.head() == head


def test_reverting_content_makes_a_new_version(store: Store, writers: dict[str, Writer]) -> None:
    claude = writers["claude"]
    lines = claude.read(PATH).splitlines(keepends=True)
    claude.write(PATH, "".join(lines[:3]) + LEADERBOARD[4:])  # 保留 id、base，内容改回 v1
    result = claude.check_in(PATH, message="Back to v1.", confirm=True, reason="Revert.")
    assert result["status"] == "committed" and result["items"][0]["version"] == 3
    v1, _, v3 = history(store, "art_0001")
    assert v3.material["content_hash"] == v1.material["content_hash"] and v3.material["id"] != v1.material["id"]


def test_record_reference_pins_the_version(store: Store, writers: dict[str, Writer]) -> None:
    alice = writers["alice"]
    answer = (
        "---\ntype: Note\ntitle: DLinear on ETTh1\nabs: Short answer.\n---\n"
        "DLinear reaches 0.375 MSE at horizon 96 [art_0001#method_0002++paper_0001+96+336].\n"
    )
    alice.write("answer.md", answer)
    done = alice.check_in("answer.md", message="Answer the ETTh1 question.", confirm=True)
    assert done["status"] == "committed" and done["items"][0]["artifact"] == "art_0002"
    edge = used(store, "art_0002")["art_0001"]
    assert edge["material_ref"] == history(store, "art_0001")[-1].material["id"]
    assert edge["role"] == ["method_0002++paper_0001+96+336"]

    again = alice.check_in("answer.md", message="Answer the ETTh1 question.", confirm=True)
    assert again["status"] == "unchanged" and again["items"][0] == {
        "doc": "answer.md",
        "type": "Note",
        "artifact": "art_0002",
        "action": "existing",
    }


def test_references_must_exist(store: Store, writers: dict[str, Writer]) -> None:
    alice = writers["alice"]
    bad = "---\ntype: Note\ntitle: Bad\nabs: Bad refs.\n---\n"
    bad += "See [exp_9999].\nAnd [paper_0001::5.2 Comparison::59:70].\n"
    alice.write("bad.md", bad)
    alice.write("fine.md", "---\ntype: Note\ntitle: Fine\nabs: Fine.\n---\nSee [exp_0001].\n")
    head = store.graph.head()
    result = alice.check_in("fine.md", "bad.md", confirm=True)
    assert result["status"] == "rejected" and rules(result) == [("reference", "bad.md:6"), ("reference", "bad.md:7")]
    assert store.graph.head() == head
    missing = alice.check_in("fine.md", confirm=True)["items"][0]
    assert missing["action"] == "create"


def test_paper_forms_go_through_commit(writers: dict[str, Writer]) -> None:
    claude = writers["claude"]
    claude.write("form.md", "---\ntype: paper-form\ntitle: X\nabs: Y\n---\n")
    result = claude.check_in("form.md")
    assert rules(result) == [("format", "form.md:1")] and "graph-doc" in result["errors"][0]["msg"]


def test_checkout_reports_what_is_missing(writers: dict[str, Writer]) -> None:
    assert writers["alice"].fetch("art_0001", "art_9999")["missing"] == [{"artifact": "art_9999", "msg": "not in the store"}]


def test_skill_round_trip(store: Store, writers: dict[str, Writer]) -> None:
    claude, bob = writers["claude"], writers["bob"]
    skill = "---\nname: leaderboard\ndescription: How to add results to a Leaderboard.\n"
    skill += "metadata:\n  type: Skill\n---\nFind it first.\n"
    claude.write("skill.md", skill)
    created = claude.check_in("skill.md", message="Seed the leaderboard skill.", confirm=True)
    art = created["items"][0]["artifact"]
    item = bob.fetch(art)["items"][0]
    assert item["path"] == ".agents/skills/leaderboard/SKILL.md"
    text = bob.read(item["path"])
    assert "  id: " + art in text and text.startswith("---\nname: leaderboard\n")
    bob.write(item["path"], text + "Then read the paper's table.\n")
    done = bob.check_in(item["path"], message="Add a step.", confirm=True)
    assert done["status"] == "committed" and done["items"][0]["version"] == 2
    node = store.query("MATCH (a:Artifact {id: $id}) RETURN a.title AS t, a.abs AS a", id=art)[0]
    assert node == {"t": "leaderboard", "a": "How to add results to a Leaderboard."}


def test_light_rules_warnings_and_notes(store: Store, writers: dict[str, Writer]) -> None:
    claude = writers["claude"]
    item = claude.fetch("art_0001")["items"][0]
    assert item["notes"]["rows_by_contributor"] == [{"editor": "claude", "rows": 2, "versions": [1, 3]}]
    text = claude.read(PATH).replace(
        "setting: {variate: multivariate}\n", "setting: {variate: multivariate}\nmetrics: {MSE: lower}\n"
    )
    text = text.replace("| 0.375 |", "| 0.5 |").replace("| 0.865 |", "| 12 |")  # 所引的行是 "line 10"…"line 12"
    claude.write(PATH, text)
    checked = claude.check_in(PATH, message="Declare metrics; fix two numbers.")
    warnings = [(w["rule"], w["at"]) for w in checked["items"][0]["warnings"]]
    assert ("number", f"{PATH}:16") in warnings and ("number", f"{PATH}:17") not in warnings
    assert ("structure", f"{PATH}:14") in warnings  # 缺 origin 列

    bad = text.replace("| 12 | paper_0001::5.2 Comparison::12 |", "| twelve | paper_0001::5.2 Comparison::12 |")
    claude.write(PATH, bad)
    assert rules(claude.check_in(PATH)) == [("schema", f"{PATH}:17")]

    claude.write(PATH, text)
    done = claude.check_in(PATH, message="Declare metrics; fix two numbers.", confirm=True)
    entry = done["items"][0]
    assert entry["version"] == 4 and entry["warnings"]
    assert entry["notes"]["rows_by_contributor"] == [{"editor": "claude", "rows": 2, "versions": [4]}]


def test_note_stats(writers: dict[str, Writer]) -> None:
    alice = writers["alice"]
    alice.write("stats.md", "---\ntype: Note\ntitle: Stats\nabs: Stats.\n---\nOne [exp_0001].\n\nTwo.\n")
    assert alice.check_in("stats.md")["items"][0]["stats"] == {"paragraphs": 2, "cited_paragraphs": 1}


def test_cited_artifact_has_a_newer_version(store: Store) -> None:
    latest = history(store, "art_0001")[-1].material["id"]  # art_0002 引的是 v3，之后有了 v4
    reasons = stale(store, ["art_0002"])["art_0002"]
    assert reasons == [{"ref": "art_0001#method_0002++paper_0001+96+336", "reason": "superseded", "by": latest}]


def test_paper_new_version_supersedes_rows(store: Store, writers: dict[str, Writer]) -> None:
    v2 = MATERIAL.replace("paper.md", "v2/paper.md")
    file = store.material_root / v2
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text("".join(f"line {i} (v2)\n" for i in range(1, 61)), encoding="utf-8")
    new = commit_doc(store, f"graph-doc: v0.2\nset:\n  paper_0001:\n    material: {v2}\n")
    assert new["status"] == "committed", new

    reasons = stale(store, ["art_0001"])["art_0001"]
    assert {r["reason"] for r in reasons} == {"superseded"}
    assert {r["ref"] for r in reasons} >= {"paper_0001::5.2 Comparison::10:12", "paper_0001::5.2 Comparison::12:12"}
    item = writers["bob"].fetch("art_0001")["items"][0]
    assert [s["at"] for s in item["notes"]["superseded_sources"]] == [16, 17]


def test_search_finds_artifacts(store: Store) -> None:
    found = search(store, "ETTh1 multivariate forecasting", kind=["Leaderboard"]).details["results"]
    assert list(found) == ["art_0001"]
    mixed = search(store, "ETTh1").details["results"]
    assert "art_0001" in mixed and "dataset_0001" in mixed


NEW_EXPERIMENT = """graph-doc: v0.2
create:
  $ili:
    kind: Dataset
    name: ILI
    description: Weekly influenza-like illness ratios.
  $exp:
    kind: Experiment
    paper: paper_0001
    anchor: [20:30]
    figures: [S5.T3]
    description: DLinear on ETTh1 and ILI with a longer look-back window.
    EVALUATES:
      method_0002: {role: target}
    USES:
      dataset_0001: {role: evaluation_data}
      $ili: {role: evaluation_data}
    ON_TASK:
      task_0001:
"""


def test_commit_lists_related_leaderboards(writers: dict[str, Writer]) -> None:
    alice = writers["alice"]
    done = alice.commit(NEW_EXPERIMENT)
    assert done["status"] == "committed", done
    shared = done["related_artifacts"]
    assert shared["experiments"] == [done["ids"]["$exp"]]
    [board] = shared["leaderboards"]
    assert board["artifact"] == "art_0001" and board["version"] == 4 and board["last_edited_by"] == "claude"
    ili = done["ids"]["$ili"].split()[0]  # "dataset_0002 (ILI)"
    assert shared["no_leaderboard_yet"] == [{"dataset": ili, "name": "ILI"}]

    note = f"graph-doc: v0.2\nset:\n  {ili}:\n    description: Weekly ILI ratios (US).\n"
    plain = alice.commit(note)
    assert plain["status"] == "committed" and "related_artifacts" not in plain  # 没有触及 Experiment


def test_repeated_warnings_are_grouped() -> None:
    item = Item(Draft("lb.md", ""), lines=[1, 2, 4, 5, 6, 7, 9])  # 去掉 id、base 两行后的行号 → 写者文件中的行号
    same = "lookback 'searched in {24, 48}' is not a number; fine if the paper states it so"
    item.warnings = [("format", 2, same), ("format", 3, same), ("number", 4, "0.5 not in the cited lines"),
                     ("format", 4, same), ("format", 7, same)]
    assert item.grouped_warnings() == [
        {"rule": "format", "at": "lb.md:2, 4-5, 9", "msg": same, "count": 4},
        {"rule": "number", "at": "lb.md:5", "msg": "0.5 not in the cited lines"},
    ]
