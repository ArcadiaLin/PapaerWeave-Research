"""正式时间线：任务文字的占位符、代码副本中新版本的仓库、联网命令的审计、A0 的起点、有效题、续跑与并发记账。"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tarfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from pweval.harness import timeline
from pweval.harness.sandbox import ENV_NOTE, WRITER_NOTE, Paths
from pweval.harness.timeline import Timeline

HINTS = {
    "a3": {"WRITE": "Record it as a {type} artifact.", "TOOLS": "Use the PaperWeave tools."},
    "a4": {"WRITE": "Record it as a memory.", "TOOLS": "Use the Graphiti memory tools."},
}
IDENTITIES = {"i3-a": {"id": "i3-a", "user": "u@lab.example", "background": "You maintain a benchmark.\n"}}
READER = {"user": "reader@lab.example", "seed_papers": ["s1"],
          "prompt": "{question}\n\nAnswer only from the store. {TOOLS}"}  # fmt: skip


def test_prompt_fills_the_arm_hints_after_the_background() -> None:
    step = {"seq": 5, "identity": "i3-a", "type": "compare", "writes": "CompareSettings",
            "task": "Are they comparable? {WRITE} {TOOLS}"}  # fmt: skip
    tl = Timeline([step], IDENTITIES, HINTS, READER, [])
    note = f"\n\n{ENV_NOTE}\n{WRITER_NOTE}\n"  # 环境说明（V3 §7 第 5 条）与写者的来源说明（f3 B2），各组相同
    assert timeline.prompt(tl, "A3", step) == (
        "You maintain a benchmark.\n\nAre they comparable? Record it as a CompareSettings artifact. "
        "Use the PaperWeave tools." + note
    )
    assert timeline.prompt(tl, "A4", step).endswith("Record it as a memory. Use the Graphiti memory tools." + note)
    build = {"seq": 1, "identity": "i3-a", "type": "build", "task": "Add the paper. {TOOLS}"}
    assert timeline.prompt(tl, "A3", build).endswith("Add the paper. Use the PaperWeave tools." + note)
    with pytest.raises(ValueError, match="placeholder"):
        timeline.prompt(tl, "A3", {**build, "task": "Add {paper}. {TOOLS}"})


CONFIG = {"arms": {"A3": {"neo4j": "bolt://x", "llm": "http://192.0.2.1:30000/v1"},
                   "A2": {"neo4j": "bolt://y", "llm": "http://192.0.2.1:30001/v1", "ablate": ["dedup"]},
                   "A0": {"llm": "http://192.0.2.1:30000/v1"},
                   "A4": {"graphiti": "http://127.0.0.1:8765/mcp/", "llm": "http://192.0.2.1:30001/v1"}}}  # fmt: skip


def test_every_writer_sandbox_is_cut_off_from_the_network(tmp_path: Path) -> None:
    config = {**CONFIG, "corpus_papers": tmp_path / "papers", "code": tmp_path / "code"}
    for arm in timeline.ARMS:
        box = timeline.sandbox_arm(config, tmp_path, arm, ["s1v1"], "x")
        assert box.isolated_llm == CONFIG["arms"][arm]["llm"]  # 只经转发连本组的大模型服务（V3 §7 第 5 条）
        assert box.isolated_tcp == (("127.0.0.1:8765",) if arm == "A4" else ())  # A4 另转发 Graphiti
        assert box.papers is None and box.code is None  # f3 §2：不挂载论文与代码
        assert box.read_source is not None and box.read_source.opened == ("s1v1",)  # 四组接法相同
    assert timeline.sandbox_arm(config, tmp_path, "A3").sources == tmp_path / "A3/sources"
    assert timeline.sandbox_arm(config, tmp_path, "A2").ablate == ("dedup",)


def test_graph_readers_read_papers_only_through_recorded_anchors(tmp_path: Path) -> None:
    for arm in ("A3", "A2"):  # V3 §2.2：只能经库读原文，不能浏览
        box = timeline.reader_arm(CONFIG, tmp_path, arm, 10)
        assert box.read_only and box.evidence_scope == "anchored" and box.papers is None


def test_a_writer_session_is_archived_after_it_ends(tmp_path: Path) -> None:
    paths = Paths(tmp_path / "A3/sessions/007-x")
    (paths.work / "sources/2106.13008v5").mkdir(parents=True)
    (paths.work / "sources/2106.13008v5/paper.md").write_text("# p\n")
    (paths.work / "draft.yaml").write_text("graph-doc: 1\n")
    (paths.home / "sessions").mkdir(parents=True)
    (paths.home / "sessions/s.jsonl").write_text("{}\n")
    rec = timeline.archive(tmp_path, "A3", 7, paths, "after")
    assert re.fullmatch(r"A3/session-snapshots/007-after-\d{8}T\d{6}Z\.tar\.gz", rec["path"]) and len(rec["sha256"]) == 64
    with tarfile.open(tmp_path / rec["path"]) as tar:  # B4：/work（含 sources/）与 home
        assert {"work/draft.yaml", "home/sessions/s.jsonl", "work/sources/2106.13008v5/paper.md"} <= set(tar.getnames())
    a0 = tmp_path / "A0/repo"
    a0.mkdir(parents=True)
    (a0 / "AGENTS.md").write_text("x\n")
    rec = timeline.archive(tmp_path, "A0", 12, Paths(tmp_path / "A0/sessions/012-x"), "after")
    with tarfile.open(tmp_path / rec["path"]) as tar:
        assert "work/AGENTS.md" in tar.getnames()  # A0 的工作目录是共享仓库
    assert not list((tmp_path / "A0/session-snapshots").glob("*.partial"))


MATERIALS = {
    "seed": ["2012.07436v3"],
    "sessions": [
        {"seq": 1, "type": "build", "named": ["2106.13008v5"], "opens": ["2106.13008v5"]},
        {"seq": 2, "type": "compare", "named": ["2012.07436v3", "2106.13008v5"]},
        {"seq": 3, "type": "note-i6", "named": ["2106.13008v5", "Autoformer@09994619"], "opens": ["Autoformer@09994619"]},
    ],
}


def _corpus(tmp_path: Path) -> tuple[dict, Timeline]:
    from pweval.harness.source_server import tree_sha256

    papers, code = tmp_path / "corpus/papers", tmp_path / "corpus/code"
    for source in ("2012.07436v3", "2106.13008v5", "2205.08897v4"):
        (papers / source).mkdir(parents=True)
        (papers / source / "paper.md").write_text(f"# {source}\n")
    (code / "Autoformer@09994619/layers").mkdir(parents=True)
    (code / "Autoformer@09994619/layers/a.py").write_text("x = 1\n")
    hashes = {s: timeline._sha256(papers / s / "paper.md") for s in ("2012.07436v3", "2106.13008v5")}
    hashes["Autoformer@09994619"] = tree_sha256(code / "Autoformer@09994619")
    materials = {**MATERIALS, "sources": {s: {"sha256": h} for s, h in hashes.items()}}
    return {"corpus_papers": papers, "code": code}, Timeline([], IDENTITIES, HINTS, READER, [], [], materials)


def test_sources_open_when_the_session_that_first_gives_them_starts(tmp_path: Path) -> None:
    """f3 §3.2、B1：种子在起点开放，此后按会话开放、一直可读；点出不开放；复制前按材料表核对哈希。"""
    config, tl = _corpus(tmp_path)
    assert tl.opened_through(0) == ["2012.07436v3"]
    assert tl.opened_through(2) == ["2012.07436v3", "2106.13008v5"] and tl.opens(2) == []
    assert tl.opened_through(3)[-1] == "Autoformer@09994619" and tl.named(3) == ["2106.13008v5", "Autoformer@09994619"]
    assert timeline.materials_record(tl, 2) == {"named": ["2012.07436v3", "2106.13008v5"], "opens": [], "available": 2}
    run = tmp_path / "run"
    assert timeline.open_sources(config, tl, run, "A3", tl.opened_through(1)) == ["2012.07436v3", "2106.13008v5"]
    assert timeline.open_sources(config, tl, run, "A3", tl.opened_through(2)) == []
    timeline.open_sources(config, tl, run, "A3", tl.opened_through(3))
    root = timeline.sources_dir(run, "A3")
    assert sorted(p.name for p in root.iterdir()) == ["2012.07436v3", "2106.13008v5", "Autoformer@09994619"]
    assert (root / "Autoformer@09994619/layers/a.py").read_text() == "x = 1\n"
    (config["corpus_papers"] / "2106.13008v5/paper.md").write_text("changed\n")
    with pytest.raises(RuntimeError, match="the corpus copy does not match materials.yml"):
        timeline.open_sources(config, tl, tmp_path / "other", "A3", tl.opened_through(1))
    (root / "2106.13008v5/paper.md").write_text("edited in place\n")  # 已开放的副本也每次核对（审查第 2 条）
    with pytest.raises(RuntimeError, match="the opened copy .* does not match materials.yml"):
        timeline.open_sources(config, tl, run, "A3", tl.opened_through(3))


def test_network_calls_are_recorded(tmp_path: Path) -> None:
    def call(command: str) -> str:
        content = [{"type": "toolCall", "name": "bash", "arguments": {"command": command}}]
        return json.dumps({"type": "message_end", "message": {"role": "assistant", "content": content}})

    events = tmp_path / "e.jsonl"
    events.write_text("\n".join([
        call("grep -n github papers/2106.13008v5/paper.md"),
        call("curl -s https://api.github.com/repos/thuml/Autoformer"),
        call("git clone https://github.com/x/y"),
        call("ls code"),
        "not json",
    ]))  # fmt: skip
    assert timeline.network_calls(events) == [
        "curl -s https://api.github.com/repos/thuml/Autoformer",
        "git clone https://github.com/x/y",
    ]


def test_a0_starts_from_the_kit_and_two_seed_commits(tmp_path: Path) -> None:
    seed = tmp_path / "seed"
    (seed / "a0/store/nodes/paper").mkdir(parents=True)
    (seed / "a0/store/nodes/paper/paper_0001.yaml").write_text("id: paper_0001\n")
    (seed / "a0/store/artifacts").mkdir(parents=True)
    (seed / "a0/store/artifacts/ETTh1.md").write_text("---\ntype: Leaderboard\n---\n")
    run = tmp_path / "run"
    timeline._seed_a0(run, seed)
    repo = run / "A0/repo"
    log = subprocess.run(["git", "-C", str(repo), "log", "--format=%an|%s"], capture_output=True, text=True).stdout
    assert log.splitlines() == [f"seed|{timeline.SEED_MESSAGES[1]}", f"seed|{timeline.SEED_MESSAGES[0]}",
                                "setup|Set up the shared repository"]  # fmt: skip
    assert (repo / "AGENTS.md").exists() and (repo / "templates/Note.md").exists()
    assert (repo / ".gitignore").read_text() == "papers/\ncode/\n"


def test_probes_count_once_all_their_papers_are_in() -> None:
    steps = [
        {"seq": 1, "type": "build", "paper": "p1v1"},
        {"seq": 2, "type": "build", "paper": "p2v1"},
        {"type": "checkpoint", "papers": 3},
        {"seq": 3, "type": "update", "paper": "p2v2", "from": "p2v1"},
        {"type": "checkpoint", "papers": 4},
    ]
    probes = [{"id": "a", "requires": ["s1", "p1v1"]}, {"id": "b", "requires": ["p2v2"]}, {"id": "c", "requires": ["p3v1"]}]
    tl = Timeline(steps, IDENTITIES, HINTS, READER, probes)
    assert timeline.papers_at(tl, 3) == {"s1", "p1v1", "p2v1"}
    assert [p["id"] for p in timeline.eligible(tl, 3)] == ["a"]
    assert [p["id"] for p in timeline.eligible(tl, 4)] == ["a", "b"]
    probe = {"id": "a", "question": "Which table?  "}
    assert timeline.reader_prompt(tl, "A4", probe) == "Which table?\n\nAnswer only from the store. Use the Graphiti memory tools."


def test_auxiliary_probes_follow_the_same_rule_and_go_to_their_own_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """辅助组的代码题按同样的严格规则作答，存在 k<篇数>-aux.jsonl，不混进主检验的回答。"""
    steps = [{"seq": 1, "type": "build", "paper": "p1v1"}, {"type": "checkpoint", "papers": 3}]
    tl = Timeline(steps, IDENTITIES, HINTS, READER, [{"id": "m", "requires": ["s1"]}],
                  [{"id": "x", "requires": ["p1v1"]}, {"id": "y", "requires": ["p9v1"]}])  # fmt: skip
    assert [p["id"] for p in timeline.eligible(tl, 3, "aux")] == ["x"]
    run = _run(tmp_path, {"A3": {0: "commit_000002", 3: "commit_000005"}})
    monkeypatch.setattr(timeline, "version", lambda *a: "commit_000005")
    monkeypatch.setattr(timeline, "reader_arm", lambda *a: None)
    monkeypatch.setattr(timeline, "answer", lambda *a: {"probe": a[5]["id"], "exit": 0, "seconds": 1, "answer": ""})
    config = {"runner": {"agent": "pi", "model": "m"}}
    for group in timeline.GROUPS:
        timeline.readers(config, tl, run, "A3", 3, group=group)
    assert timeline.answered(run, "A3", 3) == {"m"}
    assert timeline.answered(run, "A3", 3, "aux") == {"x"}
    assert timeline.answers_file(run, "A3", 3, "aux").name == "k3-aux.jsonl"


def test_answer_text_and_usage_come_from_the_event_stream(tmp_path: Path) -> None:
    def end(content: list, usage: dict) -> str:
        return json.dumps({"type": "message_end", "message": {"role": "assistant", "content": content, "usage": usage}})

    events = tmp_path / "e.jsonl"
    events.write_text("\n".join([
        end([{"type": "toolCall", "name": "mcp__PaperWeave__search", "arguments": {}}], {"input": 10, "cacheRead": 90, "output": 5}),
        end([{"type": "text", "text": "The answer [paper_0003]."}], {"input": 4, "cacheRead": 100, "output": 20}),
        end([{"type": "thinking", "thinking": "done"}], {"input": 1, "output": 1}),
    ]))  # fmt: skip
    assert timeline.final_text(events) == "The answer [paper_0003]."
    assert timeline.usage(events) == {"calls": 3, "input": 15, "cacheRead": 190, "output": 26}
    assert timeline.tool_counts(events) == {"mcp__PaperWeave__search": 1}


# ---------------------------------------------------------------- 续跑与并发（审核 2026-10-19 的五条）


def _run(tmp_path: Path, checkpoints: dict) -> Path:
    run = tmp_path / "run"
    run.mkdir()
    (run / "checkpoints.yml").write_text(yaml.safe_dump(checkpoints))
    return run


def test_a_finished_checkpoint_does_not_block_resuming(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """k10 答完、写者继续之后中断：续跑经过 k10 时不核对版本（库早已向前）；还有题没答时才核对。"""
    probes = [{"id": "a", "requires": ["s1"]}, {"id": "b", "requires": ["s1"]}]
    tl = Timeline([{"type": "checkpoint", "papers": 10}], IDENTITIES, HINTS, READER, probes)
    run = _run(tmp_path, {"A3": {0: "commit_000002", 10: "commit_000020"}})
    monkeypatch.setattr(timeline, "version", lambda *a: "commit_000031")
    (run / "answers/A3").mkdir(parents=True)
    (run / "answers/A3/k10.jsonl").write_text('{"probe": "a"}\n{"probe": "b"}\n')
    timeline.readers({}, tl, run, "A3", 10)  # 没有题要答：不报错
    (run / "answers/A3/k10.jsonl").write_text('{"probe": "a"}\n')
    with pytest.raises(RuntimeError, match="moved past checkpoint 10"):
        timeline.readers({}, tl, run, "A3", 10)


def test_checkpoints_are_never_read_half_written(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """一组写检查点时，另一组读到的总是完整内容（读到空文件会误以为没有检查点 0，从而重建起点）。"""
    run = _run(tmp_path, {"A3": {0: "commit_000002"}})
    monkeypatch.setattr(timeline, "version", lambda *a: "v")
    stop = threading.Event()

    def write() -> None:
        for k in range(300):
            timeline.checkpoint({}, run, "A2", k)
        stop.set()

    writer = threading.Thread(target=write)
    writer.start()
    reads = 0
    while not stop.is_set():
        assert timeline.checkpoints(run)["A3"] == {0: "commit_000002"}
        reads += 1
    writer.join()
    assert reads and len(timeline.checkpoints(run)["A2"]) == 300
    assert not list(run.glob("*.tmp"))


def _resume_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, now: str) -> tuple[Path, Timeline, list]:
    step = {"seq": 1, "identity": "i3-a", "type": "build", "paper": "p1v1", "task": "Add it. {TOOLS}"}
    tl = Timeline([step], IDENTITIES, HINTS, READER, [], [], {"seed": [], "sessions": [{"seq": 1, "opens": []}]})
    run = _run(tmp_path, {"A3": {0: "commit_000002"}})
    started = time.time() - 60
    (run / "A3").mkdir()
    inflight = {"seq": 1, "root": "A3/sessions/001-a", "started": "t", "started_epoch": started,
                "version_before": "commit_000002"}  # fmt: skip
    (run / "A3/inflight.json").write_text(json.dumps(inflight))
    events = run / "A3/sessions/001-a/runs/20261019T120000.jsonl"
    events.parent.mkdir(parents=True)
    events.write_text("")
    (run / "A3/sessions/001-a/work").mkdir()
    (run / "A3/sessions/001-a/work/draft.yaml").write_text("left by the interrupted attempt\n")
    calls: list = []
    monkeypatch.setattr(timeline, "version", lambda *a: now)
    monkeypatch.setattr(timeline, "snapshot", lambda *a: None)
    monkeypatch.setattr(timeline, "session", lambda *a: calls.append(a) or {
        "arm": "A3", "seq": 1, "exit": 0, "seconds": 1.0, "network": []})  # fmt: skip
    return run, tl, calls


def test_a_session_that_changed_the_store_is_not_rerun(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """写者已提交、会话尚未记账时中断：续跑不再跑一遍，按中断记账，事件流取中断前那一份。"""
    run, tl, calls = _resume_setup(tmp_path, monkeypatch, now="commit_000003")
    config = {"arms": {"A3": {"llm": "http://llm"}}, "runner": {"agent": "pi", "model": "m"}}
    timeline.run_arm(config, tl, run, "A3", None, False, with_readers=False)
    assert calls == []
    (record,) = [json.loads(line) for line in (run / "sessions.jsonl").read_text().splitlines()]
    assert record["exit"] == "interrupted" and record["recovered"] is True
    assert record["version_before"] == "commit_000002" and record["version_after"] == "commit_000003"
    assert record["events"] == "A3/sessions/001-a/runs/20261019T120000.jsonl"
    assert record["root"] == "A3/sessions/001-a" and "-interrupted-" in record["archive"]["path"]
    assert not (run / "A3/inflight.json").exists()


def test_a_session_that_left_the_store_unchanged_is_rerun(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """B4：库没变就重跑；被中断那次归档为 interrupted，重跑不继承它的文件（在全新目录中，见 session_paths）。"""
    run, tl, calls = _resume_setup(tmp_path, monkeypatch, now="commit_000002")
    timeline.run_arm({"arms": {"A3": {}}, "runner": {"agent": "pi", "model": "m"}}, tl, run, "A3", None, False)
    assert len(calls) == 1
    (record,) = [json.loads(line) for line in (run / "sessions.jsonl").read_text().splitlines()]
    rerun_of = record["rerun_after_interruption"]
    assert rerun_of["version_before"] == "commit_000002" and rerun_of["root"] == "A3/sessions/001-a"
    assert "rerun_inherits_workdir" not in record
    with tarfile.open(run / rerun_of["archive"]["path"]) as tar:
        assert tar.extractfile("work/draft.yaml").read() == b"left by the interrupted attempt\n"
    assert not (run / "A3/inflight.json").exists()


class _FakeDriver:
    def __init__(self, nodes: int) -> None:
        self.nodes, self.queries = nodes, []

    def __enter__(self) -> _FakeDriver:
        return self

    def __exit__(self, *exc: object) -> None:
        pass

    def execute_query(self, query: str, **params: object) -> SimpleNamespace:
        self.queries.append(query)
        return SimpleNamespace(records=[{"n": self.nodes}])


def test_a4_seed_needs_an_empty_group(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Graphiti 的服务与 group 跨运行共用：group 不空时不写种子，除非 --reset。"""
    fake = _FakeDriver(nodes=42)
    monkeypatch.setattr(timeline.export, "driver", lambda uri: fake)
    monkeypatch.setattr(timeline, "settle", lambda config: None)
    config = {"arms": {"A4": {"neo4j": "bolt://localhost:7698", "group_id": "formal", "graphiti": "http://x"}}}
    with pytest.raises(SystemExit, match="holds 42 nodes"):
        timeline._seed_a4(config, tmp_path, reset=False)
    assert not any("DELETE" in q for q in fake.queries)


def test_the_start_is_not_rebuilt_once_sessions_are_recorded(tmp_path: Path) -> None:
    run = _run(tmp_path, {})
    (run / "sessions.jsonl").write_text('{"arm": "A3", "seq": 1}\n')
    tl = Timeline([], IDENTITIES, HINTS, READER, [])
    with pytest.raises(SystemExit, match="refusing to rebuild"):
        timeline.setup({}, tl, run, "A3", reset=True)


def test_resuming_with_a_changed_config_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    probes = tmp_path / "probes"
    probes.mkdir()
    for args in (["init", "-q"], ["commit", "-q", "--allow-empty", "-m", "x"]):
        subprocess.run(["git", "-C", str(probes), "-c", "user.name=t", "-c", "user.email=t", *args], check=True)
    monkeypatch.setattr(timeline, "pi_version", lambda: "pi 1.2.0")
    run = _run(tmp_path, {})
    config_file = tmp_path / "c.yml"
    config_file.write_text("x: 1\n")
    config = {"probes_repo": probes, "arms": {"A3": {"neo4j": "bolt://a"}}, "runner": {"model": "m", "reader_workers": 4}}
    timeline._record_run(run, config_file, config, ["f1"])
    timeline._record_run(run, config_file, {**config, "runner": {"model": "m", "reader_workers": 2}}, ["f1"])
    moved = {**config, "arms": {"A3": {"neo4j": "bolt://b"}}}
    with pytest.raises(SystemExit, match="config differ"):
        timeline._record_run(run, config_file, moved, ["f1"])
    timeline._record_run(run, config_file, moved, ["f1"], allow_change=True)
    invocations = yaml.safe_load((run / "run.yml").read_text())["invocations"]
    assert [i["config"]["arms"]["A3"]["neo4j"] for i in invocations] == ["bolt://a", "bolt://a", "bolt://b"]
    assert invocations[0]["config"]["probes_repo"] == str(probes)


# ---------------------------------------------------------------- 复审 2026-10-19 的三条与 A4 的内容指纹


def _a0_repo(tmp_path: Path) -> Path:
    run = tmp_path / "run"
    repo = run / "A0/repo"
    repo.mkdir(parents=True)
    (repo / ".gitignore").write_text("papers/\n")
    (repo / "note.md").write_text("v1\n")
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t"]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "x"], check=True)
    return run


def test_a0_worktree_fingerprint_sees_content_not_just_status(tmp_path: Path) -> None:
    """前一会话留下 ` M note.md`，这一会话再改它而不提交：git status 前后相同，内容指纹不同。"""
    run = _a0_repo(tmp_path)
    repo = run / "A0/repo"
    (repo / "note.md").write_text("v2\n")
    status, before = timeline._a0_status(run), timeline._a0_worktree(run)
    (repo / "note.md").write_text("v3\n")
    assert timeline._a0_status(run) == status and timeline._a0_worktree(run) != before
    (repo / "new.md").write_text("a\n")
    untracked = timeline._a0_worktree(run)
    (repo / "new.md").write_text("b\n")
    assert timeline._a0_worktree(run) != untracked  # 未跟踪文件的内容也在内
    (repo / "papers").mkdir()
    (repo / "papers/x.md").write_text("ignored\n")
    assert timeline._a0_worktree(run) == timeline._a0_worktree(run) != untracked
    assert timeline._a0_status(run) == [" M note.md", "?? new.md"]  # 仓库自己的索引没有被动过


def test_a_torn_last_line_is_set_aside_and_the_log_stays_appendable(tmp_path: Path) -> None:
    path = tmp_path / "sessions.jsonl"
    path.write_bytes(b'{"arm": "A3", "seq": 1}\n{"arm": "A3", "se')
    assert timeline.read_jsonl(path) == [{"arm": "A3", "seq": 1}]
    assert path.read_bytes() == b'{"arm": "A3", "seq": 1}\n'
    (torn,) = tmp_path.glob("sessions.jsonl.torn-*")
    assert torn.read_bytes() == b'{"arm": "A3", "se'
    timeline.append_jsonl(path, {"arm": "A3", "seq": 2})
    assert [r["seq"] for r in timeline.read_jsonl(path)] == [1, 2]


def test_a_complete_last_line_without_newline_is_kept(tmp_path: Path) -> None:
    path = tmp_path / "k10.jsonl"
    path.write_bytes('{"probe": "a"}\n{"probe": "é"}'.encode())
    assert [r["probe"] for r in timeline.read_jsonl(path)] == ["a", "é"]
    timeline.append_jsonl(path, {"probe": "c"})
    assert [r["probe"] for r in timeline.read_jsonl(path)] == ["a", "é", "c"]


def test_damage_in_the_middle_of_a_log_is_an_error(tmp_path: Path) -> None:
    path = tmp_path / "sessions.jsonl"
    path.write_bytes(b'{"seq": 1}\n{"seq"\n{"seq": 3}\n')
    with pytest.raises(RuntimeError, match=":2: damaged record"):
        timeline.read_jsonl(path)


def test_an_incomplete_snapshot_is_not_taken_as_done(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run = tmp_path / "run"
    out = run / "snapshots/A0/k10"
    out.mkdir(parents=True)
    (out / "meta.yml").write_text("")  # 导出中断留下的空元数据
    (run / "snapshots/A0/k10.partial").mkdir()
    exported = []

    def export_a0(store: Path, tag: str, target: Path) -> None:
        target.mkdir(parents=True)
        (target / "tree").mkdir()
        (target / "log.jsonl").write_text("")
        (target / "meta.yml").write_text(yaml.safe_dump({"arm": "A0", "counts": {"files": 0, "commits": 1}}))
        exported.append(tag)

    monkeypatch.setattr(timeline.export, "export_a0", export_a0)
    timeline.snapshot({"arms": {"A0": {}}}, run, "A0", 10)
    assert exported == ["checkpoint-10"] and timeline.snapshot_complete(out, "A0")
    assert len(list((run / "snapshots/A0").glob("k10.invalid-*"))) == 1
    assert not (run / "snapshots/A0/k10.partial").exists()
    timeline.snapshot({"arms": {"A0": {}}}, run, "A0", 10)
    assert exported == ["checkpoint-10"]  # 完整的快照不再导出


def test_a4_version_changes_with_any_content(monkeypatch: pytest.MonkeyPatch) -> None:
    """只改实体摘要也会改变 A4 的版本（复审指出指纹参与决定是否重跑会话）。"""
    rows = [
        {"what": "node", "id": "u1", "kind": ["Entity", "Method"], "props": [["name", "PatchTST"], ["summary", "a"]]},
        {"what": "edge", "id": "e1", "kind": ["RELATES_TO", "u1", "u2"], "props": [["fact", "x"]]},
    ]

    class Driver(_FakeDriver):
        def execute_query(self, query: str, **params: object) -> SimpleNamespace:
            return SimpleNamespace(records=rows)

    monkeypatch.setattr(timeline.export, "driver", lambda uri: Driver(0))
    monkeypatch.setattr(timeline, "settle", lambda config: None)
    config = {"arms": {"A4": {"neo4j": "bolt://x", "group_id": "formal"}}}
    first = timeline.version(config, Path("."), "A4")
    assert first.startswith("nodes=1 edges=1 sha256=")
    rows[0]["props"] = [["summary", "a"], ["name", "PatchTST"]]  # 顺序不同、内容相同
    assert timeline.version(config, Path("."), "A4") == first
    rows[0]["props"] = [["name", "PatchTST"], ["summary", "b"]]
    assert timeline.version(config, Path("."), "A4") != first
    rows[0]["props"] = [["name", "PatchTST"], ["summary", "a"]]
    rows[1]["kind"] = ["RELATES_TO", "u2", "u1"]  # 方向反了
    assert timeline.version(config, Path("."), "A4") != first


@pytest.mark.parametrize(
    ("meta", "complete"),
    [
        ("arm: A0\ncounts:\n", False),  # 旧导出中断在 counts: 之后
        ("arm: A0\ncounts: {files: 3}\n", False),  # 缺 commits
        ("arm: A0\ncounts: {files: 3, commits: '2'}\n", False),
        ("arm: A0\ncounts: {files: 3, commits: true}\n", False),
        ("arm: A3\ncounts: {files: 3, commits: 2}\n", False),  # 别的组的元数据
        ("arm: A0\ncounts: {files: 3, commits: 2}\n", True),
    ],
)
def test_snapshot_metadata_is_checked_field_by_field(tmp_path: Path, meta: str, complete: bool) -> None:
    (tmp_path / "tree").mkdir()
    (tmp_path / "log.jsonl").write_text("")
    (tmp_path / "meta.yml").write_text(meta)
    assert timeline.snapshot_complete(tmp_path, "A0") is complete


# ---------------------------------------------------------------- 两个进程写同一个运行目录（监视者单独续跑一组）

_APPENDER = """
import sys
from pathlib import Path
from pweval.harness import timeline
for i in range(200):
    timeline.append_jsonl(Path(sys.argv[1]), {"who": sys.argv[2], "i": i, "pad": "x" * 2000})
    timeline.checkpoint({}, Path(sys.argv[3]), sys.argv[2], i) if i % 20 == 0 else None
"""


def test_two_processes_share_the_records(tmp_path: Path) -> None:
    run = _run(tmp_path, {})
    path = run / "sessions.jsonl"
    script = tmp_path / "append.py"
    script.write_text(_APPENDER.replace("timeline.checkpoint({}", "timeline.version = lambda *a: 'v'; timeline.checkpoint({}"))
    procs = [subprocess.Popen([sys.executable, str(script), str(path), who, str(run)]) for who in ("A3", "A2")]
    assert [p.wait(timeout=60) for p in procs] == [0, 0]
    records = timeline.read_jsonl(path)
    assert len(records) == 400 and not list(tmp_path.rglob("*.torn-*"))
    assert {who: sorted(ks) for who, ks in timeline.checkpoints(run).items()} == {
        "A2": list(range(0, 200, 20)), "A3": list(range(0, 200, 20))}  # fmt: skip


def test_an_arm_runs_in_one_process_at_a_time(tmp_path: Path) -> None:
    run = tmp_path / "run"
    holder = subprocess.Popen([sys.executable, "-c", (
        "import sys, time; from pathlib import Path; from pweval.harness import timeline\n"
        "with timeline._arm_lock(Path(sys.argv[1]), 'A3') as mine:\n"
        "    print(mine, flush=True); time.sleep(30)\n"), str(run)], stdout=subprocess.PIPE, text=True)  # fmt: skip
    try:
        assert holder.stdout.readline().strip() == "True"
        with timeline._arm_lock(run, "A3") as mine:
            assert mine is False
        with timeline._arm_lock(run, "A2") as mine:
            assert mine is True
    finally:
        holder.kill()
        holder.wait()
    with timeline._arm_lock(run, "A3") as mine:
        assert mine is True  # 持有的进程退出，锁随之释放


def test_every_attempt_gets_a_fresh_directory(tmp_path: Path) -> None:
    """f3 §2.1：同一序号的两次尝试、同一身份的两个会话，目录都不同，也都是新建的。"""
    first = timeline.session_paths(tmp_path, "A3", 7)
    second = timeline.session_paths(tmp_path, "A3", 7)
    assert first.root != second.root and first.root.parent == tmp_path / "A3/sessions"
    assert first.root.name.startswith("007-") and not first.root.exists()


def _backup_config(tmp_path: Path) -> dict:
    return {"arms": {"A3": {"neo4j": "bolt://x", "neo4j_container": "neo4j-a3", "llm": "http://h:1/v1"}}}


def test_the_checkpoint_store_is_dumped_offline_and_restarted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "A3/data/artifacts").mkdir(parents=True)
    (tmp_path / "A3/data/artifacts/lb.v1.md").write_text("x\n")
    calls = []

    def docker(*args: str) -> str:
        calls.append(args[0])
        if args[0] == "inspect":
            return json.dumps([{"HostConfig": {"AutoRemove": False}, "Config": {"Image": "neo4j:ubi10"},
                                "Mounts": [{"Source": "/srv/a3/data", "Destination": "/data"}]}])  # fmt: skip
        if args[0] == "run":
            assert args[args.index("-v") + 1] == "/srv/a3/data:/data" and args[-2:] == ("neo4j", "--to-path=/backups")
            Path(args[args.index("-v", args.index("-v") + 1) + 1].split(":")[0], "neo4j.dump").write_bytes(b"dump")
        return ""

    monkeypatch.setattr(timeline, "_docker", docker)
    monkeypatch.setattr(timeline, "checkpoints", lambda run: {"A3": {10: "commit_000020"}})
    monkeypatch.setattr(timeline, "version", lambda config, run, arm: "commit_000020")
    timeline.backup(_backup_config(tmp_path), tmp_path, "A3", 10)
    assert calls == ["inspect", "stop", "run", "start"]
    out = tmp_path / "backups/A3/k10"
    meta = yaml.safe_load((out / "meta.yml").read_text())
    assert meta["version"] == "commit_000020" and set(meta["sha256"]) == {"neo4j.dump", "data.tar.gz"}
    with tarfile.open(out / "data.tar.gz") as tar:
        assert "data/artifacts/lb.v1.md" in tar.getnames()
    calls.clear()
    timeline.backup(_backup_config(tmp_path), tmp_path, "A3", 10)  # 已有完整备份：不再停库
    assert calls == []
    (out / "neo4j.dump").write_bytes(b"changed")
    assert not timeline.backup_complete(out, "A3")  # 哈希不符即不完整


def test_the_store_is_restarted_even_if_the_dump_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "A3/data").mkdir(parents=True)
    calls = []

    def docker(*args: str) -> str:
        calls.append(args[0])
        if args[0] == "inspect":
            return json.dumps([{"HostConfig": {}, "Config": {"Image": "i"}, "Mounts": [{"Source": "/d", "Destination": "/data"}]}])
        if args[0] == "run":
            raise RuntimeError("docker run failed")
        return ""

    monkeypatch.setattr(timeline, "_docker", docker)
    monkeypatch.setattr(timeline, "checkpoints", lambda run: {"A3": {10: "c"}})
    monkeypatch.setattr(timeline, "version", lambda config, run, arm: "c")
    with pytest.raises(RuntimeError, match="docker run failed"):
        timeline.backup(_backup_config(tmp_path), tmp_path, "A3", 10)
    assert calls[-1] == "start" and not (tmp_path / "backups/A3/k10").exists()


def test_a_container_started_with_rm_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    info = [{"HostConfig": {"AutoRemove": True}, "Config": {"Image": "i"}, "Mounts": []}]
    monkeypatch.setattr(timeline, "_docker", lambda *args: json.dumps(info))
    with pytest.raises(RuntimeError, match="--rm"):
        timeline.container_of("neo4j-test")
