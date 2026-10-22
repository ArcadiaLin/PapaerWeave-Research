"""只经库读原文（``anchored``）：论文只能读库中记录过的锚点所在的块（docs/designs/v3/evaluation.md §2.2）。

论文材料按空行分成几块：摘要、引言、5.2 节标题、比较段落（Experiment 的锚点 10:20 覆盖标题与这一段）、表 2、讨论、
附录。模块内的测试按顺序共享写入：先只有种子图的锚点，再由 Note、Claim 与带锚点的边各记下一处。
"""

from __future__ import annotations

import pytest
from conftest import AT, Writer, commit_doc

from paperweave.mcp.server import enabled, scoped
from paperweave.mcp.spec import load
from paperweave.operators import Context
from paperweave.operators.db.read_evidence import read_evidence
from paperweave.query.anchored import SOURCE_IN_TEXT, block, readable
from paperweave.store import Store

LINES = [
    "# Are Transformers Effective", "",
    *[f"abstract line {i}" for i in range(3, 6)], "",
    *[f"intro line {i}" for i in range(7, 9)], "",
    "### 5.2 Comparison", "",
    *[f"comparison line {i}" for i in range(12, 21)], "",
    "Table 2: Multivariate results.", "| method | MSE |", "| --- | --- |", "| DLinear | 0.375 |", "| Transformer | 0.865 |", "",
    *[f"discussion line {i}" for i in range(28, 41)], "",
    *[f"appendix line {i}" for i in range(42, 61)],
]  # fmt: skip
PAPER_TEXT = "".join(f"{line}\n" for line in LINES)  # 取代 conftest 中的默认材料
assert len(LINES) == 60 and LINES[21] == "Table 2: Multivariate results."


def anchored(store: Store, *refs: str) -> list[dict]:
    return read_evidence(store, list(refs), scope="anchored")["items"]


# ── 不连库的部分 ─────────────────────────────────────────────────────


def test_a_block_runs_to_the_blank_lines() -> None:
    assert block(LINES, 25, 25) == (22, 26)  # 表格的一行 → 整张表（含表题）
    assert block(LINES, 12, 13) == (12, 20)
    assert block(LINES, 11, 11) == (11, 11)  # 空行不向外扩
    assert block(LINES, 10, 20) == (10, 20)


def test_readable_blocks_merge_across_blank_lines() -> None:
    assert readable(LINES, [(10, 10), (13, 13)]) == [(10, 20)]  # 标题与段落之间只隔空行
    assert readable(LINES, [(25, 25), (3, 3), (99, 99)]) == [(3, 5), (22, 26)]  # 越界的锚点不算
    assert readable(LINES, [(3, 3), (7, 7)]) == [(3, 8)]


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("see paper_0001::5.2 Comparison::10:12.", [("paper_0001", "10:12")]),
        ("[paper_0001::12, paper_0002::3:4]", [("paper_0001", "12"), ("paper_0002", "3:4")]),
        ("paper_0001::12. Also paper_0002::3:4", [("paper_0001", "12"), ("paper_0002", "3:4")]),
        ("| 0.375 | paper_0001::L174-L196 |", [("paper_0001", "L174-L196")]),
        ("art_0001::document::1:2", [("art_0001", "1:2")]),
    ],
)
def test_source_references_are_found_in_document_text(text: str, found: list[tuple[str, str]]) -> None:
    assert [(m["head"], m["plain"] or m["sectioned"]) for m in SOURCE_IN_TEXT.finditer(text)] == found


# ── 在测试实例上 ─────────────────────────────────────────────────────


def test_only_blocks_around_recorded_anchors_can_be_read(store: Store) -> None:
    inside, table, abstract = anchored(store, "paper_0001::12:13", "paper_0001::25:25", "paper_0001::3:4")
    assert inside["state"] == "available" and inside["lines"] == [12, 20]  # 返回引用所在的整段
    assert "20| comparison line 20" in inside["text"] and "Table 2" not in inside["text"]
    assert table["state"] == "missing" and table["reason"].endswith(f"readable lines of {table['material']}: 10:20")
    assert abstract["state"] == "missing" and "text" not in abstract
    across = anchored(store, "paper_0001::18:23")[0]  # 越出记录过的块
    assert across["state"] == "missing"
    assert [i["state"] for i in read_evidence(store, ["paper_0001::25:25"])["items"]] == ["available"]  # 写者不受限


def test_a_document_reference_opens_its_block_even_after_it_is_edited_out(store: Store, writers: dict[str, Writer]) -> None:
    claude = writers["claude"]
    claude.write("note.md", "---\ntype: Note\ntitle: DLinear on ETTh1\nabs: One number.\n---\nDLinear reaches 0.375 [paper_0001::5.2 Comparison::25].\n")
    done = claude.check_in("note.md", confirm=True)
    assert done["status"] == "committed", done
    art = done["items"][0]["artifact"]
    table = anchored(store, "paper_0001::25:25")[0]
    assert table["state"] == "available" and table["lines"] == [22, 26]  # 表格的一行给出整张表
    assert "| method | MSE |" in table["text"] and "Table 2: Multivariate results." in table["text"]

    claude.fetch(art)
    claude.write("note.md", claude.read("note.md").replace(" [paper_0001::5.2 Comparison::25]", ""))
    assert claude.check_in("note.md", confirm=True)["status"] == "committed"
    assert anchored(store, "paper_0001::23:24")[0]["state"] == "available"  # 旧版文档中的引用仍算
    document = anchored(store, f"{art}::1:6")[0]
    assert document["state"] == "available" and document["lines"] == [1, 6]  # 产物文档照读，不扩块


def test_content_and_edge_anchors_open_their_blocks(store: Store) -> None:
    doc = """graph-doc: v0.2
create:
  $patchtst:
    kind: Method
    name: PatchTST
    description: Channel-independent patch Transformer for long-term forecasting.
  $claim:
    kind: Claim
    paper: paper_0001
    anchor: [42:42]
    description: The appendix repeats the comparison at more horizons.
  exp_0001:
    EVALUATES:
      $patchtst: {role: baseline, anchor: [28:28]}
confirm:
  $patchtst: {distinct_from: [method_0001, method_0002]}
"""
    done = commit_doc(store, doc)
    assert done["status"] == "committed", done
    claim, edge, between = anchored(store, "paper_0001::50:51", "paper_0001::30:30", "paper_0001::40:42")
    assert claim["state"] == "available" and claim["lines"] == [42, 60]
    assert edge["state"] == "available" and edge["lines"] == [28, 40]
    assert between["state"] == "available" and between["lines"] == [28, 60]  # 两块之间只隔空行，合成一段


def test_server_scopes_read_evidence_to_anchors(store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPERWEAVE_READ_ONLY", "1")
    monkeypatch.setenv("PAPERWEAVE_EVIDENCE_SCOPE", "anchored")
    tools, ops = scoped(enabled(load()))
    assert "only around the anchors recorded in the store" in (tools["read_evidence"].description or "")
    out = ops["read_evidence"].call(Context(store, at=AT), {"source_refs": ["paper_0001::3:3", "paper_0001::13:13"]})
    assert [i["state"] for i in out.details["items"]] == ["missing", "available"]
    monkeypatch.setenv("PAPERWEAVE_EVIDENCE_SCOPE", "anchors")
    with pytest.raises(ValueError, match="PAPERWEAVE_EVIDENCE_SCOPE"):
        scoped(enabled(load()))
