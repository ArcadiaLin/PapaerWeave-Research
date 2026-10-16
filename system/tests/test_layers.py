"""包之间的依赖只朝下：model ← store ← draft、commit ← query ← artifact ← operators、interfaces ← tools ← mcp、cli。

同一包内随意引用；``interfaces`` 用 ``operators.base`` 声明自己，是唯一的同层引用。新加包时登记在 ``LAYERS`` 中。
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src/paperweave"
LAYERS = {
    "config": 0,
    "yamlfmt": 0,
    "model": 1,
    "store": 2,
    "draft": 3,
    "commit": 3,
    "query": 4,
    "artifact": 5,
    "operators": 6,
    "interfaces": 6,
    "tools": 7,
    "mcp": 8,
    "cli": 8,
    "workspace": 8,
    "env_check": 8,
    "__main__": 9,
}
SAME_LAYER = {("interfaces", "operators")}


def _package(path: Path) -> str:
    rel = path.relative_to(ROOT)
    return rel.parts[0].removesuffix(".py") if len(rel.parts) > 1 or rel.name != "__init__.py" else ""


def _imports(path: Path) -> list[tuple[int, str]]:
    """``paperweave`` 内被引用的顶层包（相对引用按文件位置解析），与所在行。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    here = path.relative_to(ROOT).parent.parts
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                base = list(here[: len(here) - (node.level - 1)]) if node.level > 1 else list(here)
                parts = base + (node.module.split(".") if node.module else [])
                if not parts:  # from . import x 在包根
                    parts = [a.name for a in node.names][:1]
            elif node.module and node.module.startswith("paperweave"):
                parts = node.module.split(".")[1:] or [a.name for a in node.names][:1]
            else:
                continue
            out.append((node.lineno, parts[0]))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("paperweave."):
                    out.append((node.lineno, alias.name.split(".")[1]))
    return out


def test_every_package_has_a_layer() -> None:
    packages = {_package(p) for p in ROOT.rglob("*.py")} - {""}
    assert packages <= set(LAYERS), f"register in LAYERS: {sorted(packages - set(LAYERS))}"


def test_imports_point_down() -> None:
    wrong = []
    for path in sorted(ROOT.rglob("*.py")):
        pkg = _package(path)
        if not pkg:
            continue
        for line, target in _imports(path):
            if target == pkg or target not in LAYERS:
                continue
            if LAYERS[target] < LAYERS[pkg] or (pkg, target) in SAME_LAYER:
                continue
            wrong.append(f"{path.relative_to(ROOT)}:{line} {pkg} → {target}")
    assert not wrong, "\n".join(wrong)
