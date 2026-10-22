"""知识访问（search、get、traverse、read_evidence）与写入（checkout、commit）在测试实例上的端到端检验。

模块内的测试按顺序共享库：前面的测试只读，后面的写入。
"""

from __future__ import annotations

import pytest
import yaml
from conftest import Writer

from graph_doc import load
from paperweave.store import Store


def results(writer: Writer, **params: object) -> dict[str, dict]:
    return writer.call("search", **params).details["results"]


def confirmed(writer: Writer, doc: str) -> str:
    """把查重给出的候选都确认为不同（新节点确实是新的时，写者要做的就是这一步）。"""
    checked = writer.commit(doc, dry_run=True)
    lines = [
        f"  {e['at'].split('create.')[1].rstrip(')')}: {{distinct_from: [{', '.join(e['candidates'])}]}}"
        for e in checked.get("errors", [])
        if e["rule"] == "dedup"
    ]
    return doc + "confirm:\n" + "\n".join(lines) + "\n" if lines else doc


# ── search ───────────────────────────────────────────────────────────


def test_exact_matches_come_first(writer: Writer) -> None:
    found = results(writer, query="dlinear")
    assert list(found)[0] == "method_0003" and found["method_0003"]["_match"] == "name"
    assert list(results(writer, query="LTSF"))[0] == "task_0001"  # 别名
    by_arxiv = results(writer, query="2205.13504")  # 不带命名空间的 arXiv 号
    assert list(by_arxiv)[0] == "paper_0001" and by_arxiv["paper_0001"]["_match"] == "identity"


def test_filters(writer: Writer) -> None:
    assert set(results(writer, query="DLinear Transformer", kind=["Content"])) <= {"exp_0001", "claim_0001", "contrib_0001"}
    assert set(results(writer, query="linear", kind=["Method"])) <= {"method_0001", "method_0002", "method_0003"}
    assert results(writer, query="linear", kind="Experiment", paper=["paper_9999"]) == {}


def test_a_described_relation_is_found_under_its_start(writer: Writer) -> None:
    found = results(writer, query="simple baseline that questions Transformer forecasters", kind=["RELATES_TO"])
    assert "method_0003" in found and "method_0001" in found["method_0003"]["RELATES_TO"]


def test_results_are_commented_yaml(writer: Writer) -> None:
    text = writer.call("search", query="ETTh1").text
    assert text.startswith("# search 'ETTh1'") and "# ETTh1" in text
    assert isinstance(load(text), dict)  # 去掉注释仍是合法的 YAML


# ── get、traverse、read_evidence ──────────────────────────────────────


def test_get_gives_fields_edges_and_sections(writer: Writer) -> None:
    out = writer.call("get", ids=["exp_0001", "nope_0001"])
    node = out.details["nodes"]["exp_0001"]
    assert node["paper"] == "paper_0001" and node["anchor"] == ["2205.13504v1::12:20"]
    assert node["EVALUATES"]["method_0003"] == {"role": "target", "result": "own"}
    assert out.details["missing"] == ["nope_0001"]
    assert "# 5.2 Comparison" in out.text and "# DLinear" in out.text


def test_traverse_walks_hops_with_via(writer: Writer) -> None:
    out = writer.call("traverse", start=["method_0003"], path=[{"rel": "EVALUATES", "dir": "in"}, {"rel": "USES"}])
    assert list(out.details["nodes"]) == ["dataset_0001"]
    assert out.details["nodes"]["dataset_0001"]["_via"] == {"exp_0001": {"USES": {"role": "evaluation_data", "printed_as": "ETTh1"}}}
    concepts = writer.call("traverse", start=["method_0003"], path=[{"rel": "BROADER"}]).details["nodes"]
    assert list(concepts) == ["method_0002"]
    wrong = writer.call("traverse", start=["method_0003"], path=[{"rel": "EVALUATED_ON"}])
    assert wrong.is_error and wrong.details["errors"][0]["at"] == "path[0].rel"


def test_read_evidence_without_a_section(writer: Writer) -> None:
    items = writer.call("read_evidence", source_refs=["2205.13504v1::12:13", "2205.13504v1::5.2 Comparison::12:12"]).details["items"]
    assert [i["state"] for i in items] == ["available", "available"]
    assert items[0]["source"] == "2205.13504v1"
    assert items[0]["section"] == "5.2 Comparison" and "12| comparison line 12" in items[0]["text"]


def test_read_evidence_reads_sources_by_id_only(writer: Writer) -> None:
    by_paper, unopened, whole, bare = writer.call(
        "read_evidence", source_refs=["paper_0001::12:13", "2301.00001v1::1:2", "2205.13504v1", "12:13"]
    ).details["items"]
    assert by_paper["state"] == "missing" and "the source of paper_0001: 2205.13504v1" in by_paper["reason"]
    assert unopened["state"] == "missing" and "not an available source" in unopened["reason"]
    assert whole["state"] == "missing" and "<start>:<end>" in whole["reason"]
    assert bare["state"] == "missing"


# ── checkout 与 commit ───────────────────────────────────────────────


def test_checkout_round_trips_to_a_noop(writer: Writer) -> None:
    out = writer.call("checkout", ids=["exp_0001", "method_0003"], new=["Claim"]).details
    edit, template = out["files"]
    assert writer.commit((writer.root / edit["path"]).read_text(), name=edit["path"])["status"] == "noop"
    blank = yaml.safe_load((writer.root / template["path"]).read_text())
    assert blank["create"]["$new_claim"]["kind"] == "Claim"


def test_a_new_name_that_exists_is_a_dedup_error(writer: Writer, store: Store) -> None:
    doc = "graph-doc: v0.2\ncreate:\n  $d:\n    kind: Method\n    name: D-Linear\n    description: A linear model.\n"
    blocked = writer.commit(doc)
    assert blocked["status"] == "blocked" and blocked["errors"][0]["rule"] == "dedup"
    candidates = blocked["errors"][0]["candidates"]
    assert list(candidates)[0] == "method_0003" and len(candidates) <= 4  # 名称命中在前，另有至多 3 个近邻
    assert writer.commit(confirmed(writer, doc), dry_run=True)["status"] == "ready"


def test_commit_then_search_sees_it(writer: Writer, store: Store) -> None:
    doc = """graph-doc: v0.2
create:
  $patchtst:
    kind: Method
    name: PatchTST
    description: Channel-independent patch Transformer for long-term forecasting.
  exp_0001:
    EVALUATES:
      $patchtst: {role: baseline, result: cited, anchor: [2205.13504v1::14:15]}
"""
    judged = confirmed(writer, doc)
    done = writer.commit(judged)
    assert done["status"] == "committed", done
    new = done["ids"]["$patchtst"].split()[0]
    apart = load(judged)["confirm"]["$patchtst"]["distinct_from"]  # 查重给出的候选都判断为不同
    meta = store.graph.get_commit(done["commit"]).meta
    assert meta["confirmations"] == {new: {"distinct_from": apart}}  # 写者的判断按 id 记在提交上
    assert list(results(writer, query="PatchTST"))[0] == new  # 提交后补算了检索字段
    again = writer.commit(doc.replace("$patchtst", new).replace(f"  {new}:\n    kind: Method\n    name: PatchTST\n    description: Channel-independent patch Transformer for long-term forecasting.\n", ""))
    assert again["status"] == "noop"  # 同样的边已在，属性相同


def test_edges_on_records_need_anchors(writer: Writer) -> None:
    doc = "graph-doc: v0.2\ncreate:\n  exp_0001:\n    USES:\n      dataset_0001: {role: evaluation_data}\n"
    assert writer.commit(doc, dry_run=True)["status"] == "noop"  # 已在
    doc = "graph-doc: v0.2\ncreate:\n  claim_0001:\n    ABOUT:\n      task_0001:\n"
    blocked = writer.commit(doc, dry_run=True)
    assert blocked["status"] == "blocked" and blocked["errors"][0]["rule"] == "revision"
    assert blocked["errors"][0]["at"].startswith("doc.yaml:")



def test_an_edge_with_two_roles_writes_role_as_a_list(writer: Writer) -> None:
    doc = (
        "graph-doc: v0.2\nset:\n  exp_0001:\n    USES:\n      dataset_0001: {role: [training_data, evaluation_data]}\n"
        "confirm:\n  exp_0001: {revise: {reason: \"the model is also trained on this dataset\", anchor: [2205.13504v1::12:20]}}\n"
    )
    assert writer.commit(doc, dry_run=True)["status"] == "ready"
    bad = writer.commit(doc.replace("training_data", "train"), dry_run=True)
    assert "a list when it plays two roles" in bad["errors"][0]["msg"]

def test_an_arxiv_identity_has_no_version(writer: Writer) -> None:
    doc = "graph-doc: v0.2\ncreate:\n  $p:\n    kind: Paper\n    name: Some paper\n    stub: true\n    identities: [arxiv:2211.14730v2]\n"
    blocked = writer.commit(doc, dry_run=True)
    assert blocked["status"] == "blocked" and "arxiv:2211.14730 " in blocked["errors"][0]["msg"]


def test_an_anchor_on_a_line_without_text_blocks(writer: Writer) -> None:
    doc = "graph-doc: v0.2\ncreate:\n  claim_0001:\n    ABOUT:\n      task_0001: {anchor: [2205.13504v1::61:61]}\n"
    blocked = writer.commit(doc, dry_run=True)
    assert blocked["status"] == "blocked"
    assert any("nearest line with text is 60" in e["msg"] for e in blocked["errors"]), blocked


def test_a_reversed_edge_says_how_to_write_it(writer: Writer) -> None:
    doc = "graph-doc: v0.2\ncreate:\n  claim_0001:\n    SUPPORTS:\n      exp_0001: {anchor: [2205.13504v1::12:13]}\n"
    blocked = writer.commit(doc, dry_run=True)
    assert "write it the other way, under exp_0001: SUPPORTS: {claim_0001: ...}" in blocked["errors"][0]["msg"]


def test_evaluating_a_model_without_identities_warns_unless_stub(writer: Writer) -> None:
    doc = """graph-doc: v0.2
create:
  $m:
    kind: Model
    name: DLinear-trained
    description: The DLinear weights trained in this paper.
    IMPLEMENTS:
      method_0003:
  exp_0001:
    EVALUATES:
      $m: {role: target, result: own, anchor: [2205.13504v1::12:13]}
confirm:
  $m: {distinct_from: []}
"""
    checked = writer.commit(doc, dry_run=True)
    assert checked["status"] == "ready", checked  # 提示，不阻塞
    assert any(w["rule"] == "model" and "usually the Method (method_0003)" in w["msg"] for w in checked["warnings"]), checked
    stub = doc.replace("    description: The DLinear weights trained in this paper.\n", "    stub: true\n")
    assert not [w for w in writer.commit(stub, dry_run=True).get("warnings", []) if w["rule"] == "model"]


def test_anchors_on_an_older_version_are_marked(store: Store, writer: Writer) -> None:
    older = (store.sources.root / "2205.13504v1/paper.md").read_text(encoding="utf-8")
    newer = store.sources.root / "2205.13504v2/paper.md"
    newer.parent.mkdir(parents=True, exist_ok=True)
    newer.write_text(older + "Appendix line 62\n", encoding="utf-8")
    moved = writer.commit("graph-doc: v0.2\nset:\n  paper_0001:\n    source: [2205.13504v1, 2205.13504v2]\n")
    assert moved["status"] == "committed", moved
    view = writer.call("get", ids=["exp_0001", "method_0003"]).details["nodes"]
    note = view["exp_0001"]["_anchor_version"]
    # 前面的测试给 exp_0001 加过一条带锚点的 EVALUATES：记录本身与这条边的锚点都写在旧版本上
    assert note.startswith("anchor, EVALUATES method_0004 cite 2205.13504v1; paper_0001 now also has the newer version 2205.13504v2")
    assert "_anchor_version" not in view["method_0003"]

    rewritten = """graph-doc: v0.2
set:
  exp_0001:
    anchor: [2205.13504v2::12:21]
confirm:
  exp_0001: {revise: {reason: "the table runs to line 21 in the new version", anchor: [2205.13504v2::12:21]}}
"""
    assert writer.commit(rewritten)["status"] == "committed"  # 改写记录的锚点：它换到新版本，边的锚点还在旧版本上
    note = writer.call("get", ids=["exp_0001"]).details["nodes"]["exp_0001"]["_anchor_version"]
    assert note.startswith("EVALUATES method_0004 cite 2205.13504v1;")


def test_a_revision_in_the_commit_that_adds_the_version_anchors_in_the_new_one(store: Store, writer: Writer) -> None:
    older = (store.sources.root / "2205.13504v2/paper.md").read_text(encoding="utf-8")
    total = len(older.splitlines())
    newer = store.sources.root / "2205.13504v3/paper.md"
    newer.parent.mkdir(parents=True, exist_ok=True)
    newer.write_text(older + "Appendix table, first row\nAppendix table, second row\n", encoding="utf-8")
    lines = f"2205.13504v3::{total + 1}:{total + 2}"  # 只在新版本中存在的行
    doc = f"""graph-doc: v0.2
set:
  paper_0001:
    source: [2205.13504v1, 2205.13504v2, 2205.13504v3]
  exp_0001:
    anchor: [{lines}]
confirm:
  exp_0001: {{revise: {{reason: "the table moved to the appendix in the new version", anchor: [{lines}]}}}}
"""
    assert writer.commit(doc.replace(", 2205.13504v3]", "]"), dry_run=True)["status"] == "blocked"  # 还没声明 v3
    assert writer.commit(doc)["status"] == "committed"


def test_get_and_traverse_page_like_read(writer: Writer, monkeypatch: pytest.MonkeyPatch) -> None:
    first = writer.call("get", ids=["exp_0001"], limit=1)
    evaluates = first.details["more"]["exp_0001"]["EVALUATES"]
    assert evaluates > 1 and len(first.details["nodes"]["exp_0001"]["EVALUATES"]) == 1
    assert "[Use offset=1 with ids=[exp_0001] to continue.]" in first.text
    second = writer.call("get", ids=["exp_0001"], offset=1, limit=1)
    assert list(second.details["nodes"]["exp_0001"]["EVALUATES"]) != list(first.details["nodes"]["exp_0001"]["EVALUATES"])
    assert writer.call("get", ids=["exp_0001"], limit=1).text == first.text  # 同样的参数，同样的一页

    path = [{"rel": "EVALUATES", "dir": "in"}, {"rel": "EVALUATES"}]
    whole = writer.call("traverse", start=["method_0003"], path=path).details
    assert whole["reached"] > 1 and whole["next"] is None
    head = writer.call("traverse", start=["method_0003"], path=path, limit=1)
    assert head.details["next"] == 1 and "Use offset=1 to continue." in head.text
    tail = writer.call("traverse", start=["method_0003"], path=path, offset=1, limit=100).details
    assert [*head.details["nodes"], *tail["nodes"]] == list(whole["nodes"])

    monkeypatch.setattr("paperweave.operators.db.get.BUDGET", 600)  # 预算小到放不下两个节点：按整节点截短
    cut = writer.call("get", ids=["method_0003", "dataset_0001"])
    assert list(cut.details["nodes"]) == ["method_0003"] and cut.details["rest"] == ["dataset_0001"]
    assert "Get the rest with ids=[dataset_0001]" in cut.text


def test_related_names_are_cut_in_a_fixed_order(store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    from paperweave.store import derived

    monkeypatch.setattr(derived, "NEIGHBOR_NAMES", 1)  # 只留一个：应是它自己指出去的边的终点中名称最小的
    rows = store.query(
        "MATCH ({id: 'exp_0001'})-[r]->(m:Searchable) WHERE type(r) <> 'USED' RETURN coalesce(m.name, m.title) AS name"
    )
    first = min(r["name"] for r in rows if r["name"])
    texts = [derived.node_texts(store.driver, None, ["exp_0001"])[0]["search_text"] for _ in range(2)]
    assert texts[0] == texts[1] and texts[0].endswith(f"related: {first}")


def test_derived_texts_follow_a_rename_without_a_full_pass(writer: Writer, store: Store) -> None:
    from paperweave.store.derived import edge_texts, node_texts

    renamed = writer.commit("graph-doc: v0.2\nset:\n  method_0001:\n    name: Transformer forecasters\n")
    assert renamed["status"] == "committed", renamed
    texts = {n["id"]: n for n in node_texts(store.driver, None)}
    assert "Transformer forecasters" in texts["exp_0001"]["stored"]  # 邻居的 related 跟着改名
    # 提交后只重算了受影响的对象；全量重算的结果与库中所存的完全相同
    assert [n["id"] for n in texts.values() if n["search_text"] != n["stored"]] == []
    assert [e["eid"] for e in edge_texts(store.driver, None) if e["search_text"] != e["stored"]] == []
