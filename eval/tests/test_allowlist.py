"""读者的放行名单（f3 设计 §6.3）：接受的写法、正文扫描、按变更集真实格式收集历史、可读范围与返回块分开、
输入损坏即停。"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
import yaml

from pweval.harness.export import export_a0
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


# ---------------------------------------------------------------- A0：Git 历史


def _git(cwd: Path, *args: str) -> str:
    env = {"GIT_AUTHOR_NAME": "w", "GIT_AUTHOR_EMAIL": "w", "GIT_COMMITTER_NAME": "w", "GIT_COMMITTER_EMAIL": "w",
           "GIT_AUTHOR_DATE": "2026-10-22T00:00:00Z", "GIT_COMMITTER_DATE": "2026-10-22T00:00:00Z", "HOME": str(cwd)}  # fmt: skip
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True, env=env).stdout.strip()


def _a0_run(tmp_path: Path, extra: dict[str, str] | None = None) -> Path:
    """A0 的一个检查点（k1，第 2 个会话之后）：提交 1 为约定（引用未开放的示例来源），提交 2 建 exp_0001（锚点
    11:11，说明正文中引用 Q），提交 3 把锚点改为 4:4，另一个文件引用检查点之后才开放的 S。``extra`` 另在提交 3 中加文件。"""
    run = tmp_path / "run"
    texts = {P: PAPER_TEXT, Q: "Q\n\nq text\n", S: "S\n\ns text\n"}
    for source, text in texts.items():
        (run / "A0/sources" / source).mkdir(parents=True)
        (run / "A0/sources" / source / "paper.md").write_text(text)
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    (work / "AGENTS.md").write_text(f"Cite like [{U}::120:135].\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", "Set up the shared repository")
    node = work / "store/nodes/exp_0001.yaml"
    node.parent.mkdir(parents=True)
    node.write_text(f'id: exp_0001\nanchor: ["{P}::11:11"]\ndescription: see {P}\n')
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", f"add exp_0001\n\nthe table is at {Q}::3:3")
    node.write_text(f'id: exp_0001\nanchor: ["{P}::4:4"]\n')
    (work / "store/nodes/note.md").write_text(f"later: [{S}::1:1]\n")
    for path, text in (extra or {}).items():
        (work / path).parent.mkdir(parents=True, exist_ok=True)
        (work / path).write_text(text)
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", "fix the anchor")
    c1, c2, c3 = _git(work, "rev-list", "--reverse", "main").split()
    shared = run / "A0/shared.git"
    _git(tmp_path, "clone", "-q", "--bare", str(work), str(shared))
    _git(shared, "tag", "checkpoint-0", c1)
    _git(shared, "tag", "checkpoint-1", c3)
    export_a0(shared, "checkpoint-1", run / "snapshots/A0/k1")
    (run / "checkpoints.yml").write_text(yaml.safe_dump({"A0": {0: c1, 1: c3}}))
    rows = [
        {"arm": "A3", "seq": 1, "materials": {"named": [], "opens": []}, "version_before": "x", "version_after": "y"},
        {"arm": "A0", "seq": 1, "materials": {"named": [Q], "opens": [Q], "available": 2}, "read_source": {"fetched": [Q]},
         "version_before": c1, "version_after": c2},
        {"arm": "A0", "seq": 2, "materials": {"named": [], "opens": [], "available": 2}, "read_source": {},
         "version_before": c2, "version_after": c3},
    ]  # fmt: skip
    (run / "sessions.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    bank = tmp_path / "bank"
    (bank / "facts").mkdir(parents=True)
    (bank / "facts/tables.csv").write_text(f"table,arxiv,first,last,number\n{P}:T6,{P},6,9,1\n")
    (bank / "tasks").mkdir()
    plan = [{"seq": 1, "type": "build"}, {"seq": 2, "type": "build"}, {"type": "checkpoint", "papers": 1},
            {"seq": 3, "type": "build"}]  # fmt: skip
    (bank / "tasks/plan-f3.yml").write_text(yaml.safe_dump(plan))
    materials = {"seed": [P], "sessions": [{"seq": 1, "named": [Q], "opens": [Q]}, {"seq": 2, "named": [], "opens": []},
                                           {"seq": 3, "named": [S], "opens": [S]}],
                 "sources": {s: {"kind": "paper", "sha256": hashlib.sha256(t.encode()).hexdigest()} for s, t in texts.items()}}  # fmt: skip
    (bank / "tasks/materials.yml").write_text(yaml.safe_dump(materials))
    _git(bank, "init", "-q", "-b", "main")
    _git(bank, "add", "-A")
    _git(bank, "commit", "-q", "-m", "bank")
    probes = {"commit": _git(bank, "rev-parse", "HEAD"), "dirty": False}
    config = {"plan": "tasks/plan-f3.yml", "materials": "tasks/materials.yml"}
    calls = [{"started": "t0", "argv": ["f3", "--arms", "A3"], "probes": {"commit": "other", "dirty": True}, "config": config},
             {"started": "t1", "argv": ["f3", "--arms", "A0", "--reset"], "probes": probes, "config": config}]  # fmt: skip
    (run / "run.yml").write_text(yaml.safe_dump({"invocations": calls}))
    return run


def _collect_a0(run: Path) -> dict:
    return collect(run, "A0", 1, run.parent / "bank")


def test_a0_collects_every_file_version_and_full_commit_messages(tmp_path: Path) -> None:
    r = _collect_a0(_a0_run(tmp_path))
    by_ref = {(o["channel"], o["ref"]): o for o in r["origins"]}
    # 文件的每个版本都收：提交 2 中被改掉的旧锚点 11:11 照样放行；正文不按 YAML 解析，统一是 text
    old = by_ref[("text", f"{P}::11:11")]["where"]
    assert (old["seq"], old["file"]) == (2, "store/nodes/exp_0001.yaml")
    assert by_ref[("text", f"{P}::4:4")]["passage"] == [3, 4]
    # 提交说明取完整正文：只在第二段出现的引用也收到（快照的 log.jsonl 只有首行）
    assert by_ref[("commit", f"{Q}::3:3")]["where"]["field"] == "message"
    assert Q not in (run_log := (tmp_path / "run/snapshots/A0/k1/log.jsonl").read_text()) and "add exp_0001" in run_log
    # 开放的来源取自计划与材料表：S 的副本已在来源目录中，但检查点之后才开放
    assert sorted(r["inputs"]["sources"]) == sorted([P, Q])
    reasons = sorted((d["reason"], d["ref"]) for d in r["dropped"])
    assert reasons == sorted([("unopened", f"{U}::120:135"), ("unopened", f"{S}::1:1")])
    assert set(r["stats"]["channels"]) == {"text", "commit"} and "beyond_structured" not in r["stats"]
    assert r["readable"] == {P: [[3, 4], [11, 11]], Q: [[3, 3]]}
    assert r["checks"]["sessions"]["last_session"] == 2 and r["checks"]["tree"]["tree"] == "ok"
    assert r["source_text"]["sources"] == {} and r["source_text"]["source_like_paths"] == []


def test_a0_reads_the_tables_the_writers_ran_with_not_the_bank_worktree(tmp_path: Path) -> None:
    run = _a0_run(tmp_path)
    before = _collect_a0(run)
    _edit(run.parent / "bank/tasks/materials.yml", f"seed:\n- {P}\n", f"seed:\n- {P}\n- {S}\n")  # 未来的来源改进种子
    after = _collect_a0(run)
    assert after == before and S not in after["inputs"]["sources"]
    assert after["inputs"]["probes"]["invocations"] == ["t1"]  # 只认跑过 A0 的调用


def test_a0_reports_source_text_committed_into_the_repository(tmp_path: Path) -> None:
    r = _collect_a0(_a0_run(tmp_path, {"copy/paper.md": PAPER_TEXT.replace("\n", " ")}))
    st = r["source_text"]
    assert st["sources"][P]["share"] == 1.0 and st["sources"][P]["file"]["file"] == "copy/paper.md"
    assert st["source_like_paths"] == ["copy/paper.md"]


def _a0_sessions(run: Path, change) -> None:
    rows = [json.loads(line) for line in (run / "sessions.jsonl").read_text().splitlines()]
    change(rows)
    (run / "sessions.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


@pytest.mark.parametrize(
    ("damage", "message"),
    [
        (lambda run: _edit(run / "snapshots/A0/k1/tree/AGENTS.md", "Cite", "Quote"), "tree differs"),
        (lambda run: (run / "snapshots/A0/k1/tree/store/nodes/note.md").unlink(), "tree differs"),
        (lambda run: _edit(run / "A0/sources" / P / "paper.md", "Para two.", "Para 2."), "sha256"),
        (lambda run: _a0_sessions(run, lambda rows: rows.pop()), "one per session"),
        (lambda run: _a0_sessions(run, lambda rows: rows[2]["materials"].update(opens=[S])), "materials differ"),
        (lambda run: _a0_sessions(run, lambda rows: rows[1]["read_source"].update(fetched=[S])), "unopened"),
        (lambda run: _a0_sessions(run, lambda rows: rows[2].update(version_after=rows[2]["version_before"])), "end at"),
        (lambda run: _a0_sessions(run, lambda rows: rows[1]["materials"].update(available=3)), "available"),
        (lambda run: _edit(run / "snapshots/A0/k1/log.jsonl", '"author": "w"', '"author": "v"'), "snapshot log"),
        (lambda run: _edit(run / "snapshots/A0/k1/log.jsonl", "fix the anchor", "fix anchors"), "snapshot log"),
        (lambda run: _edit(run / "run.yml", "dirty: false", "dirty: true"), "uncommitted"),
        (lambda run: _edit(run / "run.yml", "- A0", "- A2"), "no invocation ran A0"),
    ],
)
def test_a0_damaged_inputs_stop_the_collection(tmp_path: Path, damage, message: str) -> None:
    run = _a0_run(tmp_path)
    damage(run)
    with pytest.raises(InputError, match=message):
        _collect_a0(run)


def test_a0_checkpoint_versions_must_agree(tmp_path: Path) -> None:
    run = _a0_run(tmp_path)
    _git(run / "A0/shared.git", "tag", "-f", "checkpoint-1", "checkpoint-0")
    with pytest.raises(InputError, match="disagree"):
        _collect_a0(run)



# ---------------------------------------------------------------- A3F：A3 检查点的只读文件视图

A3_HEAD = "commit_000002"


def _a3f_export(run: Path, work: Path, papers: int, flags: Path) -> None:
    """把工作仓库 ``work`` 当前的 ``main`` 作为第 ``papers`` 个检查点的导出：裸仓库只有 main 与标签，快照同 A0 的格式，
    ``meta.yml`` 另记清单（与导出脚本 tmps/A3F-export.py 的字段相同）。"""
    _git(work, "tag", "-f", f"checkpoint-{papers}")
    bare = allowlist.a3f_repo(run, papers)
    bare.parent.mkdir(parents=True, exist_ok=True)
    _git(bare.parent, "init", "-q", "--bare", "-b", "main", bare.name)
    _git(work, "push", "-q", str(bare), "main", f"refs/tags/checkpoint-{papers}")
    out = run / "snapshots/A3F" / f"k{papers}"
    meta = export_a0(bare, f"checkpoint-{papers}", out)
    a3, backup_meta = run / "snapshots/A3/k1", run / "backups/A3/k1/meta.yml"
    sha = lambda f: hashlib.sha256(f.read_bytes()).hexdigest()  # noqa: E731
    meta |= {
        "arm": "A3F",
        "view_of": {"arm": "A3", "papers": papers, "version": A3_HEAD,
                    "snapshot": {**{n: sha(a3 / n) for n in ("meta.yml", "graph.jsonl", "commits.jsonl")},
                                 "documents": tree_sha256(a3 / "documents")},
                    "backup_meta": {"path": str(backup_meta), "sha256": sha(backup_meta)}},
        "inputs": {"flags": {"path": str(flags), "sha256": sha(flags)}, "agents_md": sha(out / "tree/AGENTS.md")},
        "sources": yaml.safe_load(backup_meta.read_text())["sources"],
    }  # fmt: skip
    (out / "meta.yml").write_text(yaml.safe_dump(meta, sort_keys=False))


def _a3f_run(tmp_path: Path) -> Path:
    """A3 的一个检查点（k1，版本 ``commit_000002``）与它的 A3F 导出：提交 1 为说明文字（引用未开放的示例来源），提交 2、
    3 为两个库提交（锚点 11:11 改为 4:4，并加一个产物），提交 4 写入派生字段（``_revised`` 的 reason 中引用 Q::3:3）。
    A3 的名单与 A3F 共有 P 3–4 一块；只在 A3 的 Q 1–1（USED 的 locators，导出不放）与 P 13–13。另导出一个更晚的检查点 k2（多一个库提交）。"""
    run = tmp_path / "run"
    texts = {P: PAPER_TEXT, Q: "Q\n\nq text\n", S: "S\n\ns text\n"}
    for source, text in texts.items():
        (run / "A3/sources" / source).mkdir(parents=True)
        (run / "A3/sources" / source / "paper.md").write_text(text)
    opened = {s: hashlib.sha256(texts[s].encode()).hexdigest() for s in (P, Q)}
    a3 = run / "snapshots/A3/k1"
    (a3 / "documents").mkdir(parents=True)
    (a3 / "documents/art.v1.md").write_text("doc\n")
    (a3 / "meta.yml").write_text(yaml.safe_dump({"branches": {"main": A3_HEAD}}))
    (a3 / "graph.jsonl").write_text("{}\n")
    (a3 / "commits.jsonl").write_text("{}\n")
    (run / "backups/A3/k1").mkdir(parents=True)
    (run / "backups/A3/k1/meta.yml").write_text(yaml.safe_dump({"arm": "A3", "papers": 1, "version": A3_HEAD,
                                                                "sources": opened}))  # fmt: skip
    (run / "checkpoints.yml").write_text(yaml.safe_dump({"A3": {0: "commit_000001", 1: A3_HEAD}}))
    a3_list = {"arm": "A3", "checkpoint": 1, "version": A3_HEAD, "inputs": {"sources": opened},
               "origins": [{"channel": "structured", "ref": f"{P}::4:4", "source": P, "lines": [4, 4], "passage": [3, 4],
                            "where": {"node": "exp_0001", "field": "anchor"}},
                           {"channel": "structured", "ref": f"{Q}::3,::1:1", "source": Q, "lines": [1, 1], "passage": [1, 1],
                            "where": {"edge": "art_0001-[USED]->paper_0002", "field": "locators"}},
                           {"channel": "structured", "ref": f"{P}::13:13", "source": P, "lines": [13, 13],
                            "passage": [13, 13], "where": {"node": "claim_0001", "field": "anchor", "side": "before"}}],
               "readable": {P: [[3, 4], [13, 13]], Q: [[1, 1]]}}  # fmt: skip
    (run / "allowlists/A3").mkdir(parents=True)
    (run / "allowlists/A3/k1.json").write_text(json.dumps(a3_list))
    flags = tmp_path / "flags/k1.json"
    flags.parent.mkdir()
    flags.write_text('{"flags": {}}')
    work = tmp_path / "view"
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    (work / "AGENTS.md").write_text(f"Cite like [{U}::120:135].\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", "Set up the shared repository")
    node = work / "store/nodes/experiment/exp_0001.yaml"
    node.parent.mkdir(parents=True)
    node.write_text(f'id: exp_0001\nkind: Experiment\nanchor: ["{P}::11:11"]\n')
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", "add exp_0001\n\nPaperWeave-Commit: commit_000001")
    node.write_text(f'id: exp_0001\nkind: Experiment\nanchor: ["{P}::4:4"]\n')
    board = work / "store/artifacts/Board.md"
    board.parent.mkdir(parents=True)
    board.write_text(f"---\ntype: Leaderboard\nid: art_0001\ntitle: Board\n---\n| M | x [{P}::4:4] |\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", f"fix the anchor\n\nPaperWeave-Commit: {A3_HEAD}")
    later = work.with_name("later")
    _git(tmp_path, "clone", "-q", str(work), str(later))
    node.write_text(f'id: exp_0001\nkind: Experiment\n_revised: {{reason: "see {Q}::3:3"}}\nanchor: ["{P}::4:4"]\n')
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", f"Write the store's read-only fields as of {A3_HEAD}")
    _a3f_export(run, work, 1, flags)
    # 更晚的检查点：同一段历史之后多一个库提交，再写它自己的派生字段（k2 只为读者仓库核对“之后的提交”）
    (later / "store/nodes/experiment/exp_0002.yaml").write_text("id: exp_0002\nkind: Experiment\n")
    _git(later, "add", "-A")
    _git(later, "commit", "-q", "-m", "add exp_0002\n\nPaperWeave-Commit: commit_000003")
    (later / "store/nodes/experiment/exp_0002.yaml").write_text("id: exp_0002\nkind: Experiment\n_formed_by: w\n")
    _git(later, "add", "-A")
    _git(later, "commit", "-q", "-m", "Write the store's read-only fields as of commit_000003")
    _git(later, "tag", "-f", "checkpoint-2")
    bare = allowlist.a3f_repo(run, 2)
    _git(bare.parent, "init", "-q", "--bare", "-b", "main", bare.name)
    _git(later, "push", "-q", str(bare), "main", "refs/tags/checkpoint-2")
    bank = tmp_path / "bank"
    (bank / "facts").mkdir(parents=True)
    (bank / "facts/tables.csv").write_text(f"table,arxiv,first,last,number\n{P}:T6,{P},6,9,1\n")
    return run


def _collect_a3f(run: Path) -> dict:
    return collect(run, "A3F", 1, run.parent / "bank")


def test_a3f_collects_every_file_version_including_the_read_only_fields(tmp_path: Path) -> None:
    r = _collect_a3f(_a3f_run(tmp_path))
    by_ref = {(o["channel"], o["ref"]): o for o in r["origins"]}
    assert by_ref[("text", f"{P}::11:11")]["where"]["seq"] == 2  # 被改掉的旧锚点照样放行
    derived = by_ref[("text", f"{Q}::3:3")]["where"]  # 只在写派生字段的最后一个提交中出现
    assert (derived["seq"], derived["file"]) == (4, "store/nodes/experiment/exp_0001.yaml")
    assert [(d["reason"], d["ref"]) for d in r["dropped"]] == [("unopened", f"{U}::120:135")]  # 说明文字的示例
    assert "structured" not in {c for c, _ in by_ref}
    assert r["readable"] == {P: [[3, 4], [11, 11]], Q: [[3, 3]]}
    assert r["inputs"]["sources"].keys() == {P, Q} and r["checks"]["view"]["versions"]["manifest"] == A3_HEAD
    assert r["version"] == r["inputs"]["repository"]["head"] == _git(allowlist.a3f_repo(tmp_path / "run", 1), "rev-parse",
                                                                      "checkpoint-1")  # fmt: skip
    c = r["compare_a3"]
    assert c["blocks"] == {"A3F": 3, "A3": 3, "both": 1, "only_A3F": 2, "only_A3": 2}
    assert c["readable_lines"] == {"A3F": 4, "A3": 4, "only_A3F": 2, "only_A3": 2}
    assert [(b["source"], b["passage"]) for b in c["only_A3F"]] == [(Q, [3, 3]), (P, [11, 11])]
    assert c["only_A3"] == [
        {"source": Q, "passage": [1, 1], "origins": [
            {"channel": "structured", "ref": f"{Q}::3,::1:1", "where": {"edge": "art_0001-[USED]->paper_0002", "field": "locators"}}]},
        {"source": P, "passage": [13, 13], "origins": [
            {"channel": "structured", "ref": f"{P}::13:13", "where": {"node": "claim_0001", "field": "anchor", "side": "before"}}]}]  # fmt: skip


def _manifest(run: Path, change) -> None:
    path = run / "snapshots/A3F/k1/meta.yml"
    meta = yaml.safe_load(path.read_text())
    change(meta)
    path.write_text(yaml.safe_dump(meta, sort_keys=False))


@pytest.mark.parametrize(
    ("damage", "message"),
    [
        (lambda run: _edit(run / "snapshots/A3/k1/graph.jsonl", "{}", "{ }"), "A3 snapshot k1 changed"),
        (lambda run: _edit(run / "snapshots/A3/k1/documents/art.v1.md", "doc", "Doc"), "A3 snapshot k1 changed"),
        (lambda run: _edit(run / "checkpoints.yml", "1: commit_000002", "1: commit_000003"), "versions disagree"),
        (lambda run: _edit(run / "backups/A3/k1/meta.yml", "version: commit_000002", "version: commit_000003"),
         "versions disagree"),
        (lambda run: _edit(run / "snapshots/A3/k1/meta.yml", "main: commit_000002", "main: commit_000003"),
         "versions disagree"),
        (lambda run: _edit(run / "backups/A3/k1/meta.yml", "papers: 1", "papers: 1\nnote: x"), "backup meta k1 changed"),
        (lambda run: _edit(run.parent / "flags/k1.json", "{}", "{ }"), "read-only fields"),
        (lambda run: _manifest(run, lambda m: m["sources"].pop(Q)), "other sources than the A3 backup"),
        (lambda run: _manifest(run, lambda m: m["view_of"].update(papers=2)), "not an A3F view"),
        (lambda run: _edit(run / "snapshots/A3F/k1/tree/AGENTS.md", "Cite", "Quote"), "AGENTS.md differs"),
        (lambda run: (run / "snapshots/A3F/k1/tree/store/nodes/experiment/exp_0001.yaml").write_text("x\n"), "tree differs"),
        (lambda run: _git(allowlist.a3f_repo(run, 1), "tag", "-f", "checkpoint-1", "checkpoint-1~1"), "disagree"),
        (lambda run: _edit(run / "allowlists/A3/k1.json", f'"{Q}": ', '"x": '), "other opened sources than the A3F view"),
        (lambda run: _edit(run / "allowlists/A3/k1.json", '"version": "commit_000002"', '"version": "commit_000003"'),
         "A3 allowlist is of"),
        (lambda run: _edit(run / "A3/sources" / P / "paper.md", "Para two.", "Para 2."), "sha256"),
    ],
)  # fmt: skip
def test_a3f_damaged_inputs_stop_the_collection(tmp_path: Path, damage, message: str) -> None:
    run = _a3f_run(tmp_path)
    damage(run)
    with pytest.raises(InputError, match=message):
        _collect_a3f(run)


# ---------------------------------------------------------------- A4：Graphiti 的 episode


def _a4_rows() -> list[dict]:
    """两个 episode（三个字段各有引用）、一个实体（摘要中的引用不收）与它们之间的边；属性与 export_graphiti 的格式相同。"""
    ep = lambda uuid, at, content, name, desc: {  # noqa: E731
        "node": uuid, "labels": ["Episodic"],
        "props": {"uuid": uuid, "group_id": "formal", "created_at": at, "content": content, "name": name,
                  "source_description": desc, "source": "text", "entity_edges": [], "valid_at": at}}  # fmt: skip
    return [
        ep("ep-2", "2026-10-23T19:00:00.000000000+00:00", f"Board row [{P}::4:4]; unopened [{U}::5:6]; also {S}",
           "Leaderboard rows", f"from {Q}::3:3"),
        ep("ep-1", "2026-10-23T18:00:00.000000000+00:00", f"Table [{P}::7:7] and code [{C}::src/model.py::20:20]",
           f"Paper {P}::11:11", "paper added"),
        {"node": "ent-1", "labels": ["Entity", "Method"],
         "props": {"uuid": "ent-1", "group_id": "formal", "name": "M", "summary": f"see {P}::13:13",
                   "name_embedding": [0.1, 0.2], "created_at": "2026-10-23T18:01:00+00:00"}},
        {"edge": ["ep-1", "MENTIONS", "ent-1"], "props": {"uuid": "e-1", "group_id": "formal", "created_at": "t"}},
        {"edge": ["ent-1", "RELATES_TO", "ent-1"],
         "props": {"uuid": "e-2", "group_id": "formal", "fact": f"M beats N ({P}::13:13)", "fact_embedding": [0.3]}},
    ]  # fmt: skip


def _a4_run(tmp_path: Path, rows: list[dict] | None = None) -> Path:
    run = tmp_path / "run"
    texts = {P: PAPER_TEXT, Q: "Q\n\nq text\n", S: "S\n\ns text\n"}
    for source, text in texts.items():
        (run / "A4/sources" / source).mkdir(parents=True)
        (run / "A4/sources" / source / "paper.md").write_text(text)
    (run / "A4/sources" / C / "src").mkdir(parents=True)
    (run / "A4/sources" / C / "src/model.py").write_text(CODE_TEXT)
    opened = {s: hashlib.sha256(t.encode()).hexdigest() for s, t in texts.items() if s != S}  # S 检查点之后才开放
    opened[C] = tree_sha256(run / "A4/sources" / C)
    rows = _a4_rows() if rows is None else rows
    snap = run / "snapshots/A4/k1"
    snap.mkdir(parents=True)
    (snap / "graph.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    nodes = sum("node" in r for r in rows)
    meta = {"arm": "A4", "group": "formal", "counts": {"nodes": nodes, "edges": len(rows) - nodes}}
    (snap / "meta.yml").write_text(yaml.safe_dump(meta))
    version = allowlist.a4_fingerprint(snap)
    (run / "backups/A4/k1").mkdir(parents=True)
    (run / "backups/A4/k1/meta.yml").write_text(yaml.safe_dump({"arm": "A4", "papers": 1, "version": version,
                                                                "sources": opened}))  # fmt: skip
    (run / "checkpoints.yml").write_text(yaml.safe_dump({"A4": {0: "nodes=0 edges=0 sha256=0", 1: version}}))
    (tmp_path / "bank/facts").mkdir(parents=True)
    (tmp_path / "bank/facts/tables.csv").write_text(f"table,arxiv,first,last,number\n{P}:T6,{P},6,9,1\n")
    return run


def _collect_a4(run: Path) -> dict:
    return collect(run, "A4", 1, run.parent / "bank")


def test_a4_collects_the_three_episode_fields_not_the_extracted_graph(tmp_path: Path) -> None:
    r = _collect_a4(_a4_run(tmp_path))
    got = sorted((o["channel"], o["ref"], o["where"]["episode"]) for o in r["origins"])
    assert got == sorted([("content", f"{P}::7:7", "ep-1"), ("content", f"{C}::src/model.py::20:20", "ep-1"),
                          ("name", f"{P}::11:11", "ep-1"), ("content", f"{P}::4:4", "ep-2"),
                          ("source_description", f"{Q}::3:3", "ep-2")])  # fmt: skip
    # 实体摘要与事实中的 13:13 是 Graphiti 改写过的文字，不放行；表内的行扩到整表
    assert r["readable"] == {P: [[3, 4], [6, 9], [11, 11]], Q: [[3, 3]], f"{C}::src/model.py": [[12, 28]]}
    assert [(d["reason"], d["ref"]) for d in r["dropped"]] == [("unopened", f"{U}::5:6")]
    assert set(r["stats"]["channels"]) == {"content", "name", "source_description"}
    assert r["stats"]["channels"]["content"]["mentions"] == 1  # 只写来源 ID 的 S
    assert r["checks"]["snapshot"] == {"nodes": 3, "edges": 2, "episodes": 2,
                                       "empty_fields": {"content": 0, "name": 0, "source_description": 0}}  # fmt: skip
    assert r["source_text"]["sources"] == {}


def test_a4_fingerprint_matches_the_writer_runs_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """timeline.version 对 Cypher 读出的行所算的指纹，与按快照重算的相同（Cypher 的行由快照的行构造，同 A4_CONTENT）。"""
    from pweval.harness import timeline

    rows = _a4_rows()
    records = []
    for r in rows:
        pairs = [[k, v] for k, v in r["props"].items() if not k.endswith("embedding")]
        if "node" in r:
            records.append({"what": "node", "id": r["node"], "kind": list(reversed(r["labels"])), "props": pairs})
        else:
            src, kind, dst = r["edge"]
            records.append({"what": "edge", "id": r["props"]["uuid"], "kind": [kind, src, dst], "props": pairs[::-1]})

    class Driver:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute_query(self, query, **params):
            assert query == timeline.A4_CONTENT and params == {"g": "formal"}
            return type("Result", (), {"records": records})()

    monkeypatch.setattr(timeline, "settle", lambda config: None)
    monkeypatch.setattr(timeline.export, "driver", lambda uri: Driver())
    config = {"arms": {"A4": {"neo4j": "bolt://x", "group_id": "formal"}}}
    run = _a4_run(tmp_path, rows)
    assert timeline.version(config, run, "A4") == allowlist.a4_fingerprint(run / "snapshots/A4/k1")


@pytest.mark.parametrize(
    ("damage", "message"),
    [
        (lambda run: _edit(run / "snapshots/A4/k1/graph.jsonl", "Leaderboard rows", "Board rows"), "disagree"),
        (lambda run: _edit(run / "backups/A4/k1/meta.yml", "version: nodes=3", "version: nodes=4"), "disagree"),
        (lambda run: _edit(run / "snapshots/A4/k1/meta.yml", "group: formal", "group: cats"), "not A4 group"),
        (lambda run: _edit(run / "snapshots/A4/k1/meta.yml", "nodes: 3", "nodes: 4"), "graph.jsonl has"),
        (lambda run: _edit(run / "snapshots/A4/k1/graph.jsonl", '"group_id": "formal", "fact"', '"group_id": "cats", "fact"'),
         "outside group"),
        (lambda run: _edit(run / "snapshots/A4/k1/graph.jsonl", '"source_description": "paper added"',
                           '"source_description": null'), "not a string"),
        (lambda run: _edit(run / "A4/sources" / P / "paper.md", "Para two.", "Para 2."), "sha256"),
        (lambda run: _edit(run / "backups/A4/k1/meta.yml", "arm: A4", "arm: A3"), "backup meta"),
    ],
)
def test_a4_damaged_inputs_stop_the_collection(tmp_path: Path, damage, message: str) -> None:
    run = _a4_run(tmp_path)
    damage(run)
    with pytest.raises(InputError, match=message):
        _collect_a4(run)
