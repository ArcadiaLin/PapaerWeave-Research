"""评测代码与被测系统分离（evaluation_draft §10.1）：t1 不导入 e09、graph-doc、graph-vc；测量层只用标准库与 pyyaml。

尚未按 §10.1 改写的模块列在 ``PENDING`` 中，改完一个移出一个；``PENDING`` 为空即达标。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

T1 = Path(__file__).resolve().parents[1]
SOURCES = sorted([*(T1 / "src/t1").glob("*.py"), *(T1 / "seeds/scripts").glob("*.py")])
SYSTEM = {"e09", "graph_doc", "graph_vc"}
MEASURE = {"health", "grade", "source_tables"}  # 测量层：只读快照，不连库
MEASURE_OK = {"yaml", "t1"}
PENDING = {"a0_seed", "replay", "run", "health"}


def imports(path: Path) -> set[str]:
    """模块导入的顶层包；相对导入记为 ``t1``。"""
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            out.add("t1" if node.level else (node.module or "").split(".")[0])
    return out


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.stem)
def test_no_system_imports(path: Path) -> None:
    found = imports(path) & SYSTEM
    if path.stem in PENDING:
        pytest.skip(f"not yet separated: imports {sorted(found)}" if found else "listed as pending")
    assert not found, f"{path.name} imports the system under test: {sorted(found)}"


@pytest.mark.parametrize("path", [p for p in SOURCES if p.stem in MEASURE], ids=lambda p: p.stem)
def test_measure_uses_stdlib_and_yaml(path: Path) -> None:
    if path.stem in PENDING:
        pytest.skip("listed as pending")
    extra = imports(path) - set(sys.stdlib_module_names) - MEASURE_OK - {"__future__"}
    assert not extra, f"{path.name} (measure layer) imports {sorted(extra)}"


def test_pending_is_honest() -> None:
    """白名单中的模块确实还导入被测系统；改完却没移出的会在这里报出。"""
    stale = [p.stem for p in SOURCES if p.stem in PENDING and not imports(p) & SYSTEM and p.stem not in MEASURE]
    assert not stale, f"remove from PENDING: {stale}"
