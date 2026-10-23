"""读者的放行名单（f3 设计 §6.3）：接受的写法、正文扫描、按变更集真实格式收集历史、可读范围与返回块分开、
输入损坏即停。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from pweval.harness.source_server import tree_sha256
from pweval.protocol import allowlist
from pweval.protocol.allowlist import InputError, Ref, collect, merge, parse, scan, write

P = "2205.13504v2"
Q = "2106.13008v5"  # 只有被删的 Claim 锚到它
R = "2310.09751v3"  # 只有提交的 input 引用它
S = "2211.14730v2"  # 开放了、库中没有锚点
U = "2403.01673v1"  # 未开放
C = "repo@abcdef12"


# ---------------------------------------------------------------- 写法


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (f"{P}::120:135", Ref(P, None, 120, 135)),
        (f"{P}::4.2 Results::120:135", Ref(P, None, 120, 135)),
        (f"{P}::120", Ref(P, None, 120, 120)),  # 单个行号
        (f"{P}::120-135", Ref(P, None, 120, 135)),
        (f"{P}::L120-L135", Ref(P, None, 120, 135)),
        (f"{P}::lines 120-135", Ref(P, None, 120, 135)),
        (f"{P}::120–135", Ref(P, None, 120, 135)),
        (f" `{P} :: 120:135` ", Ref(P, None, 120, 135)),
        (f"[{P}::120:135]", Ref(P, None, 120, 135)),
        (f"{C}::src/model.py::30:48", Ref(C, "src/model.py", 30, 48)),
        (f"{C}::./src/model.py::30:48", Ref(C, "./src/model.py", 30, 48)),
        (P, "no-locator"),  # 只到来源
        (C, "no-locator"),
        (f"{C}::src/model.py", "no-locator"),  # 只到文件
        (f"{P}::4.2 Results", "no-locator"),  # 只到章节
        ("2205.13504::120:135", "format"),  # 不带版本
        ("paper_0001::120:135", "format"),  # 库内 id
        (f"{C}::../etc/passwd::1:2", "format"),
        (f"{C}::30:48", "format"),  # 代码没写文件
        ("", "format"),
        (None, "format"),
    ],
)
def test_parse_accepts_the_system_spellings(text: object, expected: Ref | str) -> None:
    assert parse(text) == expected


def test_scan_finds_several_refs_in_one_line_without_swallowing_the_first() -> None:
    text = f"{U}::1016 (Appendix D.2), {U}::103 (Section 2); see {U}::143:164 (Section 4), {U}::92:93 (Figure 2)"
    assert [p for _, p in scan(text)] == [Ref(U, None, 1016, 1016), Ref(U, None, 103, 103),
                                          Ref(U, None, 143, 164), Ref(U, None, 92, 93)]  # fmt: skip


def test_scan_sections_code_mentions_and_missing_lines() -> None:
    text = (f"The table [{P}::4.2 Results::120:135] and [{C}::models/x.py::1:6]. Paper arXiv:{P} (no lines), "
            f"code at {C}::README.md, section {P}::4.2 Results only.")  # fmt: skip
    got = [p for _, p in scan(text)]
    assert got == [Ref(P, None, 120, 135), Ref(C, "models/x.py", 1, 6), "mention", "no-locator", "no-locator"]


def test_tree_hash_matches_the_source_server(tmp_path: Path) -> None:
    (tmp_path / "a/b").mkdir(parents=True)
    (tmp_path / "a/x.py").write_text("x\n")
    (tmp_path / "a/b/y.txt").write_bytes(b"\x00\xff")
    assert allowlist.tree_sha256(tmp_path / "a") == tree_sha256(tmp_path / "a")


def test_merge_joins_overlapping_and_adjacent_spans() -> None:
    assert merge([(10, 12), (1, 3), (4, 5), (11, 20), (30, 31)]) == [[1, 5], [10, 20], [30, 31]]


# ---------------------------------------------------------------- 收集

PAPER_TEXT = "\n".join(
    ["Title", "", "Para one line a.", "Para one line b.", "", "Table 1: results", "| M | MSE |", "| A | 0.2 |",
     "| B | 0.3 |", "", "Para two.", "", "Para three."]  # fmt: skip
) + "\n"  # 13 行：段一 3–4，表 6–9，段二 11，段三 13
CODE_TEXT = "".join(f"line {i}\n" for i in range(1, 41))


def _commit(seq: int, parent: str | None, changeset: dict, message: str = "", input_: str = "") -> dict:
    return {"id": f"commit_{seq:06d}", "seq": str(seq), "parent": parent, "branch": "main", "author": "w",
            "message": message, "input": input_, "changeset": json.dumps(changeset)}  # fmt: skip


@pytest.fixture
def run(tmp_path: Path) -> Path:
    """一个两次提交的 A3 检查点（k1）。第一次：建节点、USED 边、NameKey、Material 与文档，提交的 message 与 input 中
    也有引用；第二次：改 exp_0001 的锚点（11:11 → 4:4），删 claim_0001（它的 Q::3:3 是有效锚点）。之后当前图中不再有
    11:11 与 Q 的引用，只能从历史中收到。"""
    run = tmp_path / "run"
    sources = run / "A3/sources"
    texts = {P: PAPER_TEXT, Q: "Q\n\nq text\n", R: "R\n\nr text\n", S: "S\n\ns text\n"}
    for source, text in texts.items():
        (sources / source).mkdir(parents=True)
        (sources / source / "paper.md").write_text(text)
    (sources / C / "src").mkdir(parents=True)
    (sources / C / "src/model.py").write_text(CODE_TEXT)
    opened = {source: hashlib.sha256(text.encode()).hexdigest() for source, text in texts.items()}
    opened[C] = tree_sha256(sources / C)
    doc1 = f"# Board\n\nRow from [{P}::3:3]; code [{C}::src/model.py::20:20]; unopened [{U}::5:6].\n"
    doc_path = "artifacts/Board.v1.md"
    one = {
        "nodes": [
            {"op": "create", "id": "exp_0001", "labels": ["Content", "Experiment"],
             "after": {"anchor": [f"{P}::11:11"], "description": f"See {P}::13:13 too.", "exp_key": f"{P}::1:1",
                       "formed_by": "w"}},
            {"op": "create", "id": "claim_0001", "labels": ["Content", "Claim"],
             "after": {"anchor": [f"{P}::99:99", f"{P}::0:2", f"{Q}::3:3"], "description": "old claim"}},
            {"op": "create", "id": "art_0001", "labels": ["Artifact"], "after": {"title": "Board", "abs": "a"}},
            {"op": "create", "id": "Board|NameKey", "labels": ["NameKey"],
             "after": {"raw": "Board", "registered_from": f"{P}::7:7"}},
            {"op": "create", "id": "material_1", "labels": ["Material"], "after": {"path": f"{P}::8:8"}},
        ],
        "edges": [
            {"op": "create", "from": "art_0001", "to": "exp_0001", "type": "USED",
             "after": {"locators": [f"{P}::7:7", C], "material_ref": f"{P}::1:1"}},
            {"op": "create", "from": "material_1", "to": "art_0001", "type": "MATERIAL_OF",
             "after": {"description": f"{P}::13:13"}},
        ],
        "files": [{"path": doc_path, "sha256": hashlib.sha256(doc1.encode()).hexdigest()}],
    }  # fmt: skip
    two = {
        "nodes": [
            {"op": "update", "id": "exp_0001", "labels": ["Content", "Experiment"],
             "props": {"anchor": {"before": [f"{P}::11:11"], "after": [f"{P}::4:4"]}}},
            {"op": "delete", "id": "claim_0001", "labels": ["Content", "Claim"],
             "before": {"anchor": [f"{P}::99:99", f"{P}::0:2", f"{Q}::3:3"], "description": "old claim"}},
        ],
        "edges": [],
        "files": [],
    }  # fmt: skip
    commits = [_commit(1, None, one, message=f"first; see {U}::1:2 and {P}::200:201", input_=f"input cites {R}::3:3"),
               _commit(2, "commit_000001", two)]  # fmt: skip
    snap = run / "snapshots/A3/k1"
    (snap / "documents/artifacts").mkdir(parents=True)
    (snap / "documents" / doc_path).write_text(doc1)
    (snap / "commits.jsonl").write_text("".join(json.dumps(c) + "\n" for c in commits))
    graph = [
        {"node": "exp_0001", "labels": ["Content", "Experiment"],
         "props": {"id": "exp_0001", "anchor": [f"{P}::4:4"], "description": f"See {P}::13:13 too.",
                   "exp_key": f"{P}::1:1", "formed_by": "w", "embedding": [0.1]}},
        {"node": "art_0001", "labels": ["Artifact"], "props": {"id": "art_0001", "title": "Board", "abs": "a"}},
        {"node": "Board|NameKey", "labels": ["NameKey"],
         "props": {"id": "Board|NameKey", "raw": "Board", "registered_from": f"{P}::7:7"}},
        {"node": "material_1", "labels": ["Material"], "props": {"id": "material_1", "path": f"{P}::8:8"}},
        {"edge": ["art_0001", "USED", "exp_0001"], "props": {"locators": [f"{P}::7:7", C], "material_ref": f"{P}::1:1"}},
        {"edge": ["material_1", "MATERIAL_OF", "art_0001"], "props": {"description": f"{P}::13:13"}},
    ]  # fmt: skip
    (snap / "graph.jsonl").write_text("".join(json.dumps(g) + "\n" for g in graph))
    meta = {"arm": "A3", "branches": {"main": "commit_000002"}, "counts": {"commits": 2}}
    (snap / "meta.yml").write_text(yaml.safe_dump(meta))
    backup = run / "backups/A3/k1"
    backup.mkdir(parents=True)
    (backup / "meta.yml").write_text(yaml.safe_dump({"arm": "A3", "papers": 1, "version": "commit_000002",
                                                     "sources": opened}))  # fmt: skip
    (run / "checkpoints.yml").write_text(yaml.safe_dump({"A3": {0: "commit_000000", 1: "commit_000002"}}))
    bank = tmp_path / "bank/facts"
    bank.mkdir(parents=True)
    (bank / "tables.csv").write_text(f"table,arxiv,first,last,number\n{P}:T6,{P},6,9,1\n")
    return run


def _collect(run: Path) -> dict:
    return collect(run, "A3", 1, run.parent / "bank")


def test_collects_visible_history_in_three_channels(run: Path) -> None:
    r = _collect(run)
    by_ref = {(o["channel"], o["ref"]): o for o in r["origins"]}
    # 结构化：USED 的 locators；段一扩为 3–4，表中的 7 扩为整表 6–9
    assert by_ref[("structured", f"{P}::4:4")]["passage"] == [3, 4]
    assert by_ref[("structured", f"{P}::7:7")]["passage"] == [6, 9]
    # 自由文本：节点描述与文档正文；代码前后各补 8 行（20 → 12–28），来源键带文件
    assert by_ref[("text", f"{P}::13:13")]["where"]["field"] == "description"
    assert by_ref[("text", f"{P}::3:3")]["where"]["document"] == "artifacts/Board.v1.md"
    assert by_ref[("text", f"{C}::src/model.py::20:20")]["passage"] == [12, 28]
    # 提交：只出现在 input 中的引用也放行，出处记提交 ID 与字段名
    assert by_ref[("commit", f"{R}::3:3")]["where"] == {"commit": "commit_000001", "seq": 1, "field": "input"}
    assert r["readable"][R] == [[3, 3]]
    # 不收：隐藏字段（exp_key、formed_by、material_ref）、NameKey 除 raw 以外的、Material 节点与连着它的边
    hidden = ("exp_key", "material_ref", "registered_from", "path")
    assert not [o for o in r["origins"] if o["where"].get("field") in hidden]
    assert not [o for o in r["origins"] if "material_1" in json.dumps(o["where"])]
    # 丢弃逐条记下，三个通道同一套校验：越界与零行、只到来源的 locator、未开放的来源
    reasons = sorted((d["channel"], d["reason"], d["ref"]) for d in r["dropped"])
    assert reasons == sorted([
        ("structured", "bad-range", f"{P}::99:99"), ("structured", "bad-range", f"{P}::0:2"),
        ("structured", "bad-range", f"{P}::99:99"), ("structured", "bad-range", f"{P}::0:2"),  # 创建与删除各一次
        ("structured", "no-locator", C), ("text", "unopened", f"{U}::5:6"),
        ("commit", "unopened", f"{U}::1:2"), ("commit", "bad-range", f"{P}::200:201"),
    ])  # fmt: skip
    # 返回块与可读范围分开；代码按 来源＋文件 分组
    assert r["passages"][P] == [[3, 4], [6, 9], [11, 11], [13, 13]]
    assert r["readable"][P] == [[3, 4], [6, 9], [11, 11], [13, 13]]
    assert r["passages"][f"{C}::src/model.py"] == [[12, 28]]
    assert S not in r["readable"]  # 开放了但没有锚点：名单中没有它
    # 统计：自由文本新增 13 与代码块，提交新增 R；取自 before 的引用出现两次（11:11 与 Q::3:3）
    beyond = r["stats"]["beyond_structured"]
    assert (beyond["text"]["blocks"], beyond["commit"]["blocks"], beyond["text+commit"]["blocks"]) == (2, 1, 3)
    assert beyond["commit"]["sources"] == [R]
    assert r["stats"]["before_side"] == 2
    assert r["checks"]["history"]["parent_chain"] == "ok" and r["checks"]["replay"]["replay"] == "ok"


def test_valid_old_anchors_stay_readable_after_update_and_delete(run: Path) -> None:
    graph = (run / "snapshots/A3/k1/graph.jsonl").read_text()
    assert f"{P}::11:11" not in graph and Q not in graph  # 当前图中已经没有这两条引用
    r = _collect(run)
    old = {o["ref"]: o["where"] for o in r["origins"] if o["where"].get("side") == "before"}
    assert old[f"{P}::11:11"]["op"] == "update" and old[f"{Q}::3:3"]["op"] == "delete"
    assert [11, 11] in r["readable"][P] and r["readable"][Q] == [[3, 3]]


def test_overlapping_blocks_stay_separate_but_readable_merges(run: Path) -> None:
    def cross(cs: dict) -> None:
        cs["nodes"][0]["props"]["anchor"]["after"] = [f"{P}::4:11"]  # 跨段：3–11

    _mutate(run, 2, cross)
    snap = run / "snapshots/A3/k1"
    graph = [json.loads(line) for line in (snap / "graph.jsonl").read_text().splitlines()]
    graph[0]["props"]["anchor"] = [f"{P}::4:11"]
    (snap / "graph.jsonl").write_text("".join(json.dumps(g) + "\n" for g in graph))
    r = _collect(run)
    assert [3, 11] in r["passages"][P] and [3, 4] in r["passages"][P] and [6, 9] in r["passages"][P]
    assert r["readable"][P] == [[3, 11], [13, 13]]


def _mutate(run: Path, seq: int, change) -> None:
    """改第 ``seq`` 次提交的变更集（``change`` 原地修改解开的变更集）。"""
    path = run / "snapshots/A3/k1/commits.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    cs = json.loads(rows[seq - 1]["changeset"])
    change(cs)
    rows[seq - 1]["changeset"] = json.dumps(cs)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def _bad_update_before(cs: dict) -> None:
    cs["nodes"][0]["props"]["anchor"]["before"] = [f"{P}::12:12"]


def _bad_delete_before(cs: dict) -> None:
    cs["nodes"][1]["before"]["description"] = "another claim"


@pytest.mark.parametrize("change", [_bad_update_before, _bad_delete_before])
def test_wrong_before_values_fail_even_when_the_final_graph_matches(run: Path, change) -> None:
    graph = (run / "snapshots/A3/k1/graph.jsonl").read_bytes()
    _mutate(run, 2, change)
    assert (run / "snapshots/A3/k1/graph.jsonl").read_bytes() == graph  # 最终图没变
    with pytest.raises(InputError, match="replay: the before of"):
        _collect(run)


def _edit(path: Path, old: str, new: str) -> None:
    path.write_text(path.read_text().replace(old, new))


@pytest.mark.parametrize(
    ("damage", "message"),
    [
        (lambda run: _edit(run / "A3/sources" / P / "paper.md", "Para two.", "Para 2."), "sha256"),
        (lambda run: (run / "snapshots/A3/k1/documents/artifacts/Board.v1.md").unlink(), "missing"),
        (lambda run: _edit(run / "snapshots/A3/k1/documents/artifacts/Board.v1.md", "Row", "Raw"), "sha256"),
        (lambda run: _edit(run / "snapshots/A3/k1/commits.jsonl", '"parent": "commit_000001"', '"parent": null'), "parent"),
        (lambda run: _edit(run / "backups/A3/k1/meta.yml", "commit_000002", "commit_000001"), "disagree"),
        (lambda run: _edit(run / "snapshots/A3/k1/graph.jsonl", '"abs": "a"', '"abs": "b"'), "replay"),
    ],
)
def test_damaged_inputs_stop_the_collection(run: Path, damage, message: str) -> None:
    damage(run)
    with pytest.raises(InputError, match=message):
        _collect(run)


def test_write_puts_the_digest_beside_and_refuses_to_replace_different_content(run: Path, tmp_path: Path) -> None:
    r = _collect(run)
    path = write(r, tmp_path / "out")
    digest, name = (path.parent / "k1.json.sha256").read_text().split()
    assert name == "k1.json" and digest == hashlib.sha256(path.read_bytes()).hexdigest()
    assert write(r, tmp_path / "out") == path  # 内容相同：可以重写
    with pytest.raises(FileExistsError):
        write({**r, "rule": "other"}, tmp_path / "out")
