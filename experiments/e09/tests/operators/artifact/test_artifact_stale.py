"""可能过期（``_stale``）、修订标记、只读产物文档与登录身份，在 CheckIn 写的共同产物上检验。

``_stale`` 在读取时按文档中的引用与 ``USED`` 边上记下的版本核对，不存状态。模块内的测试按顺序共享写入的产物：
art_0001 是 Leaderboard，之后的 Generate 引用记录、观察或它的行。
"""

from __future__ import annotations

import dataclasses
import shutil
from pathlib import Path

import pytest
from conftest import AT, LEADERBOARD, MATERIAL, Writer, commit_doc

from e09.artifact.stale import stale
from e09.artifact.versions import history
from e09.draft import Workdir
from e09.mcp.server import enabled, scoped
from e09.mcp.spec import load
from e09.operators import Context
from e09.operators.db.read_evidence import read_evidence
from e09.operators.db.search import search
from e09.operators.db.traverse import traverse
from e09.store import Store
from e09.tools import TOOLS

SOURCE = "paper_0001::5.2 Comparison::10:12"
ROW = "art_0001#method_0002++paper_0001+96+336"  # Leaderboard 中 DLinear 的一行
REVISE_EXP = """graph-doc: v0.1
by: maintainer
confirm:
  exp_0001: {revise: {reason: "the table compares linear models too", anchor: "5.2 Comparison::10:20"}}
nodes:
  exp_0001:
    text: Multivariate long-term forecasting comparing DLinear with Transformer and linear baselines.
"""


def doc(body: str, by: str = "claude") -> str:
    return f"graph-doc: v0.1\nby: {by}\nnodes:\n{body}"


def generate(writer: Writer, name: str, text: str) -> str:
    """检入一份 Generate，返回产物 id。"""
    writer.write(f"{name}.md", f"---\ntype: Generate\ntitle: {name}\nabs: An answer for the tests.\n---\n{text}\n")
    done = writer.check_in(f"{name}.md", confirm=True)
    assert done["status"] == "committed", done
    return done["items"][0]["artifact"]


def test_revisions_of_used_records_mark_artifacts(store: Store, writers: dict[str, Writer]) -> None:
    claude = writers["claude"]
    claude.write("board.md", LEADERBOARD)
    assert claude.check_in("board.md", confirm=True)["items"][0]["artifact"] == "art_0001"
    first = generate(claude, "records", "DLinear is lower on ETTh1 [exp_0001] [dataset_0001].")
    assert stale(store, [first]) == {first: []}

    entity = doc("  dataset_0001:\n    aliases: [ETT-h1]\n    description: Hourly ETT data, a common LTSF benchmark.\n")
    assert commit_doc(store, entity, source="test:entity")["status"] == "committed"
    assert stale(store, [first]) == {first: []}  # 实体的改动不算

    revision = commit_doc(store, REVISE_EXP, source="test:revise")
    assert revision["status"] == "committed", revision
    assert stale(store, [first]) == {first: [{"ref": "exp_0001", "reason": "revised", "commit": revision["commit"]}]}
    marked = traverse(store, ["exp_0001"])["nodes"]["exp_0001"]["_revised"]  # 修订标记随记录出现在读视图中
    assert marked["commit"] == revision["commit"] and marked["by"] == "maintainer"
    assert marked["reason"] == "the table compares linear models too" and marked["anchor"].endswith("::10:20")
    hits = search(store, "Content", "DLinear Transformer linear baselines")["results"]
    assert next(h for h in hits if h["id"] == "exp_0001")["revised"]["commit"] == revision["commit"]
    assert "_revised" not in traverse(store, ["dataset_0001"])["nodes"]["dataset_0001"]
    echoed = doc(f"  exp_0001:\n    _revised: {{commit: {revision['commit']}}}\n", by="maintainer")
    assert commit_doc(store, echoed, commit=False)["status"] != "rejected"  # 原样抄回不报错

    obs = commit_doc(
        store, doc("  $obs:\n    kind: Observation\n    text: DLinear wins on most horizons.\n    ABOUT: [exp_0001]\n")
    )
    obs_id = obs["ids"]["$obs"]
    later = generate(claude, "observation", f"Mostly [{obs_id}].")
    added = commit_doc(store, doc(f"  {obs_id}:\n    ABOUT: [exp_0001, dataset_0001]\n", by="gpt"))
    assert added["status"] == "committed", added
    assert stale(store, [later]) == {later: []}  # 别人新增出边不算
    edited = commit_doc(store, doc(f"  {obs_id}:\n    text: DLinear wins on all horizons.\n"))
    assert edited["status"] == "committed", edited
    assert stale(store, [later]) == {later: [{"ref": obs_id, "reason": "revised", "commit": edited["commit"]}]}


def test_staleness_follows_inputs(store: Store, writers: dict[str, Writer], tmp_path: Path) -> None:
    board = "art_0001"
    later = generate(writers["bob"], "row", f"DLinear reaches 0.375 [{ROW}].")
    assert stale(store, [board, later]) == {board: [], later: []}

    root = tmp_path / "root"  # 改动论文材料：用到它的行范围的产物可能过期
    shutil.copytree(store.material_root, root)
    (root / MATERIAL).write_text("edited\n" * 60, encoding="utf-8")
    edited = stale(dataclasses.replace(store, material_root=root), [board, later])
    assert {r["reason"] for r in edited[board]} == {"material"} and SOURCE in {r["ref"] for r in edited[board]}
    assert edited[later] == [{"ref": ROW, "reason": "stale input"}]

    document = traverse(store, [board])["nodes"][board]["_document"]
    (root / MATERIAL).write_text((store.material_root / MATERIAL).read_text(encoding="utf-8"), encoding="utf-8")
    (root / document).write_text("rewritten\n", encoding="utf-8")
    current = history(store, board)[-1].material["id"]
    assert stale(dataclasses.replace(store, material_root=root), [board])[board] == [
        {"ref": current, "reason": "document"}
    ]

    removal = doc("  dataset_0001: null\n")
    impact = [w for w in commit_doc(store, removal, commit=False)["warnings"] if w["rule"] == "delete-impact"]
    assert f"{board}-[USED]->dataset_0001" in impact[0]["msg"] and "possibly stale" in impact[0]["msg"]
    assert commit_doc(store, removal)["status"] == "committed"
    view = traverse(store, [board, later])["nodes"]
    assert view[board]["_stale"] == [{"ref": "dataset_0001", "reason": "removed"}]
    assert view[later]["_stale"] == [{"ref": ROW, "reason": "stale input"}]
    assert "dataset_0001" not in str(view[board]["_USED"])


def test_artifacts_only_reads_documents_but_not_papers(store: Store) -> None:
    refs = ["art_0001::document::1:2", SOURCE]
    assert [i["state"] for i in read_evidence(store, refs)["items"]] == ["available", "available"]
    document, paper = read_evidence(store, refs, artifacts_only=True)["items"]
    assert document["state"] == "available" and document["path"].startswith("artifacts/")
    assert paper["state"] == "missing" and "source papers are not available" in paper["reason"]
    assert "text" not in paper


def test_server_scopes_read_evidence_from_the_environment(store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("E09_READ_ONLY", "1")
    tools, ops = scoped(enabled(load()))
    assert "only artifact documents" not in (tools["ReadEvidence"].description or "")
    monkeypatch.setenv("E09_EVIDENCE_SCOPE", "artifacts")
    tools, ops = scoped(enabled(load()))
    assert "only artifact documents can be read" in (tools["ReadEvidence"].description or "")
    result = ops["ReadEvidence"].call(Context(store, at=AT), {"source_refs": [SOURCE]})
    assert result.details["items"][0]["state"] == "missing"


USER, AGENT = "results.curator@forecast-lab.example", "pi/sglang/qwen3.8-27b"


def test_commit_and_check_in_record_the_signed_in_writer(store: Store, tmp_path: Path) -> None:
    ctx = Context(store, at=AT, session="s-login", formed_by=USER, agent=AGENT, workdir=Workdir(tmp_path))
    text = "graph-doc: v0.1\nby: {by}\nnodes:\n  method_0002:\n    note: DLinear is linear.\n"
    other = TOOLS["Commit"].call(ctx, {"doc": text.format(by="claude"), "source": "test", "apply": True})
    assert other.is_error and other.details["errors"][0]["rule"] == "identity"
    done = TOOLS["Commit"].call(ctx, {"doc": text.replace("by: {by}\n", ""), "source": "test", "apply": True})
    assert done.details["status"] == "committed", done.details
    record = store.graph.get_commit(done.details["commit"])
    assert record.author == USER and record.meta["agent"] == AGENT

    (tmp_path / "login.md").write_text(
        "---\ntype: Generate\ntitle: Login\nabs: A.\n---\nText [exp_0001].\n", encoding="utf-8"
    )
    written = TOOLS["CheckIn"].call(ctx, {"artifact_doc": ["login.md"], "update_abstract": "New.", "confirm": True})
    assert written.details["status"] == "committed", written.details
    record = store.graph.get_commit(written.details["commit"])
    assert record.author == USER and record.meta["agent"] == AGENT


def test_commit_source_defaults_to_the_session(store: Store) -> None:
    text = "graph-doc: v0.1\nnodes:\n  method_0002:\n    note: DLinear decomposes the series.\n"
    done = TOOLS["Commit"].call(Context(store, at=AT, session="s-src", formed_by=USER), {"doc": text, "apply": True})
    assert done.details["status"] == "committed", done.details
    assert store.graph.get_commit(done.details["commit"]).source == "session:s-src"
    unsigned = TOOLS["Commit"].call(Context(store, at=AT), {"doc": text})
    assert unsigned.is_error and unsigned.details["errors"][0]["at"] == "source"
