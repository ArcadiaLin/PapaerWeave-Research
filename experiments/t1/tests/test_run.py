"""T1 的调度与任务文本：由配置确定，不依赖运行环境；会话记录中的请求出错与 A0 残留改动。"""

from __future__ import annotations

import http.server
import json
import subprocess
import threading
from pathlib import Path

import yaml

from t1 import seeding
from t1.paths import REPO, SEEDS
from t1.run import assign, check_checkpoint0, discard_leftovers, preflight, prompt, request_errors, schedule

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


def test_checkpoint0_holds_every_seed_verbatim(tmp_path: Path) -> None:
    snap = tmp_path / "checkpoints/0/A3"
    rows, docs = [], [d for pattern, _ in seeding.BATCHES for d in seeding.documents(pattern)]
    for i, doc in enumerate(docs, start=1):
        art, material, path = f"art_{i:04d}", f"material_{i:04x}", f"artifacts/{i}.v1.md"
        rows += [
            {"node": art, "labels": ["Artifact"], "props": {"id": art, "title": doc}},
            {"node": material, "labels": ["Material"], "props": {"id": material, "path": path}},
            {"edge": [material, "MATERIAL_OF", art], "props": {}},
        ]
        (snap / "documents" / path).parent.mkdir(parents=True, exist_ok=True)
        (snap / "documents" / path).write_text((SEEDS / doc).read_text(encoding="utf-8"), encoding="utf-8")
    (snap / "graph.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    commits = len(CONFIG["seed_docs"]) + len(seeding.BATCHES)
    lines = "".join(json.dumps({"seq": i}) + "\n" for i in range(commits))
    (snap / "commits.jsonl").write_text(lines, encoding="utf-8")
    assert check_checkpoint0(tmp_path, CONFIG) == []

    changed = snap / "documents/artifacts/1.v1.md"
    changed.write_text(changed.read_text(encoding="utf-8") + "edited\n", encoding="utf-8")
    assert check_checkpoint0(tmp_path, CONFIG) == [f"{docs[0]}: stored 0 times verbatim"]


PILOT3 = yaml.safe_load((REPO / "experiments/t1/config/pilot3-ltsf.yml").read_text(encoding="utf-8"))


def test_assignment_is_fixed_by_the_seed_and_overlaps_a_quarter() -> None:
    papers, users = list(range(8)), ["a", "b", "c", "d"]
    plan = assign(papers, users, seed=1, overlap=0.25)
    assert plan == assign(papers, users, seed=1, overlap=0.25)
    assert plan != assign(papers, users, seed=2, overlap=0.25)
    assert sum(len(p) == 2 for p in plan) == 2 and all(len(set(p)) == len(p) for p in plan)
    assert all(len(p) == 1 for p in assign(papers, users, seed=1, overlap=0))


def test_compositions_share_papers_order_and_sessions() -> None:
    single = schedule(PILOT3 | {"composition": "single"})
    multi = schedule(PILOT3 | {"composition": "multi"})
    assert [(s.paper["arxiv"], s.checkpoint) for s in single] == [(s.paper["arxiv"], s.checkpoint) for s in multi]
    assert {s.writer["id"] for s in single} == {"user-i3"}
    assert {s.writer["id"] for s in multi} <= set(PILOT3["compositions"]["multi"])
    assert len(single) == len(PILOT3["corpus"]["papers"]) + 2  # 25% 的 8 篇分给两个伪用户
    assert [s.checkpoint for s in single if s.checkpoint] == [1, 2, 3, 4] and single[-1].checkpoint == 4
    overlapped = [s for s in multi if sum(t.paper is s.paper for t in multi) == 2]
    assert overlapped and all(a.writer is not b.writer for a, b in zip(overlapped[::2], overlapped[1::2], strict=True))


def test_pseudo_user_prompt_is_background_plus_the_common_task() -> None:
    slot = schedule(PILOT3 | {"composition": "multi"})[0]
    text = prompt(PILOT3, "A0", slot, {"2106.13008": "Autoformer"})
    assert text.startswith(slot.writer["background"].rstrip())
    assert "Add this paper to the knowledge base your work uses." in text
    assert "leaderboard" not in text.lower() and "{" not in text


def test_preflight_names_the_services_that_do_not_answer(monkeypatch) -> None:
    class Models(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200 if self.path.endswith("/v1/models") else 404)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args) -> None:
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Models)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    up, down = f"http://127.0.0.1:{server.server_port}/v1", "http://127.0.0.1:9/v1"
    for key in ("EMBED_URL", "http_proxy", "HTTP_PROXY", "all_proxy", "ALL_PROXY"):
        monkeypatch.delenv(key, raising=False)
    config = {**PILOT3, "runner": {**PILOT3["runner"], "endpoints": {"A3": up, "A0": down},
                                   "embeddings_url": f"{up}/embeddings"}}
    try:
        problems = preflight(config, ["A3", "A0"])
    finally:
        server.shutdown()
    assert [p.split(" http")[0] for p in problems] == ["A0 model service"]
