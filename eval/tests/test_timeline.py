"""正式时间线：任务文字的占位符、代码副本中新版本的仓库、联网命令的审计、A0 的起点、有效题、续跑与并发记账。"""

from __future__ import annotations

import json
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from pweval.harness import timeline
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
    assert timeline.prompt(tl, "A3", step) == (
        "You maintain a benchmark.\n\nAre they comparable? Record it as a CompareSettings artifact. "
        "Use the PaperWeave tools.\n"
    )
    assert timeline.prompt(tl, "A4", step).endswith("Record it as a memory. Use the Graphiti memory tools.\n")
    build = {"seq": 1, "identity": "i3-a", "type": "build", "task": "Add the paper. {TOOLS}"}
    assert timeline.prompt(tl, "A3", build).endswith("Add the paper. Use the PaperWeave tools.\n")
    with pytest.raises(ValueError, match="placeholder"):
        timeline.prompt(tl, "A3", {**build, "task": "Add {paper}. {TOOLS}"})


def _code(root: Path) -> Path:
    src = root / "code"
    for name in ("FiLM@ccd65d69", "FiLM@88af1c0c", "Autoformer@09994619"):
        (src / name).mkdir(parents=True)
        (src / name / "x.py").write_text("pass\n")
    (src / "README.md").write_text(
        "# Code\n\n| directory | repository | commit | commit date | paper versions (papers/) |\n| --- | --- | --- | --- | --- |\n"
        "| Autoformer@09994619/ | u | c | d | 2106.13008v5 |\n"
        "| FiLM@88af1c0c/ | u | c | d | 2205.08897v4 |\n"
        "| FiLM@ccd65d69/ | u | c | d | 2205.08897v3 |\n"
    )
    return src


def test_code_for_a_later_version_arrives_with_the_update(tmp_path: Path) -> None:
    config = {"code": _code(tmp_path)}
    target = tmp_path / "arm/code"
    timeline.sync_code(config, target, {"2205.08897v4"})
    assert sorted(p.name for p in target.iterdir()) == ["Autoformer@09994619", "FiLM@ccd65d69", "README.md"]
    assert "88af1c0c" not in (target / "README.md").read_text()
    timeline.sync_code(config, target, set())
    assert (target / "FiLM@88af1c0c/x.py").exists() and "88af1c0c" in (target / "README.md").read_text()


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
    tl = Timeline([step], IDENTITIES, HINTS, READER, [])
    run = _run(tmp_path, {"A3": {0: "commit_000002"}})
    started = time.time() - 60
    (run / "A3").mkdir()
    inflight = {"seq": 1, "started": "t", "started_epoch": started, "version_before": "commit_000002"}
    (run / "A3/inflight.json").write_text(json.dumps(inflight))
    events = run / "A3/writers/i3-a/runs/20261019T120000.jsonl"
    events.parent.mkdir(parents=True)
    events.write_text("")
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
    assert record["events"] == "A3/writers/i3-a/runs/20261019T120000.jsonl"
    assert not (run / "A3/inflight.json").exists()


def test_a_session_that_left_the_store_unchanged_is_rerun(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run, tl, calls = _resume_setup(tmp_path, monkeypatch, now="commit_000002")
    timeline.run_arm({}, tl, run, "A3", None, False, with_readers=False)
    assert len(calls) == 1
    (record,) = [json.loads(line) for line in (run / "sessions.jsonl").read_text().splitlines()]
    assert record["rerun_after_interruption"]["version_before"] == "commit_000002"
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
