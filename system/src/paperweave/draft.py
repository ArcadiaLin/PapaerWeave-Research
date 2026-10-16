"""草稿文件：写者在自己的工作目录里写好的大块内容，算子按路径读取（docs/designs/v2/draft_files.md）。

草稿是写者的，产物是服务端的：Commit 的 ``doc_file`` 是 graph-doc YAML（CheckIn 的共同产物文档另见
:mod:`paperweave.artifact.checkin`）。服务端读入、解析后交给与参数中写出的内容相同的校验；被拒时把校验报告的位置换算成
``<文件>:<行号>``，写者就地改那几行再交。通过后的产物由服务端从解析后的内容生成，之后草稿再改也不影响它。

**路径。** 只接受工作目录内的文件：相对路径相对于工作目录；绝对路径须在工作目录内，或以写者看到的工作目录
（``alias``，如沙箱中的 ``/work``）开头。解析 ``..`` 与符号链接后仍须在工作目录内，且不在材料根目录下；
文件不超过 :data:`MAX_BYTES`。工作目录由服务端决定（:meth:`Workdir.from_env`），写者无法自己声明。
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from graph_doc import SECTIONS

from .store.store import ContractError

MAX_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class Workdir:
    """写者的工作目录：``root`` 是服务端看到的路径，``alias`` 是写者看到的同一目录（不同时为 ``None``）。"""

    root: Path
    alias: str | None = None

    @classmethod
    def from_env(cls) -> Workdir:
        """``PAPERWEAVE_WORKDIR`` 与 ``PAPERWEAVE_WORKDIR_ALIAS``；没有设置时用服务进程的当前目录。"""
        root = os.environ.get("PAPERWEAVE_WORKDIR") or os.getcwd()
        return cls(Path(root), os.environ.get("PAPERWEAVE_WORKDIR_ALIAS") or None)


@dataclass(frozen=True, slots=True)
class Draft:
    """读入的草稿：``path`` 是写者给出的写法（报错与提交记录都用它），``text`` 是读入时的内容。"""

    path: str
    text: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()

    def meta(self) -> dict[str, str]:
        """记入提交 ``meta.draft``。"""
        return {"path": self.path, "sha256": self.sha256}


def read(workdir: Workdir | None, given: Any, at: str, material_root: Path) -> Draft:
    """按路径规则读入草稿。

    Raises:
        ContractError: 路径不合规则、文件不存在、过大或不是 UTF-8 文本（``format``）。
    """

    def fail(msg: str) -> ContractError:
        return ContractError([{"rule": "format", "at": at, "msg": msg}])

    if workdir is None:
        raise fail("draft files are not available here; give the content inline")
    if not isinstance(given, str) or not given.strip():
        raise fail("a path to a file in your working directory")
    text = given.strip()
    root = workdir.root.resolve()
    alias = workdir.alias.rstrip("/") if workdir.alias else None
    if alias and (text == alias or text.startswith(alias + "/")):
        file = root / text[len(alias) :].lstrip("/")
    else:
        file = root / text  # 绝对路径时 root 被忽略，下面核对它是否在工作目录内
    shown = alias or str(workdir.root)
    try:
        file = file.resolve(strict=True)
    except (FileNotFoundError, RuntimeError):
        raise fail(f"{text} does not exist; write the file in your working directory ({shown}) first") from None
    if not file.is_relative_to(root):
        raise fail(f"{text} is outside your working directory ({shown})")
    if file.is_relative_to(material_root.resolve()):
        raise fail(f"{text} is a source material, not a draft of yours")
    if not file.is_file():
        raise fail(f"{text} is not a file")
    if file.stat().st_size > MAX_BYTES:
        raise fail(f"{text} is larger than {MAX_BYTES // (1024 * 1024)} MB")
    try:
        content = file.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise fail(f"{text} is not UTF-8 text") from None
    return Draft(text, content)


# ── YAML ───────────────────────────────────────────────────────────────

_TOKEN = re.compile(r"\[(\d+)\]|([^.\[\]]+)")


def yaml_syntax(draft: Draft) -> dict[str, str] | None:
    """YAML 语法错误，位置是 ``<文件>:<行号>``；没有错误时为 ``None``。"""
    try:
        yaml.compose(draft.text, Loader=yaml.SafeLoader)
    except yaml.MarkedYAMLError as exc:
        mark = exc.problem_mark or exc.context_mark
        where = f"{draft.path}:{mark.line + 1}" if mark else draft.path
        return {"rule": "format", "at": where, "msg": f"not YAML: {exc.problem or exc}"}
    except yaml.YAMLError as exc:
        return {"rule": "format", "at": draft.path, "msg": f"not YAML: {exc}"}
    return None


def yaml_locator(draft: Draft) -> Callable[[str], str]:
    """graph-doc 中的位置（如 ``create.$exp.EVALUATES.method_0021.role``）→ ``<文件>:<行号> (<位置>)``。

    沿位置逐级找到最深的节点，取它的行号；只写节点（如 ``$exp.description``）时在 create、set、delete、confirm
    下找最深的一处。一级也找不到时只给文件。
    """
    try:
        root = yaml.compose(draft.text, Loader=yaml.SafeLoader)
    except yaml.YAMLError:
        root = None

    def walk(tokens: list[str | int]) -> tuple[int | None, int]:
        """最深的已找到节点的行号与找到的级数。"""
        node, line = root, None
        for depth, token in enumerate(tokens):
            if isinstance(node, yaml.MappingNode) and isinstance(token, str):
                found = next(((k, v) for k, v in node.value if getattr(k, "value", None) == token), None)
                if found is None:
                    return line, depth
                node, line = found[1], found[0].start_mark.line + 1
            elif isinstance(node, yaml.SequenceNode) and isinstance(token, int) and token < len(node.value):
                node = node.value[token]
                line = node.start_mark.line + 1
            else:
                return line, depth
        return line, len(tokens)

    def locate(at: str) -> str:
        tokens: list[str | int] = [int(i) if i else name for i, name in _TOKEN.findall(at)]
        line, depth = walk(tokens) if tokens else (None, 0)
        if depth == 0 and tokens and tokens[0] not in SECTIONS:
            found = [walk([section, *tokens]) for section in SECTIONS]  # 只写节点（如 $exp）时在各节下找
            under, deeper = max(found, key=lambda f: f[1])
            line = under if deeper > 1 else None
        where = f"{draft.path}:{line}" if line is not None else draft.path
        return f"{where} ({at})" if at else where

    return locate


def locate_doc(result: Mapping[str, Any], draft: Draft) -> dict[str, Any]:
    """Commit 结果中 ``errors`` 与 ``warnings`` 的位置换算成草稿的行号。"""
    locate = yaml_locator(draft)
    out = dict(result)
    for key in ("errors", "warnings"):
        if isinstance(out.get(key), list):
            out[key] = [{**e, "at": locate(str(e.get("at", "")))} if isinstance(e, Mapping) else e for e in out[key]]
    return out


__all__ = [
    "MAX_BYTES",
    "Draft",
    "Workdir",
    "locate_doc",
    "read",
    "yaml_locator",
    "yaml_syntax",
]
