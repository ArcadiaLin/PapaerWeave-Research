"""库健康度：原文表格的解析（合并表头、引文链接、标准差、论文自己的简称），笔记中结果表的抽取，覆盖与重复候选。

不连库、不用 git：A3 的变更记录用最小的替身。"""

from __future__ import annotations

from types import SimpleNamespace as NS

import yaml

from t1.grade import paper_aliases
from t1.health import Fact, _cited_lines, _note_facts, a3_overwrites, candidates, fidelity
from t1.paths import REPO
from t1.source_tables import lookup, same_method

CONFIG = yaml.safe_load((REPO / "experiments/t1/config/pilot-ltsf.yml").read_text(encoding="utf-8"))
MATERIAL = REPO / CONFIG["corpus"]["material_root"]
ALIASES = paper_aliases(CONFIG)


def _cell(arxiv: str, dataset: str, horizon: int, metric: str, method: str) -> list[float]:
    return [c.value for c in lookup(MATERIAL, arxiv, dataset, horizon, metric) if same_method(method, c.header)]


def test_source_tables_read_the_corpus_header_variants() -> None:
    assert _cell("2107.08687v2", "ETTh1", 24, "mse", "Informer") == [0.098, 0.577]  # Informer<br>MSE；单变量与多变量两表
    assert 0.719 in _cell("2106.13008v5", "Traffic", 96, "mse", "Informer")  # Informer[[48](#bib.bib48)]
    assert 0.255 in _cell("2106.13008v5", "ETTm2", 96, "mse", "Autoformer")  # Autoformer 的 ETT* 即 ETTm2
    assert _cell("2106.13008v5", "ETTm2", 96, "mse_std", "Autoformer") == [0.020]  # 0.255<br>$\pm$0.020
    assert 0.197 in _cell("2106.13008v5", "Exchange-Rate", 96, "mse", "Autoformer")  # 表中写作 Exchange
    assert 0.247 in _cell("2012.07436v3", "ETTh1", 24, "mae", "Informer")  # 一格两个指标：0.098  0.247


def test_fidelity_separates_wrong_values_from_wrong_anchors() -> None:
    def fact(value: float, lines: tuple[int, int] | None, metric: str = "MSE") -> Fact:
        return Fact("2106.13008v5", "Autoformer", "ETTm2", 96, metric, value, lines, "x")

    result = fidelity(
        [fact(0.255, (291, 291)), fact(0.255, (293, 293)), fact(0.020, (291, 291), "MSE_std"), fact(0.999, None)],
        MATERIAL,
        ALIASES,
    )
    assert result["status"] == {"supported": 3, "unsupported": 1}
    assert result["anchor"] == {"ok": 1, "near": 1, "off": 1, "none": 0}  # 标准差在表 10（第 821 行），引的是表 1


def test_note_tables_become_facts_with_the_cited_lines() -> None:
    lines = [
        "### Results (Table 3, lines 169-199)",
        "",
        "| Dataset | Horizon | PatchTST/64 MSE | PatchTST/64 MAE | MSE ratio |",
        "| --- | --- | --- | --- | --- |",
        "| ETTh1 | 96 | 0.370 | 0.400 | 0.9 |",
        "|  | 192 | 0.413 | 0.429 | 0.9 |",
    ]
    span = _cited_lines(lines, 2)
    facts = _note_facts(lines[2:], "2211.14730v2", span, "n.md:3")
    assert span == (169, 199) and len(facts) == 4  # MSE ratio 不是结果数值
    assert (facts[2].dataset, facts[2].horizon, facts[2].method, facts[2].metric) == ("ETTh1", 192, "PatchTST/64", "MSE")
    assert fidelity(facts, MATERIAL, ALIASES)["status"] == {"supported": 4}


def test_overwrites_count_only_other_writers_after_the_seed() -> None:
    def record(id_: str, author: str, *changes: NS, revisions: dict | None = None) -> NS:
        return NS(id=id_, author=author, meta={"revisions": revisions or {}}, changeset=NS(nodes=list(changes)))

    def change(id_: str, op: str, before: dict | None = None, after: dict | None = None) -> NS:
        return NS(id=id_, op=op, before=before, after=after)

    history = [
        record("c1", "seed", change("m1", "create", None, {"name": "X", "definition": "a"})),
        record("c2", "w1", change("m2", "create", None, {"name": "Y", "value": 0.4})),
        record("c3", "w1", change("m1", "update", {"definition": "a"}, {"definition": "b", "embedding": "e"})),
        record("c4", "w2", change("m2", "update", {"value": 0.4}, {"value": 0.5}), revisions={"m2": "anchor"}),
        record("c5", "w2", change("m2", "update", {"value": 0.5}, {"value": 0.6})),
    ]
    out = a3_overwrites(history, since="c1", until="c4")
    assert [(i["commit"], i["kind"], i["reason"]) for i in out["items"]] == [("c3", "text", False), ("c4", "value", True)]
    assert out["without_reason"] == 1 and out["value"] == 1 and out["text"] == 1


def test_duplicate_candidates_group_variants_but_not_lookalikes() -> None:
    groups = candidates([
        ("Method", "a", "PatchTST"), ("Method", "b", "PatchTST/64"), ("Method", "c", "N-BEATS"),
        ("Method", "d", "N-HiTS"), ("Dataset", "e", "Exchange"), ("Dataset", "f", "Exchange-Rate"),
    ])  # fmt: skip
    assert [[m["id"] for m in g["members"]] for g in groups] == [["e", "f"], ["a", "b"]]


def test_note_tables_with_paired_cells_take_the_table_anchor_over_other_line_numbers() -> None:
    lines = [
        "## Experiment S4.T1",
        "- **anchors:** S4.T1",
        "- Implementation details are at Implementation details::320:324 (not the table).",
        "**Results** (MSE / MAE)",
        "| Dataset | O | Autoformer | Informer |",
        "|---|---|---|---|",
        "| ETT (ETim2) | 96 | 0.255 / 0.339 | 0.365 / 0.453 |",
    ]
    paper = (MATERIAL / "papers/2106.13008v5/paper.md").read_text(encoding="utf-8").splitlines()
    span = _cited_lines(lines, 4, paper)
    assert span is not None and span[0] == 287  # 原文中 <a id="S4.T1"> 所在行到表尾
    facts = _note_facts(lines[4:], "2106.13008v5", span, "n.md:5", "\n".join(lines[1:4]))
    assert [(f.method, f.metric, f.value) for f in facts] == [
        ("Autoformer", "MSE", 0.255), ("Autoformer", "MAE", 0.339), ("Informer", "MSE", 0.365), ("Informer", "MAE", 0.453)
    ]
    # 笔记把 ETTm2 写错成 “ETT (ETim2)”：按原文自己的叫法 ETT 认出（Autoformer 的 ETT 即 ETTm2）
    assert fidelity(facts, MATERIAL, ALIASES)["status"] == {"supported": 4}
