"""知识访问（search、get、traverse、read_evidence）与写入（checkout、commit）在测试实例上的端到端检验。

模块内的测试按顺序共享库：前面的测试只读，后面的写入。
"""

from __future__ import annotations

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
        f"  {e['at'].split('create.')[1].rstrip(')')}: {{distinct_from: [{', '.join(c['id'] for c in e['candidates'])}]}}"
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
    assert node["paper"] == "paper_0001" and node["anchor"] == ["12:20"]
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
    items = writer.call("read_evidence", source_refs=["paper_0001::12:13", "paper_0001::5.2 Comparison::12:12"]).details["items"]
    assert [i["state"] for i in items] == ["available", "available"]
    assert items[0]["section"] == "5.2 Comparison" and "12| comparison line 12" in items[0]["text"]


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
    assert candidates[0]["id"] == "method_0003" and len(candidates) <= 4  # 名称命中在前，另有至多 3 个近邻
    assert writer.commit(confirmed(writer, doc), dry_run=True)["status"] == "ready"


def test_commit_then_search_sees_it(writer: Writer) -> None:
    doc = """graph-doc: v0.2
create:
  $patchtst:
    kind: Method
    name: PatchTST
    description: Channel-independent patch Transformer for long-term forecasting.
  exp_0001:
    EVALUATES:
      $patchtst: {role: baseline, result: cited, anchor: [14:15]}
"""
    done = writer.commit(confirmed(writer, doc))
    assert done["status"] == "committed", done
    new = done["ids"]["$patchtst"].split()[0]
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


def test_an_arxiv_identity_has_no_version(writer: Writer) -> None:
    doc = "graph-doc: v0.2\ncreate:\n  $p:\n    kind: Paper\n    name: Some paper\n    stub: true\n    identities: [arxiv:2211.14730v2]\n"
    blocked = writer.commit(doc, dry_run=True)
    assert blocked["status"] == "blocked" and "arxiv:2211.14730 " in blocked["errors"][0]["msg"]
