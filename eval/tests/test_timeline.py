"""正式时间线的组装：任务文字的占位符、代码副本中新版本的仓库、联网命令的审计、A0 的起点。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from pweval.harness import timeline
from pweval.harness.timeline import Timeline

HINTS = {
    "a3": {"WRITE": "Record it as a {type} artifact.", "TOOLS": "Use the PaperWeave tools."},
    "a4": {"WRITE": "Record it as a memory.", "TOOLS": "Use the Graphiti memory tools."},
}
IDENTITIES = {"i3-a": {"id": "i3-a", "user": "u@lab.example", "background": "You maintain a benchmark.\n"}}


def test_prompt_fills_the_arm_hints_after_the_background() -> None:
    step = {"seq": 5, "identity": "i3-a", "type": "compare", "writes": "CompareSettings",
            "task": "Are they comparable? {WRITE} {TOOLS}"}  # fmt: skip
    tl = Timeline([step], IDENTITIES, HINTS)
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
