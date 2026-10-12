"""论文出了新版本：材料被取代后，用到旧材料的产物标为 ``superseded``；修订过的有据层记录在读视图中带 ``_revised``。"""

from __future__ import annotations

from conftest import EXTRACT, MATERIAL, commit_doc, write, write_material

from e09.artifact.document import data_of
from e09.artifact.stale import stale
from e09.operators.db.search import search
from e09.operators.db.traverse import traverse
from e09.store import Store

REVISE_EXP = """graph-doc: v0.1
by: maintainer
confirm:
  exp_0001: {revise: {reason: "v2 corrects the table", anchor: "5.2 Comparison::10:12"}}
nodes:
  exp_0001:
    text: Multivariate long-term forecasting comparing DLinear with Transformer and linear baselines (v2).
"""


def test_new_version_supersedes_material_and_revisions_travel_with_records(store: Store) -> None:
    first = write(store, EXTRACT)["artifact"]  # 定位在论文材料的 10:12 行
    assert stale(store, [first]) == {first: []}
    old = store.query("MATCH (m:Material)-[:MATERIAL_OF]->(:Paper {id: 'paper_0001'}) RETURN m.id AS id")[0]["id"]
    rows = data_of((store.material_root / traverse(store, [first])["nodes"][first]["_document"]).read_text(encoding="utf-8"))
    assert {r["source"] for r in rows["rows"]} == {f"{old}::5.2 Comparison::10:12"}  # 写成材料 id，固定在这个版本

    v2 = MATERIAL.replace("paper.md", "v2/paper.md")
    write_material(store.material_root, v2, "".join(f"line {i} (v2)\n" for i in range(1, 61)))
    new = commit_doc(store, f"graph-doc: v0.1\nby: maintainer\nnodes:\n  paper_0001:\n    material: {v2}\n")
    assert new["status"] == "committed", new
    reasons = stale(store, [first])[first]
    assert [r["reason"] for r in reasons] == ["superseded"] and reasons[0]["by"].startswith("material_")
    assert traverse(store, ["paper_0001"])["nodes"]["paper_0001"]["material"] == v2

    revision = commit_doc(store, REVISE_EXP, source="test:revise")
    assert revision["status"] == "committed", revision
    marked = traverse(store, ["exp_0001"])["nodes"]["exp_0001"]["_revised"]
    assert marked["commit"] == revision["commit"] and marked["by"] == "maintainer"
    assert marked["reason"] == "v2 corrects the table" and marked["anchor"].endswith("5.2 Comparison::10:12")
    hits = search(store, "Content", "DLinear Transformer linear baselines")["results"]
    assert next(h for h in hits if h["id"] == "exp_0001")["revised"]["commit"] == revision["commit"]
    assert "_revised" not in traverse(store, ["dataset_0001"])["nodes"]["dataset_0001"]

    echoed = f"graph-doc: v0.1\nby: maintainer\nnodes:\n  exp_0001:\n    _revised: {{commit: {revision['commit']}}}\n"
    assert commit_doc(store, echoed, commit=False)["status"] != "rejected"  # 原样抄回不报错
