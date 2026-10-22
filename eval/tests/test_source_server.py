"""来源服务 read_source（工程记录 B3）：按开放的来源 ID 交付到会话目录，拒绝不泄露，逐次记录。"""

from __future__ import annotations

import io
import json
import os
import stat
import sys
from pathlib import Path

import pytest

from pweval.harness.mcp_client import Client
from pweval.harness.source_server import REFUSED, Sources, handle, serve, tree_sha256


@pytest.fixture
def corpus(tmp_path: Path) -> tuple[Path, Path]:
    papers, code = tmp_path / "papers", tmp_path / "code"
    for source in ("2106.13008v5", "2205.08897v3", "2205.08897v4", "2403.01673v1"):
        (papers / source).mkdir(parents=True)
        (papers / source / "paper.md").write_text(f"# {source}\nline 2\nline 3\n", encoding="utf-8")
    (code / "Autoformer@09994619/layers").mkdir(parents=True)
    (code / "Autoformer@09994619/layers/AC.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
    (code / "Autoformer@09994619/README.md").write_text("# Autoformer\n", encoding="utf-8")
    return papers, code


def sources(corpus: tuple[Path, Path], tmp_path: Path, opened: list[str]) -> Sources:
    papers, code = corpus
    return Sources(papers, code, opened, tmp_path / "work/sources", "/work/sources", tmp_path / "sources.jsonl", "s-1")


def log(tmp_path: Path) -> list[dict]:
    return [json.loads(line) for line in (tmp_path / "sources.jsonl").read_text(encoding="utf-8").splitlines()]


def test_a_paper_is_delivered_read_only_and_reused(corpus: tuple[Path, Path], tmp_path: Path) -> None:
    s = sources(corpus, tmp_path, ["2106.13008v5"])
    out, error = s.fetch("2106.13008v5")
    assert not error and out["path"] == "/work/sources/2106.13008v5/paper.md" and out["lines"] == 3 and not out["reused"]
    local = tmp_path / "work/sources/2106.13008v5/paper.md"
    assert local.read_text(encoding="utf-8").startswith("# 2106.13008v5")
    assert not os.access(local, os.W_OK) or os.geteuid() == 0
    assert stat.S_IMODE(local.stat().st_mode) == 0o444
    again, _ = s.fetch(" 2106.13008v5 ")
    assert again["reused"] and again["intact"]
    assert len(json.dumps(out)) < 1024
    assert [r["outcome"] for r in log(tmp_path)] == ["delivered", "reused"]


def test_refusals_do_not_tell_unopened_from_missing(corpus: tuple[Path, Path], tmp_path: Path) -> None:
    s = sources(corpus, tmp_path, ["2205.08897v3"])
    unopened, error = s.fetch("2205.08897v4")
    missing, _ = s.fetch("2301.00001v1")
    assert error and unopened == missing == {"error": REFUSED}
    fmt, _ = s.fetch("arXiv:2205.08897v3")
    path, _ = s.fetch("papers/2205.08897v3/paper.md")
    assert "write the id alone" in fmt["error"] and "write the id alone" in path["error"]
    reasons = [(r["outcome"], r.get("reason")) for r in log(tmp_path)]
    assert reasons[:2] == [("refused", "not opened yet"), ("refused", "not in the corpus")]
    assert not (tmp_path / "work/sources/2205.08897v4").exists()


def test_an_id_without_version_gives_the_latest_opened(corpus: tuple[Path, Path], tmp_path: Path) -> None:
    s = sources(corpus, tmp_path, ["2205.08897v3"])
    assert s.fetch("2205.08897")[0]["source_id"] == "2205.08897v3"  # v4 未开放
    s = sources(corpus, tmp_path / "later", ["2205.08897v3", "2205.08897v4"])
    assert s.fetch("2205.08897")[0]["source_id"] == "2205.08897v4"


def test_code_comes_with_a_manifest_outside_the_tree(corpus: tuple[Path, Path], tmp_path: Path) -> None:
    s = sources(corpus, tmp_path, ["Autoformer@09994619"])
    out, error = s.fetch("Autoformer@09994619")
    assert not error and out == {
        "source_id": "Autoformer@09994619", "kind": "code", "root": "/work/sources/Autoformer@09994619/",
        "files": 2, "manifest": "/work/sources/Autoformer@09994619.files.tsv", "reused": False,
    }  # fmt: skip
    root = tmp_path / "work/sources"
    rows = (root / "Autoformer@09994619.files.tsv").read_text(encoding="utf-8").splitlines()
    assert rows[0] == "path\tlines\tsha256" and rows[2].startswith("layers/AC.py\t2\t")
    assert tree_sha256(root / "Autoformer@09994619") == tree_sha256(corpus[1] / "Autoformer@09994619")
    assert s.fetch("Autoformer@09994619")[0]["intact"]


def test_the_stdio_server_answers_mcp(corpus: tuple[Path, Path], tmp_path: Path) -> None:
    papers, code = corpus
    opened = tmp_path / "opened.json"
    opened.write_text(json.dumps(["2403.01673v1"]), encoding="utf-8")
    cmd = [sys.executable, "-m", "pweval.harness.source_server", "--papers", str(papers), "--code", str(code),
           "--opened", str(opened), "--dest", str(tmp_path / "dest"), "--log", str(tmp_path / "sources.jsonl")]  # fmt: skip
    with Client(cmd, dict(os.environ)) as client:
        text = client.call("read_source", {"source_id": "2403.01673v1"})
    assert json.loads(text)["sha256"] and (tmp_path / "dest/2403.01673v1/paper.md").is_file()
    listed = handle(sources(corpus, tmp_path, []), {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert [t["name"] for t in listed["result"]["tools"]] == ["read_source"]
    out = io.StringIO()
    serve(sources(corpus, tmp_path, []), io.StringIO('{"jsonrpc":"2.0","method":"notifications/initialized"}\nnot json\n'), out)
    assert json.loads(out.getvalue())["error"]["code"] == -32700
