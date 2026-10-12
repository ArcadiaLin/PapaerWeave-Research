"""T1 的调度与任务文本：由配置确定，不依赖运行环境；会话记录中的请求出错与 A0 残留改动。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import yaml
from e09.config import REPO
from t1.run import discard_leftovers, prompt, request_errors, schedule

CONFIG = yaml.safe_load((REPO / "experiments/t1/config/pilot-ltsf.yml").read_text(encoding="utf-8"))


def test_writers_alternate_and_checkpoints_follow_every_second_paper() -> None:
    slots = schedule(CONFIG)
    assert len(slots) == 17
    assert [s.writer["id"] for s in slots[:4]] == ["writer-i3", "writer-i2", "writer-i2", "writer-i3"]
    assert [s.paper["short"] for s in slots[:4]] == ["Autoformer", "Autoformer", "Query Selector", "Query Selector"]
    assert [(s.index, s.checkpoint) for s in slots if s.checkpoint] == [(4, 1), (8, 2), (13, 3), (17, 4)]
    assert [(s.index, s.writer["id"]) for s in slots if s.event] == [(9, "paper-maintainer")]  # 检查点 2 之后


def test_writers_get_the_first_version_and_the_maintainer_both() -> None:
    slots = schedule(CONFIG)
    titles = {p["arxiv"].rsplit("v", 1)[0]: "T" for p in CONFIG["corpus"]["papers"]}
    film = [prompt(CONFIG, "A3", s, titles) for s in slots if s.paper["short"] == "FiLM"]
    assert all("papers/2205.08897v3/paper.md" in p and "v4" not in p for p in film[:2])
    assert "material papers/2205.08897v4/paper.md" in film[2] and "material papers/2205.08897v3/paper.md" in film[2]
    assert "{" not in film[2]


def test_prompts_differ_between_arms_only_in_the_store_sentence() -> None:
    slot = schedule(CONFIG)[0]
    titles = {"2106.13008": "Autoformer: Decomposition Transformers"}
    a3, a0 = prompt(CONFIG, "A3", slot, titles), prompt(CONFIG, "A0", slot, titles)
    assert "papers/2106.13008v5/paper.md" in a3 and "Autoformer: Decomposition Transformers" in a3
    assert a3.replace(CONFIG["arms"]["A3"]["store"], "") == a0.replace(CONFIG["arms"]["A0"]["store"], "")
    assert "{" not in a3


def test_request_errors_are_the_assistant_messages_that_ended_in_error(tmp_path: Path) -> None:
    events = [
        {"type": "message_end", "message": {"role": "assistant", "stopReason": "toolUse"}},
        {"type": "message_end", "message": {"role": "assistant", "stopReason": "error", "errorMessage": "terminated"}},
        {"type": "turn_end", "message": {"role": "assistant", "stopReason": "error", "errorMessage": "terminated"}},
    ]
    path = tmp_path / "e.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in events) + "\nnot json\n", encoding="utf-8")
    assert request_errors(path) == ["terminated"]
    assert request_errors(tmp_path / "missing.jsonl") == []


def test_uncommitted_notes_are_saved_as_a_patch_and_discarded(tmp_path: Path) -> None:
    store = tmp_path / "store"
    git = ["git", "-C", str(store), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q", "-b", "main", str(store)], check=True)
    (store / "a.md").write_text("one\n", encoding="utf-8")
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-qm", "seed"], check=True)
    assert discard_leftovers(store, tmp_path / "none.patch") == [] and not (tmp_path / "none.patch").exists()

    (store / "a.md").write_text("two\n", encoding="utf-8")
    (store / "methods").mkdir()
    (store / "methods/new.md").write_text("draft\n", encoding="utf-8")
    assert discard_leftovers(store, tmp_path / "runs/left.patch") == ["a.md", "methods/new.md"]  # 补丁目录可以还不存在
    patch = (tmp_path / "runs/left.patch").read_text(encoding="utf-8")
    assert "+two" in patch and "+draft" in patch
    assert (store / "a.md").read_text(encoding="utf-8") == "one\n" and not (store / "methods").exists()
