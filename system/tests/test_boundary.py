"""系统与评测互不导入：系统（paperweave 及其底层 graph-doc、graph-vc）不导入评测代码（pweval）。

反方向（评测不导入系统）由 eval/tests/test_imports.py 检查。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SOURCES = sorted(
    p
    for root in ("system/src/paperweave", "packages/graph-doc/src/graph_doc", "packages/graph-vc/src/graph_vc")
    for p in (REPO / root).rglob("*.py")
)
EVALUATION = {"pweval"}


def imports(path: Path) -> set[str]:
    """模块导入的顶层包（相对导入不计，它们留在本包内）。"""
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and not node.level:
            out.add((node.module or "").split(".")[0])
    return out


def test_sources_found() -> None:
    assert len(SOURCES) > 50


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: str(p.relative_to(REPO)))
def test_no_evaluation_imports(path: Path) -> None:
    found = imports(path) & EVALUATION
    assert not found, f"{path.relative_to(REPO)} imports the evaluation code: {sorted(found)}"
