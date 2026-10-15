"""评测代码的分层与被测系统分离（evaluation_draft §10.1）。

- 评测的任何代码都不导入被测系统（paperweave、graph-doc、graph-vc）；
- ``protocol``（共享约定）只用标准库、pyyaml 与 protocol 自己；
- ``measure``（测量）只用标准库、pyyaml、protocol 与 measure 自己：只读快照，不连库，不依赖运行框架；
- ``harness/bridge.py`` 在沙箱里用系统的 python3 直接运行，只用标准库。

反方向（系统不导入评测）由 system/tests/test_boundary.py 检查。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

EVAL = Path(__file__).resolve().parents[1]
PACKAGE = EVAL / "src/pweval"
SOURCES = sorted([*PACKAGE.rglob("*.py"), *(EVAL / "seeds/scripts").glob("*.py")])
SYSTEM = {"paperweave", "graph_doc", "graph_vc"}
STDLIB = set(sys.stdlib_module_names) | {"__future__"}
LAYERS = {  # 层 → 除标准库外可以导入的模块（前缀）
    "pweval.protocol": ("yaml", "pweval.paths", "pweval.protocol"),
    "pweval.measure": ("yaml", "pweval.paths", "pweval.protocol", "pweval.measure"),
    "pweval.harness.bridge": (),
}


def module_of(path: Path) -> str | None:
    """包内文件的模块名（``__init__.py`` 即包名）；包外的脚本为 ``None``。"""
    path = path.resolve()
    if not path.is_relative_to(PACKAGE):
        return None
    parts = ["pweval", *path.relative_to(PACKAGE).with_suffix("").parts]
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def imports(path: Path) -> set[str]:
    """模块导入的完整模块名；相对导入按所在包解析，``from 包 import 名字`` 记为 ``包.名字``。"""
    module = module_of(path)
    package = (module or "").split(".") if path.name == "__init__.py" else (module or "").split(".")[:-1]
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            base = ".".join(package[: len(package) - node.level + 1]) if node.level else ""
            target = ".".join(filter(None, [base, node.module]))
            out |= {f"{target}.{a.name}" for a in node.names} if node.level and not node.module else {target}
    return out


def _allowed(name: str, prefixes: tuple[str, ...]) -> bool:
    return name.split(".")[0] in STDLIB or any(name == p or name.startswith(p + ".") for p in prefixes)


def _layer(path: Path) -> str | None:
    module = module_of(path) or ""
    return next((layer for layer in LAYERS if module == layer or module.startswith(layer + ".")), None)


def _id(path: Path) -> str:
    return str(path.relative_to(EVAL))


def test_layout() -> None:
    assert {_layer(p) for p in SOURCES} >= set(LAYERS), "every layer has modules"
    assert all(module_of(p) is not None or p.parent.name == "scripts" for p in SOURCES)


@pytest.mark.parametrize("path", SOURCES, ids=_id)
def test_no_system_imports(path: Path) -> None:
    found = {name for name in imports(path) if name.split(".")[0] in SYSTEM}
    assert not found, f"{_id(path)} imports the system under test: {sorted(found)}"


@pytest.mark.parametrize("path", [p for p in SOURCES if _layer(p)], ids=_id)
def test_layer_imports(path: Path) -> None:
    layer = _layer(path)
    assert layer is not None
    extra = sorted(name for name in imports(path) if not _allowed(name, LAYERS[layer]))
    assert not extra, f"{_id(path)} ({layer}) imports {extra}"
