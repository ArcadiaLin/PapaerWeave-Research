"""参照组的读者（docs/designs/v3/evaluation.md §10）：P 按检查点取论文与有效题，断网，组单独的服务与并发。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from pweval.harness.refs import at_checkpoint, box_of, llm_of, papers_dir, workers_of
from pweval.harness.timeline import TIMING_ONLY, Timeline, papers_at

SEED, BUILT, LATER = "1111.11111v1", "2222.22222v1", "3333.33333v1"


@pytest.fixture
def timeline() -> Timeline:
    steps = [{"type": "build", "paper": BUILT, "seq": 1}, {"type": "checkpoint", "papers": 10},
             {"type": "build", "paper": LATER, "seq": 2}, {"type": "checkpoint", "papers": 20},
             {"type": "checkpoint", "papers": 30}]  # fmt: skip
    probes = [{"id": "early", "requires": [SEED, BUILT]}, {"id": "late", "requires": [SEED, LATER]}]
    aux = [{"id": "code", "requires": [SEED], "group": "auxiliary"}]
    return Timeline(steps, {}, {}, {"seed_papers": [SEED], "user": "r@lab"}, probes, aux)


def config(tmp_path: Path) -> dict:
    corpus = tmp_path / "corpus"
    for paper in (SEED, BUILT, LATER):
        (corpus / paper).mkdir(parents=True)
        (corpus / paper / "paper.md").write_text(paper)
        (corpus / paper / "meta.json").write_text("{}")
    return {"corpus_papers": corpus, "llm": "http://a:1/v1", "llm_by_group": {"P": "http://b:2/v1"},
            "runner": {"reader_workers": 12, "workers_by_group": {"P": 4}}}  # fmt: skip


def test_each_checkpoint_gets_only_the_papers_in_the_store_then(timeline: Timeline, tmp_path: Path) -> None:
    cfg, run = config(tmp_path), tmp_path / "run"
    k10, digest = papers_dir(cfg, timeline, run, 10)
    assert {p.name for p in k10.iterdir()} == {SEED, BUILT}
    manifest = json.loads((run / "P/papers/k10.manifest.json").read_text())
    assert sorted(manifest) == [f"{p}/{f}" for p in (SEED, BUILT) for f in ("meta.json", "paper.md")]
    assert papers_dir(cfg, timeline, run, 10)[1] == digest  # 续跑：副本不变，清单哈希不变
    assert {p.name for p in papers_dir(cfg, timeline, run, 20)[0].iterdir()} == papers_at(timeline, 20)
    (k10 / LATER).mkdir()  # 多出的论文：拒绝，不让读者看到检查点之后的论文
    with pytest.raises(SystemExit, match="not in the store"):
        papers_dir(cfg, timeline, run, 10)


@pytest.mark.parametrize("damage", ["missing", "changed", "extra"])
def test_a_damaged_copy_is_refused(timeline: Timeline, tmp_path: Path, damage: str) -> None:
    cfg, run = config(tmp_path), tmp_path / "run"
    target = papers_dir(cfg, timeline, run, 10)[0] / BUILT
    if damage == "missing":  # 复制中断留下的残缺目录
        (target / "paper.md").unlink()
    elif damage == "changed":
        (target / "paper.md").write_text("edited")
    else:
        (target / "notes.md").write_text("x")
    with pytest.raises(SystemExit, match="differs from the corpus copy"):
        papers_dir(cfg, timeline, run, 10)


def test_an_interrupted_copy_is_redone(timeline: Timeline, tmp_path: Path) -> None:
    cfg, run = config(tmp_path), tmp_path / "run"
    partial = run / "P/papers/k10" / f".{BUILT}.partial"  # 中断时只留下临时目录，正式目录还不存在
    shutil.copytree(cfg["corpus_papers"] / SEED, partial)
    k10, _ = papers_dir(cfg, timeline, run, 10)
    assert {p.name for p in k10.iterdir()} == {SEED, BUILT}
    assert (k10 / BUILT / "paper.md").read_text() == BUILT


def test_probes_follow_the_strict_rule_per_checkpoint(timeline: Timeline) -> None:
    chosen = [("main", p) for p in timeline.probes] + [("aux", p) for p in timeline.aux]
    assert [p["id"] for _, p in at_checkpoint(timeline, chosen, 10)] == ["early", "code"]
    assert [p["id"] for _, p in at_checkpoint(timeline, chosen, 20)] == ["early", "late", "code"]


def test_originals_use_their_own_service_and_concurrency_and_are_isolated(tmp_path: Path) -> None:
    cfg = config(tmp_path)
    assert (llm_of(cfg, "P"), llm_of(cfg, "C")) == ("http://b:2/v1", "http://a:1/v1")
    assert (workers_of(cfg, "P"), workers_of(cfg, "D")) == (4, 12)
    assert "workers_by_group" not in TIMING_ONLY  # P 的并发影响成本，改了要 --allow-config-change
    p = box_of(cfg, "P", tmp_path / "papers")
    assert p.isolated_llm == "http://b:2/v1" and p.papers == tmp_path / "papers" and p.pi_args == ()
    c = box_of(cfg, "C", None)
    assert c.isolated_llm is None and c.papers is None and "--no-tools" in c.pi_args
