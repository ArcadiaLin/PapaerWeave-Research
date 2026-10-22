"""可能过期（``_stale``）、修订标记、只读产物文档与登录身份，在 commit 写的共同产物上检验。

``_stale`` 在读取时按文档中的引用与 ``USED`` 边上记下的版本核对，不存状态。模块内的测试按顺序共享写入的产物：
art_0001 是 Leaderboard，之后的 Note 引用记录或它的行。
"""

from __future__ import annotations

import dataclasses
import shutil
from pathlib import Path

import pytest
from conftest import AT, LEADERBOARD, MATERIAL, Writer, commit_doc

from paperweave.artifact.stale import readonly, stale
from paperweave.artifact.versions import history
from paperweave.draft import Workdir
from paperweave.mcp.server import enabled, scoped
from paperweave.mcp.spec import load
from paperweave.operators import Context
from paperweave.operators.db.get import get
from paperweave.operators.db.read_evidence import read_evidence
from paperweave.store import Store
from paperweave.tools import TOOLS

SOURCE = "2205.13504v1::5.2 Comparison::10:12"
ROW = "art_0001#method_0002++paper_0001+96+336"  # Leaderboard 中 DLinear 的一行
REVISE_EXP = """graph-doc: v0.2
set:
  exp_0001:
    description: Multivariate long-term forecasting comparing DLinear with Transformer and linear baselines.
confirm:
  exp_0001: {revise: {reason: "the table compares linear models too", anchor: [2205.13504v1::10:20]}}
"""


def doc(body: str, section: str = "set") -> str:
    return f"graph-doc: v0.2\n{section}:\n{body}"


def note(writer: Writer, name: str, text: str) -> str:
    """检入一份 Note，返回产物 id。"""
    writer.write(f"{name}.md", f"---\ntype: Note\ntitle: {name}\nabs: An answer for the tests.\n---\n{text}\n")
    done = writer.check_in(f"{name}.md", confirm=True)
    assert done["status"] == "committed", done
    return done["items"][0]["artifact"]


def test_revisions_of_used_records_mark_artifacts(store: Store, writers: dict[str, Writer]) -> None:
    claude = writers["claude"]
    claude.write("board.md", LEADERBOARD)
    assert claude.check_in("board.md", confirm=True)["items"][0]["artifact"] == "art_0001"
    first = note(claude, "records", "DLinear is lower on ETTh1 [exp_0001] [dataset_0001].")
    assert stale(store, [first]) == {first: []}

    entity = doc("  dataset_0001:\n    alias: [ETT-h1]\n    description: Hourly ETT data, a common LTSF benchmark.\n")
    quiet = commit_doc(store, entity)
    assert quiet["status"] == "committed" and "affected_artifacts" not in quiet
    assert stale(store, [first]) == {first: []}  # 实体的改动不算

    revision = commit_doc(store, REVISE_EXP, user="maintainer")
    assert revision["status"] == "committed", revision
    assert stale(store, [first]) == {first: [{"ref": "exp_0001", "reason": "revised", "commit": revision["commit"]}]}
    told = revision["affected_artifacts"]  # 提交时就告诉改记录的写者：哪些产物用到了它
    assert [(a["artifact"], a["reasons"]) for a in told["artifacts"]] == [
        ("art_0001", ["exp_0001 revised"]),  # 表中论文里使用表头数据集的实验
        (first, ["exp_0001 revised"]),
    ]
    marked = get(store, ["exp_0001"]).details["nodes"]["exp_0001"]["_revised"]  # 修订标记随记录出现在 get 中
    assert marked["commit"] == revision["commit"] and marked["by"] == "maintainer"
    assert marked["reason"] == "the table compares linear models too" and marked["anchor"] == ["2205.13504v1::10:20"]
    assert "_revised" not in get(store, ["dataset_0001"]).details["nodes"]["dataset_0001"]
    echoed = doc(f"  exp_0001:\n    _revised: {{commit: {revision['commit']}}}\n")
    assert commit_doc(store, echoed, commit=False)["status"] == "noop"  # 只读字段原样抄回不算改动

    anchored = doc("  exp_0001:\n    USES:\n      dataset_0001: {anchor: [2205.13504v1::12:14]}\n", "create")
    assert commit_doc(store, anchored)["status"] == "blocked"  # 已有的边：create 不能改属性
    again = commit_doc(store, REVISE_EXP.replace("linear baselines", "simple linear baselines"))
    assert again["status"] == "committed" and "affected_artifacts" not in again  # 已经报过的不再重复


def test_staleness_follows_inputs(store: Store, writers: dict[str, Writer], tmp_path: Path) -> None:
    board = "art_0001"
    later = note(writers["bob"], "row", f"DLinear reaches 0.375 [{ROW}].")
    before = stale(store, [board, later])
    # 表引用的是论文行；表中论文里使用该数据集的实验是它的隐含输入，上一个测试修订了 exp_0001
    assert [(r["ref"], r["reason"]) for r in before[board]] == [("exp_0001", "revised")]
    assert before[later] == [{"ref": ROW, "reason": "stale input"}]

    root = tmp_path / "root"  # 来源不在来源目录中：引用它的产物可能过期
    shutil.copytree(store.material_root, root)
    (root / MATERIAL).unlink()
    edited = stale(dataclasses.replace(store, material_root=root), [board, later])
    assert {r["reason"] for r in edited[board]} == {"material", "revised"} and SOURCE in {r["ref"] for r in edited[board]}
    assert edited[later] == [{"ref": ROW, "reason": "stale input"}]

    document = readonly(store, [board])[board]["_document"]
    (root / MATERIAL).write_text((store.material_root / MATERIAL).read_text(encoding="utf-8"), encoding="utf-8")
    (root / document).write_text("rewritten\n", encoding="utf-8")
    current = history(store, board)[-1].material["id"]
    assert stale(dataclasses.replace(store, material_root=root), [board])[board] == [
        {"ref": current, "reason": "document"}
    ]

    removal = doc("  dataset_0001: null\n", "delete")
    impact = [w for w in commit_doc(store, removal, commit=False)["warnings"] if w["rule"] == "delete-impact"]
    assert f"{board} USED" in impact[0]["msg"] and "possibly stale" in impact[0]["msg"]
    removed = commit_doc(store, removal)
    assert removed["status"] == "committed"
    # 表与 records 新多了 removed；later 早已因表被修订报 stale input，不算本次引起
    assert {a["artifact"]: a["reasons"] for a in removed["affected_artifacts"]["artifacts"]} == {
        board: ["dataset_0001 removed"],
        "art_0002": ["dataset_0001 removed"],
    }
    view = get(store, [board, later]).details["nodes"]
    assert view[board]["_stale"] == [{"ref": "dataset_0001", "reason": "removed"}]
    assert view[later]["_stale"] == [{"ref": ROW, "reason": "stale input"}]


def test_artifacts_only_reads_documents_but_not_papers(store: Store) -> None:
    refs = ["art_0001::document::1:2", SOURCE]
    assert [i["state"] for i in read_evidence(store, refs)["items"]] == ["available", "available"]
    document, paper = read_evidence(store, refs, scope="artifacts")["items"]
    assert document["state"] == "available" and document["path"].startswith("artifacts/")
    assert paper["state"] == "missing" and "sources are not available" in paper["reason"]
    assert "text" not in paper


def test_server_scopes_read_evidence_from_the_environment(store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPERWEAVE_READ_ONLY", "1")
    tools, ops = scoped(enabled(load()))
    assert "only artifact documents" not in (tools["read_evidence"].description or "")
    monkeypatch.setenv("PAPERWEAVE_EVIDENCE_SCOPE", "artifacts")
    tools, ops = scoped(enabled(load()))
    assert "only artifact documents can be read" in (tools["read_evidence"].description or "")
    result = ops["read_evidence"].call(Context(store, at=AT), {"source_refs": [SOURCE]})
    assert result.details["items"][0]["state"] == "missing"


USER, AGENT = "results.curator@forecast-lab.example", "pi/sglang/qwen3.8-27b"


def test_commit_records_the_signed_in_writer(store: Store, tmp_path: Path) -> None:
    ctx = Context(store, at=AT, session="s-login", formed_by=USER, agent=AGENT, workdir=Workdir(tmp_path))
    (tmp_path / "d.yaml").write_text(doc("  method_0002:\n    alias: [D-Linear]\n"), encoding="utf-8")
    done = TOOLS["commit"].call(ctx, {"files": ["d.yaml"], "message": "alias"})
    assert done.details["status"] == "committed", done.details
    record = store.graph.get_commit(done.details["graph_doc"]["commit"])
    assert record.author == USER and record.meta["agent"] == AGENT and record.source == "session:s-login"

    (tmp_path / "login.md").write_text(
        "---\ntype: Note\ntitle: Login\nabs: A.\n---\nText [exp_0001].\n", encoding="utf-8"
    )
    written = TOOLS["commit"].call(ctx, {"files": ["login.md"], "message": "New."})
    assert written.details["status"] == "committed", written.details
    record = store.graph.get_commit(written.details["artifacts"]["commit"])
    assert record.author == USER and record.meta["agent"] == AGENT

    unsigned = TOOLS["commit"].call(Context(store, at=AT, workdir=Workdir(tmp_path)), {"files": ["d.yaml"], "message": "x"})
    assert unsigned.is_error and unsigned.details["errors"][0]["rule"] == "identity"
