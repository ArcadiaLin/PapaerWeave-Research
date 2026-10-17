"""Leaderboard 的隐含输入：库中有使用表头数据集、但论文不在表中的实验时，``_stale`` 报 ``uncovered``；把这篇论文
写进 “Papers covered”（说明为何不收）后提示消失。

模块自己重建一次图（见 conftest），按顺序共享写入的产物：art_0001 是 Leaderboard。
"""

from __future__ import annotations

from conftest import LEADERBOARD, Writer

from paperweave.artifact.stale import stale
from paperweave.store import Store

SECOND = "papers/2024-Other/paper.md"
OTHER_PAPER = """graph-doc: v0.2
create:
  $other:
    kind: Paper
    name: Another forecasting paper
    year: 2024
    material: papers/2024-Other/paper.md
    description: A later paper that also reports ETTh1.
  $exp:
    kind: Experiment
    paper: $other
    anchor: [3:5]
    figures: [S4.T1]
    description: Multivariate forecasting on ETTh1 against DLinear.
    EVALUATES:
      method_0002: {role: baseline, result: cited}
    USES:
      dataset_0001: {role: evaluation_data}
    ON_TASK:
      task_0001:
confirm:
  $other: {distinct_from: [paper_0001]}  # 测试库不接向量服务，全文近邻不设阈值
"""


def test_a_paper_missing_from_the_table_is_uncovered(store: Store, writers: dict[str, Writer]) -> None:
    claude, bob = writers["claude"], writers["bob"]
    claude.write("board.md", LEADERBOARD)
    assert claude.check_in("board.md", confirm=True)["items"][0]["artifact"] == "art_0001"
    assert stale(store, ["art_0001"]) == {"art_0001": []}

    file = store.material_root / SECOND
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text("".join(f"other line {i}\n" for i in range(1, 11)), encoding="utf-8")
    done = bob.commit(OTHER_PAPER)
    assert done["status"] == "committed", done
    assert stale(store, ["art_0001"])["art_0001"] == [{"ref": "paper_0002", "reason": "uncovered", "experiments": "exp_0002"}]

    edit = claude.fetch("art_0001")["items"][0]["path"]
    text = claude.read(edit).replace(
        "| paper_0001 DLinear | Table 2 (paper_0001::5.2 Comparison::10:20) | no |",
        "| paper_0001 DLinear | Table 2 (paper_0001::5.2 Comparison::10:20) | no |\n"
        "| paper_0002 Other | left out: univariate setting | no |",
    )
    claude.write(edit, text)
    assert claude.check_in(edit, message="Record why paper_0002 is left out.", confirm=True)["status"] == "committed"
    assert stale(store, ["art_0001"]) == {"art_0001": []}  # 有意不收也是一个留下记录的决定


def test_get_lists_uses_and_checkout_keeps_notes_in_a_file(store: Store, writers: dict[str, Writer]) -> None:
    from paperweave.operators.db import CHECKOUT
    from paperweave.tools import TOOLS

    claude = writers["claude"]
    board = TOOLS["get"].call(claude.ctx(), {"ids": ["art_0001"]}).details["nodes"]["art_0001"]
    assert board["_uses"]["dataset"] == ["dataset_0001"] and "method_0002" in board["_uses"]["method"]
    assert board["_document"].startswith("checkout this id to get the document as a file")

    result = CHECKOUT.call(claude.ctx(), {"ids": ["art_0001"]})
    item = result.details["files"][0]
    assert item["notes_file"].endswith(".notes.yaml") and "hint" in item  # 结构化的全文仍在 details 中
    assert "last_edit:" in result.text and "editors:" not in result.text  # 给 agent 的文本只有摘要
    notes = claude.read(item["notes_file"])
    assert notes.startswith("# Edit notes for ") and "editors:" in notes

    text = store.query("MATCH (a:Artifact {id: 'art_0001'}) RETURN a.search_text AS t")[0]["t"]
    assert "DLinear" in text and "ETTh1" in text  # 产物的检索文本带上它用到的节点的名称
