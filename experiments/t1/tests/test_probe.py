"""读者探针：金标准与原文一致，有效范围随检查点扩大，回答与轨迹的提取，数值判分。"""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from e09.config import REPO
from t1.grade import claims_in, grade, numbers_in
from t1.probe import answer_of, audit, baseline_prompt, check_anchors, eligible, excerpt, gold_at, load, reader_prompt
from t1.source_tables import lookup, same_method

CONFIG = yaml.safe_load((REPO / "experiments/t1/config/pilot-ltsf.yml").read_text(encoding="utf-8"))
PROBES = load()
BY_ID = {p["id"]: p for p in PROBES["probes"]}
MATERIAL = REPO / CONFIG["corpus"]["material_root"]


def test_every_gold_value_is_on_its_anchor_line() -> None:
    assert check_anchors(PROBES, MATERIAL) == []


def test_probes_become_eligible_once_their_papers_are_written() -> None:
    counts = [len(eligible(PROBES["probes"], CONFIG, k)) for k in (1, 2, 3, 4)]
    assert counts == [3, 13, 18, 20]
    assert "B3" not in [p["id"] for p in eligible(PROBES["probes"], CONFIG, 3)]  # CATS 是第 7 篇


def test_gold_keeps_only_papers_written_by_the_checkpoint() -> None:
    c1 = BY_ID["C1"]
    assert [v["value"] for v in gold_at(c1, CONFIG, 2)["values"]] == [0.370, 0.375]  # 只有 PatchTST 原文
    assert 0.379 in [v["value"] for v in gold_at(c1, CONFIG, 3)["values"]]  # TiDE 写入后出现分歧
    assert len(gold_at(c1, CONFIG, 4)["values"]) == 6


def test_version_event_switches_gold_and_grading_at_the_event_checkpoint() -> None:
    g1 = BY_ID["G1"]
    assert 0.536 in [v["value"] for v in gold_at(g1, CONFIG, 2)["values"]]  # 检查点 2：库由 v3 写成
    assert 0.727 in [v["value"] for v in gold_at(g1, CONFIG, 3)["values"]] and len(gold_at(g1, CONFIG, 3)["rubric"]) == 1
    answer = "```claims\nFiLM | FiLM | Exchange | 720 | MSE | 0.536\n2205.08897v3 | FiLM | Exchange | 720 | MSE | 0.536\n```"
    record = {"arm": "A3", "condition": "store_only", "probe": "G1", "answer": answer}
    before, after = (grade({**record, "checkpoint": k}, g1, CONFIG) for k in (2, 3))
    assert [c["status"] for c in before["claims"]] == ["supported", "supported"]
    assert [c["status"] for c in after["claims"]] == ["outdated", "supported"]  # 简称指当前版本；写明 v3 的照实
    assert sum(v["hit"] for v in before["values"]) == 1 and sum(v["hit"] for v in after["values"]) == 0


def test_prompts_differ_between_arms_only_in_the_store_sentence() -> None:
    for condition in ("store_only", "with_papers"):
        a3, a0 = (reader_prompt(PROBES, arm, BY_ID["A1"], condition).split("\n") for arm in ("A3", "A0"))
        assert [i for i, (x, y) in enumerate(zip(a3, a0, strict=True)) if x != y] == [0]
    assert "not available" in reader_prompt(PROBES, "A0", BY_ID["A1"], "store_only")
    assert "./papers" in reader_prompt(PROBES, "A0", BY_ID["A1"], "with_papers")
    closed = baseline_prompt(PROBES, "closed_book", BY_ID["A2"], MATERIAL)
    assert "./store" not in closed and "```claims" in closed


def test_oracle_table_rows_come_with_caption_and_header() -> None:
    oracle = baseline_prompt(PROBES, "oracle", BY_ID["A2"], MATERIAL)
    block = oracle.split("[2304.08424v5, lines 223-223]\n", 1)[1]
    lines = block.split("\n")
    assert lines[0].startswith('<a id="S5.T2"') and lines[1].startswith("| Models |  | TiDE |")
    assert lines[3].startswith("| Metric |") and lines[4] == "…" and lines[5].startswith("| Traffic | 96 | 0.336")
    text = (MATERIAL / "papers/2211.14730v2/paper.md").read_text(encoding="utf-8").splitlines()
    assert excerpt(text, 164, 164) == text[163]  # 不在表中：原样


def test_table_index_reads_the_cell_under_each_method() -> None:
    cells = lookup(MATERIAL, "2310.09751", "ETTh1", 96, "MSE")  # 版本号可省；方法行在分组行之下
    assert {(c.header, c.value) for c in cells if same_method("PatchTST", c.header)} == {("PatchTST^∗", 0.404), ("PatchTST^†", 0.409)}
    assert not same_method("Autoformer", "Autoformer-CI") and same_method("PatchTST", "PatchTST/64")


def test_answer_and_audit_come_from_the_event_stream(tmp_path: Path) -> None:
    def assistant(*content: dict) -> dict:
        return {"type": "message_end", "message": {"role": "assistant", "content": list(content)}}

    events = [
        assistant({"type": "toolCall", "name": "mcp__PaperWeave__Search", "arguments": {"query": "PatchTST"}}),
        assistant({"type": "toolCall", "name": "read", "arguments": {"path": "papers/2211.14730v2/paper.md"}}),
        assistant({"type": "toolCall", "name": "bash", "arguments": {"command": "ls store"}}),
        assistant({"type": "toolCall", "name": "read", "arguments": {"path": "store/papers/patchtst-2211-14730.md"}}),
        assistant({"type": "text", "text": "PatchTST/64 reports 0.37 MSE."}),
    ]
    path = tmp_path / "e.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    assert answer_of(path) == "PatchTST/64 reports 0.37 MSE."
    assert audit(path) == {"tools": {"Search": 1, "read": 2, "bash": 1}, "paper_reads": 1}  # 笔记不算原文


def test_values_are_graded_as_source_pairs_from_the_claims_block() -> None:
    assert numbers_in("MSE 0.37 (L=512), MAE .400; v1.2.3") == [0.37, 0.4, 1.2]  # 版本号不拆成两个数
    answer = """PatchTST reports 0.370; TiDE re-ran it.

```claims
paper | method | dataset | horizon | metric | value
2211.14730 | PatchTST/64 | ETTh1 | 96 | MSE | 0.370
TiDE | PatchTST | ETTh1 | 96 | MSE | 0.375
PatchTST | PatchTST/42 | ETTh1 | 96 | MSE | 0.3752
Informer | PatchTST | ETTh1 | 96 | MSE | 0.401
Nie et al. | PatchTST | ETTh1 | 96 | MSE | 0.370
2021-PatchTST | PatchTST/42 (L=336) | ETTh1 | 96 | mse (multivariate, table 3) | 0.375
SCINet | Autoformer | ETTh2 | 24 | MSE | 0.260
```"""
    record = {"arm": "A3", "condition": "store_only", "checkpoint": 3, "probe": "C1", "answer": answer}
    g = grade(record, BY_ID["C1"], CONFIG)
    # TiDE 一行的 0.375 是 TiDE 自己的数，不是它报告的 PatchTST（0.379）：不命中，记为出处错
    assert [v["hit"] for v in g["values"]] == [True, True, False, False] and g["value_recall"] == 0.5
    statuses = [c["status"] for c in g["claims"]]
    assert statuses == ["supported", "misattributed", "supported", "unsupported", "unknown_paper", "supported", "unchecked"]
    # 0.3752 在多种子表中；SCINet 的表是转置的，没有建索引，不计入精确率
    assert g["claim_precision"] == 0.5 and [r["pass"] for r in g["rubric"]] == [None, None]
    assert claims_in("no block") is None and claims_in("```claims\nnone\n```") == []
    assert grade({**record, "probe": "E2"}, BY_ID["E2"], CONFIG)["dynamic"]["recalled"] is None
    d1 = grade({**record, "probe": "D1", "answer": "P+CI 0.367, CI 0.397"}, BY_ID["D1"], CONFIG)
    assert [v["hit"] for v in d1["values"]] == [True, True, False]  # 消融变体只看数值


def test_store_only_a3_readers_read_artifact_documents_but_not_papers(tmp_path: Path) -> None:
    from t1.probe import _reader_arm
    from t1.sandbox import Paths, Writer, _mcp_command

    reader = Writer("reader", "reader@example", "pi/test")
    store_only = _reader_arm(tmp_path, CONFIG, "A3", 1, "store_only", at_head=True)
    assert store_only.papers is None and store_only.hide_tools == () and store_only.evidence_scope == "artifacts"
    assert "E09_EVIDENCE_SCOPE=artifacts" in _mcp_command(Paths(tmp_path), store_only, reader)
    with_papers = _reader_arm(tmp_path, CONFIG, "A3", 1, "with_papers", at_head=True)
    assert with_papers.evidence_scope is None
    assert not any(a.startswith("E09_EVIDENCE_SCOPE") for a in _mcp_command(Paths(tmp_path), with_papers, reader))


def test_paper_names_readers_write_resolve_to_corpus_ids() -> None:
    from t1.grade import paper_aliases, paper_of

    aliases = paper_aliases(CONFIG, 2)
    assert paper_of("2106.13008 (Autoformer)", aliases) == "2106.13008v5"
    assert paper_of("patchtst-2211-14730", aliases) == "2211.14730v2"  # A0 笔记的文件名
    assert paper_of("2205.08897v4", aliases) == "2205.08897v4" and paper_of("FiLM", aliases) == "2205.08897v3"
    assert paper_of("2021-Autoformer", aliases) == "2106.13008v5" and paper_of("nonsense-1234", aliases) is None
