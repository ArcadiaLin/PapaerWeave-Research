"""草稿文件的读取与定位：路径规则、graph-doc 位置到行号的换算（不连库）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from paperweave.draft import MAX_BYTES, Draft, Workdir, read, yaml_locator, yaml_syntax
from paperweave.store import ContractError


@pytest.fixture
def dirs(tmp_path: Path) -> tuple[Workdir, Path]:
    work, materials = tmp_path / "work", tmp_path / "data"
    (work / "tables").mkdir(parents=True)
    (materials / "papers").mkdir(parents=True)
    (work / "tables/a.yml").write_text("x\n1\n", encoding="utf-8")
    return Workdir(work, "/work"), materials


def problem(workdir: Workdir, materials: Path, given: str) -> str:
    with pytest.raises(ContractError) as exc:
        read(workdir, given, "doc_file", materials)
    [error] = exc.value.errors
    assert error["rule"] == "format" and error["at"] == "doc_file"
    return error["msg"]


def test_relative_absolute_and_alias_paths_read_the_same_file(dirs: tuple[Workdir, Path]) -> None:
    workdir, materials = dirs
    for given in ("tables/a.yml", "/work/tables/a.yml", str(workdir.root / "tables/a.yml"), "./tables/../tables/a.yml"):
        draft = read(workdir, given, "doc_file", materials)
        assert draft.text == "x\n1\n" and draft.path == given
    assert read(workdir, "tables/a.yml", "f", materials).meta()["sha256"] == Draft("p", "x\n1\n").sha256


def test_paths_outside_the_working_directory_are_refused(dirs: tuple[Workdir, Path], tmp_path: Path) -> None:
    workdir, materials = dirs
    (tmp_path / "secret.csv").write_text("x\n", encoding="utf-8")
    assert "outside your working directory" in problem(workdir, materials, "../secret.csv")
    assert "outside your working directory" in problem(workdir, materials, str(tmp_path / "secret.csv"))
    (workdir.root / "link.csv").symlink_to(tmp_path / "secret.csv")
    assert "outside your working directory" in problem(workdir, materials, "link.csv")
    assert "does not exist" in problem(workdir, materials, "tables/b.csv")
    assert "not a file" in problem(workdir, materials, "tables")


def test_source_materials_and_large_files_are_refused(tmp_path: Path) -> None:
    work = tmp_path / "work"
    (work / "papers").mkdir(parents=True)
    (work / "papers/p.md").write_text("line\n", encoding="utf-8")
    workdir = Workdir(work)
    assert "source material" in problem(workdir, work / "papers", "papers/p.md")  # 材料目录在工作目录内时
    (work / "big.yml").write_bytes(b"x" * (MAX_BYTES + 1))
    assert "larger than" in problem(workdir, tmp_path / "data", "big.yml")
    with pytest.raises(ContractError, match="not available here"):
        read(None, "big.yml", "doc_file", tmp_path)


DOC = """graph-doc: v0.2
create:
  $exp:
    kind: Experiment
    description: A run.
    EVALUATES:
      method_0003:
        role: target
set:
  method_0003:
    description: x
"""


def test_doc_positions_become_file_lines() -> None:
    locate = yaml_locator(Draft("d.yml", DOC))
    assert locate("create.$exp.EVALUATES.method_0003.role") == "d.yml:8 (create.$exp.EVALUATES.method_0003.role)"
    assert locate("create.$exp.EVALUATES") == "d.yml:6 (create.$exp.EVALUATES)"
    assert locate("$exp") == "d.yml:3 ($exp)"  # 只写节点时在各节下找
    assert locate("method_0003.description") == "d.yml:11 (method_0003.description)"  # 取找得最深的一处
    assert locate("create.$exp.USES") == "d.yml:3 (create.$exp.USES)"  # 找到哪一级就给哪一级
    assert locate("exp_0001-[EVALUATES]->x") == "d.yml (exp_0001-[EVALUATES]->x)"
    assert yaml_syntax(Draft("d.yml", DOC)) is None
    assert yaml_syntax(Draft("d.yml", "nodes:\n  $a: {kind: Task\n  $b: 1\n"))["at"].startswith("d.yml:")
    twice = "create:\n  $e:\n    USES:\n      dataset_0002: {role: training_data}\n      dataset_0002: {role: evaluation_data}\n"
    assert "role: [training_data, evaluation_data]" in yaml_syntax(Draft("d.yml", twice))["msg"]  # 一条边两种用途写成列表
