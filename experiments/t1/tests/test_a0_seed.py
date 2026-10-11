"""A0 的检查点 0：由入库文档在内存中重放后渲染。需要本地的先导语料（data/ 不进版本管理），没有时跳过。"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml
from e09.config import REPO
from t1.a0_seed import commit_seed, render, seed_docs, write
from t1.replay import replay

CONFIG = REPO / "experiments/t1/config/pilot-ltsf.yml"


@pytest.fixture(scope="module")
def files() -> dict[str, str]:
    docs = seed_docs(CONFIG)
    if not all(path.is_file() for path, _ in docs):
        pytest.skip("pilot corpus not present (data/ is local only)")
    root = REPO / yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["corpus"]["material_root"]
    return render(replay(docs, root))


def test_rendering_is_deterministic(files: dict[str, str]) -> None:
    docs = seed_docs(CONFIG)
    root = REPO / yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["corpus"]["material_root"]
    assert render(replay(docs, root)) == files


def test_one_file_per_object_and_contents_inside_papers(files: dict[str, str]) -> None:
    assert {p.split("/")[0] for p in files} == {"README.md", "papers", "methods", "datasets", "tasks"}
    assert sorted(p for p in files if p.startswith("papers/")) == [
        "papers/informer-2012-07436.md",
        "papers/scinet-2106-09305.md",
    ]
    informer = files["papers/informer-2012-07436.md"]
    assert "## Experiment S3.T1" in informer and "## Claim 1" in informer and "## Contribution 4" in informer
    # 同名不同物的两个 Weather 各有一个文件；Autoformer 是桩
    assert "datasets/weather.md" in files and "datasets/weather-noaa-local-climatological-data.md" in files
    assert "known only from citations" in files["methods/autoformer.md"]


def test_sources_point_at_paper_notes(files: dict[str, str]) -> None:
    scinet = files["papers/scinet-2106-09305.md"]
    assert "sources: [SCINet: Time Series Modeling" in scinet and "material_" not in scinet


def test_seed_commit(tmp_path: Path, files: dict[str, str]) -> None:
    store = tmp_path / "store"
    write(files, store)
    commit_seed(store)
    git_log = ["git", "-C", str(store), "log", "--format=%an %D"]
    log = subprocess.run(git_log, capture_output=True, text=True, check=True)
    assert log.stdout.strip() == "seed HEAD -> main, tag: checkpoint-0"
