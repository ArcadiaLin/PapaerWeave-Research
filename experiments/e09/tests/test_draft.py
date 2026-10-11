"""草稿文件的读取与定位：路径规则、CSV 的表头与行号、graph-doc 位置到行号的换算（不连库）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from e09.draft import MAX_BYTES, Draft, Workdir, locate_rows, read, read_csv, yaml_locator, yaml_syntax
from e09.store import ContractError


@pytest.fixture
def dirs(tmp_path: Path) -> tuple[Workdir, Path]:
    work, materials = tmp_path / "work", tmp_path / "data"
    (work / "tables").mkdir(parents=True)
    (materials / "papers").mkdir(parents=True)
    (work / "tables/a.csv").write_text("x\n1\n", encoding="utf-8")
    return Workdir(work, "/work"), materials


def problem(workdir: Workdir, materials: Path, given: str) -> str:
    with pytest.raises(ContractError) as exc:
        read(workdir, given, "payload_file", materials)
    [error] = exc.value.errors
    assert error["rule"] == "format" and error["at"] == "payload_file"
    return error["msg"]


def test_relative_absolute_and_alias_paths_read_the_same_file(dirs: tuple[Workdir, Path]) -> None:
    workdir, materials = dirs
    for given in ("tables/a.csv", "/work/tables/a.csv", str(workdir.root / "tables/a.csv"), "./tables/../tables/a.csv"):
        draft = read(workdir, given, "payload_file", materials)
        assert draft.text == "x\n1\n" and draft.path == given
    assert read(workdir, "tables/a.csv", "f", materials).meta()["sha256"] == Draft("p", "x\n1\n").sha256


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
    (work / "big.csv").write_bytes(b"x" * (MAX_BYTES + 1))
    assert "larger than" in problem(workdir, tmp_path / "data", "big.csv")
    with pytest.raises(ContractError, match="not available here"):
        read(None, "big.csv", "payload_file", tmp_path)


def test_csv_records_carry_their_starting_line() -> None:
    text = 'a,b,source\n1,"two\nlines",s1\n\n3,"x, y",s2\n'
    table = read_csv(Draft("t.csv", text), ["a", "b", "source"], {"a", "source"})
    assert table.header == ["a", "b", "source"]
    assert table.records == [(2, {"a": "1", "b": "two\nlines", "source": "s1"}), (5, {"a": "3", "b": "x, y", "source": "s2"})]


def test_csv_header_and_cell_count_problems_are_listed_together() -> None:
    text = "a,zzz\n1,2\n1,2,3\n"
    with pytest.raises(ContractError) as exc:
        read_csv(Draft("t.csv", text), ["a", "b", "source"], {"a", "source"})
    assert [(e["at"], e["msg"].split(":")[0]) for e in exc.value.errors] == [
        ("t.csv:1", "columns not declared"),
        ("t.csv:1", "missing columns ['source']; the header is a,b,source"),
        ("t.csv:3", "3 cells, the header has 2; quote values that contain commas"),
    ]


def test_row_positions_become_file_lines() -> None:
    draft = Draft("tables/t.csv", "")
    errors = [
        {"rule": "schema", "at": "payload.rows[1].mse", "msg": "not a number: 'x'"},
        {"rule": "schema", "at": "payload.rows[2]", "msg": "key 'a' repeats payload.rows[0]"},
        {"rule": "schema", "at": "payload.rows", "msg": "a list"},
        {"rule": "format", "at": "inputs", "msg": "unchanged"},
    ]
    assert [(e["at"], e["msg"]) for e in locate_rows(errors, draft, "rows", [2, 4, 7])] == [
        ("tables/t.csv:4 (mse)", "not a number: 'x'"),
        ("tables/t.csv:7", "key 'a' repeats line 2"),
        ("tables/t.csv", "a list"),
        ("inputs", "unchanged"),
    ]


DOC = """graph-doc: v0.1
nodes:
  $exp:
    kind: Experiment
    text: A run.
    FROM:
      - to: paper_0001
        locators: ["5.2::10:12"]
  method_0003:
    note: x
"""


def test_doc_positions_become_file_lines() -> None:
    locate = yaml_locator(Draft("d.yml", DOC))
    assert locate("nodes.$exp.FROM[0].locators") == "d.yml:8 (nodes.$exp.FROM[0].locators)"
    assert locate("nodes.$exp.FROM[0]") == "d.yml:7 (nodes.$exp.FROM[0])"
    assert locate("$exp") == "d.yml:3 ($exp)"  # 只写节点引用时在 nodes 下找
    assert locate("method_0003.note") == "d.yml:10 (method_0003.note)"
    assert locate("nodes.$exp.EVALUATES") == "d.yml:3 (nodes.$exp.EVALUATES)"  # 找到哪一级就给哪一级
    assert locate("exp_0001-[EVALUATES]->x") == "d.yml (exp_0001-[EVALUATES]->x)"
    assert yaml_syntax(Draft("d.yml", DOC)) is None
    assert yaml_syntax(Draft("d.yml", "nodes:\n  $a: {kind: Task\n  $b: 1\n"))["at"].startswith("d.yml:")
