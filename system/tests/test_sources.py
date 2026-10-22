"""外部来源：来源 ID 的版本先后与只读来源目录（paperweave.store.sources）。"""

from __future__ import annotations

from pathlib import Path

from paperweave.model.refs import parse_ref
from paperweave.store.sources import SourceDir, newer, version


def test_versions_are_read_from_the_id() -> None:
    assert version("2205.13504v2") == ("2205.13504", 2)
    assert version("Autoformer@09994619") is None
    declared = ["2205.13504v1", "2205.13504v3", "2205.13504v2", "2106.13008v5", "Autoformer@09994619"]
    assert newer("2205.13504v1", declared) == "2205.13504v3"
    assert newer("2205.13504v3", declared) is None
    assert newer("2106.13008v5", declared) is None
    assert newer("Autoformer@09994619", declared) is None  # 代码的 commit 不排序


def test_source_dir_reads_papers_and_code_files_only_inside(tmp_path: Path) -> None:
    (tmp_path / "2205.13504v2").mkdir()
    (tmp_path / "2205.13504v2/paper.md").write_text("# T\nline\n", encoding="utf-8")
    (tmp_path / "Autoformer@09994619/layers").mkdir(parents=True)
    (tmp_path / "Autoformer@09994619/layers/AC.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("no\n", encoding="utf-8")
    sources = SourceDir(tmp_path)
    assert sources.available("2205.13504v2") and sources.available("Autoformer@09994619")
    assert not sources.available("2205.13504v1") and not sources.available("secret.txt")
    assert sources.lines("2205.13504v2") == ["# T", "line"]
    assert sources.lines("Autoformer@09994619", "./layers/AC.py") == ["x = 1"]
    assert sources.file("Autoformer@09994619", "../secret.txt") is None
    assert sources.file("Autoformer@09994619", "/etc/passwd") is None
    assert sources.file("Autoformer@09994619") is None  # 代码要给出文件


def test_source_references() -> None:
    paper = parse_ref("`2205.13504v2 :: Experiments :: L210-L245`")
    assert paper is not None and paper.text == "2205.13504v2::Experiments::210:245" and paper.lines == (210, 245)
    code = parse_ref("Autoformer@09994619::layers/AC.py::30:48")
    assert code is not None and code.external and code.file == "layers/AC.py" and code.lines == (30, 48)
    whole = parse_ref("2205.13504v2")
    assert whole is not None and whole.kind == "source" and whole.lines is None
    assert parse_ref("2205.13504::1:2") is None  # 不带版本：不是来源 ID
    old = parse_ref("paper_0001::1:2")
    assert old is not None and not old.external  # 库内 id 开头：只用作产物文档的读取输入
