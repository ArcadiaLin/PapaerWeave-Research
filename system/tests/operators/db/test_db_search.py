"""Search：结构条件、查询通道与排序、续取、数据缺失、诊断、结果视图的摘录与容量、契约错误。"""

from __future__ import annotations

import dataclasses

import pytest
from conftest import problems

from paperweave.operators.db.search import find, search
from paperweave.query.excerpts import results
from paperweave.store import ContractError, Store


def ids(out: dict) -> list[str]:
    return [r["id"] for r in out["results"]]


def test_snapshot_is_the_head_the_results_were_read_at(store: Store) -> None:
    out = search(store, "Content", kinds=["Experiment"])
    assert out["meta"]["snapshot"] == store.graph.head() and "diagnostics" not in out["meta"]


def test_enumerates_by_structure_in_id_order(store: Store) -> None:
    out = search(store, "Content", kinds=["Experiment"], where={"evaluates": "method_0003", "role": "target"})
    assert ids(out) == ["exp_0001", "exp_0002"]
    assert find(store, "Content", kinds=["Experiment"]).coverage["order"] == "id"

    baseline = search(store, "Content", kinds=["Experiment"], where={"evaluates": "method_0002", "role": "baseline"})
    assert ids(baseline) == ["exp_0001"]
    stubs = search(store, "Concept", kinds=["Method"], where={"stub": False})
    assert ids(stubs) == ["method_0001", "method_0002", "method_0003"]


def test_conditions_on_the_same_record_are_conjunctive_and_lists_disjunctive(store: Store) -> None:
    both = search(store, "Content", kinds=["Experiment"], where={"uses": "dataset_0002", "evaluates": "method_0003"})
    assert ids(both) == ["exp_0001"]
    either = search(store, "Concept", where={"broader": ["method_0001", "task_0001"]}, kinds=["Method", "Task"])
    assert ids(either) == ["method_0003", "task_0002"]


def test_expand_parts_relaxes_a_dataset_reference(store: Store) -> None:
    plain = search(store, "Content", kinds=["Experiment"], where={"uses": "dataset_0001"})
    assert ids(plain) == []
    assert plain["meta"]["diagnostics"]["expandable"]["refs"] == ["exp_0001"]

    expanded = search(store, "Content", kinds=["Experiment"], where={"uses": "dataset_0001"}, expand={"parts": 1})
    assert ids(expanded) == ["exp_0001"]
    assert expanded["meta"]["expanded"] == {"dataset_0001": ["dataset_0002"]}


def test_uses_requires_the_evaluation_role_and_reports_missing_roles(store: Store) -> None:
    out = search(store, "Content", kinds=["Experiment"], where={"uses": "dataset_0003"})
    assert ids(out) == ["exp_0001"]
    assert out["meta"]["diagnostics"]["role_missing"] == {"count": 1, "refs": ["exp_0002"]}


def test_exact_name_hits_come_first(store: Store) -> None:
    found = find(store, "Concept", {"mention": "D-Linear"}, kinds=["Method"])
    assert found.page[0] == "method_0003"
    assert found.bindings["method_0003"] == {"exact": "name"}
    assert found.coverage["channels"]["semantic"] == "disabled"  # 测试中没有向量服务

    by_id = find(store, "Entity", {"identifier": "arxiv:2205.13504"})
    assert by_id.page == ["paper_0001"]
    assert by_id.bindings["paper_0001"] == {"exact": "identifier"}


def test_text_channel_ranks_within_the_conditions(store: Store) -> None:
    out = search(store, "Content", "decomposition ablation", kinds=["Experiment"])
    assert ids(out)[0] == "exp_0002"
    assert (
        find(store, "Content", "decomposition ablation", kinds=["Experiment"]).bindings["exp_0002"]["lexical_text"] == 1
    )

    scoped = search(store, "Content", "decomposition ablation", where={"uses": "dataset_0002"}, kinds=["Experiment"])
    assert ids(scoped) == []


def test_a_failing_channel_is_reported_not_treated_as_empty(store: Store) -> None:
    def embed(texts: list[str]) -> list[list[float]]:
        raise ConnectionError("embedding service unreachable")

    out = search(dataclasses.replace(store, embed=embed), "Concept", {"mention": "DLinear"})
    assert out["meta"]["failed"]["semantic"].startswith("error: ConnectionError")
    assert ids(out)[0] == "method_0003"


def test_an_identifier_alone_leaves_the_semantic_channel_off(store: Store) -> None:
    def embed(texts: list[str]) -> list[list[float]]:
        raise AssertionError("nothing to embed")

    found = find(dataclasses.replace(store, embed=embed), "Entity", {"identifier": "arxiv:2205.13504"}, kinds=["Paper"])
    assert found.page == ["paper_0001"]
    assert found.coverage["channels"]["semantic"] == "disabled"


def test_budget_and_continuation(store: Store) -> None:
    first = search(store, "Entity", kinds=["Dataset"], budget=2)
    assert ids(first) == ["dataset_0001", "dataset_0002"]
    rest = search(store, "Entity", kinds=["Dataset"], budget=2, continuation=first["meta"]["continuation"])
    assert ids(rest) == ["dataset_0003"]
    assert rest["meta"]["continuation"] is None


def test_scope_limits_content_to_papers(store: Store) -> None:
    out = search(store, "Content", kinds=["Experiment"], scope=["paper_0001"])
    assert ids(out) == ["exp_0001", "exp_0002"]
    first = out["results"][0]
    assert first["paper"] == "paper_0001" and first["source_refs"][0].startswith("material_")
    assert "EVALUATES" not in first and "FROM" not in first  # 结果不带关系，用 Traverse 读


def test_missing_references_return_an_empty_result(store: Store) -> None:
    out = search(store, "Content", kinds=["Experiment"], where={"evaluates": "method_0099"})
    assert ids(out) == []
    assert out["meta"]["missing"] == [{"ref": "method_0099", "param": "where.evaluates", "missing_in": "store"}]


def test_excerpts_share_the_size_limit(store: Store) -> None:
    page = ["exp_0001", "exp_0002"]
    state = store.graph.local_state(page)
    full = results("Content", state, page, 0, 2)
    assert full["meta"]["size"]["cut"] == 0
    original = {(r["id"], f): r[f] for r in full["results"] for f in ("text", "note") if f in r}

    limit = full["meta"]["size"]["used"] - 60
    tight = results("Content", state, page, 0, 2, limit=limit)
    assert tight["meta"]["size"]["used"] <= limit and tight["meta"]["size"]["cut"] >= 1
    for r in tight["results"]:
        for field in (k.removesuffix("_bytes") for k in r if k.endswith("_bytes")):
            text = original[r["id"], field]
            assert r[field].endswith("…") and text.startswith(r[field][:-1])
            assert r[f"{field}_bytes"] == len(text.encode())

    short = results("Content", state, page, 0, 2, limit=1)  # 识别字段都放不下：从末尾去掉结果
    assert ids(short) == ["exp_0001"] and short["meta"]["continuation"] == 1


def test_shares_are_even_and_short_excerpts_give_back() -> None:
    from paperweave.query.excerpts import _shares

    assert _shares([10, 100, 100], 150) == [10, 70, 70]
    assert _shares([10, 20], 100) == [10, 20]


@pytest.mark.parametrize(
    ("kwargs", "at"),
    [
        ({"type": "Paper"}, ["type"]),
        ({"type": "Artifact", "kinds": ["Check"]}, ["kinds"]),  # Artifact 没有 kind，用 where.op
        ({"type": "Artifact", "where": {"op": "Explain"}}, ["where.op"]),
        ({"type": "Artifact", "query": {"mention": "x"}}, ["query.mention"]),
        ({"type": "Concept", "where": {"evaluates": "method_0003"}}, ["where.evaluates"]),  # 只有 Experiment 能带
        ({"type": "Content", "where": {"evaluates": "method_0003"}}, ["where.evaluates"]),  # kinds 没有限定
        ({"type": "Content", "kinds": ["Experiment"], "where": {"evaluates": "dataset_0001"}}, ["where.evaluates"]),
        ({"type": "Content", "kinds": ["Experiment"], "where": {"role": "target"}}, ["where.role"]),
        ({"type": "Entity", "where": {"colour": "red"}}, ["where.colour"]),
        ({"type": "Content", "query": {"mention": "DLinear"}}, ["query.mention"]),
        ({"type": "Entity", "query": {"identifier": "isbn:123"}}, ["query.identifier"]),
        ({"type": "Entity", "scope": ["paper_0001"]}, ["scope"]),
        ({"type": "Entity", "budget": 0}, ["budget"]),
        ({"type": "Concept", "kinds": ["Dataset"]}, ["kinds"]),
    ],
)
def test_contract_errors(store: Store, kwargs: dict, at: list[str]) -> None:
    with pytest.raises(ContractError) as exc:
        search(store, **kwargs)
    assert problems(exc) == at
