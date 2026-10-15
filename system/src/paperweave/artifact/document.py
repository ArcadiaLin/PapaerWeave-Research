"""Artifact 文档的格式（docs/designs/v2/operators.md §4.1、§5.3）。

**共同产物**（经 ``CheckIn`` 检入、有版本的文档，:mod:`paperweave.artifact.checkin`）：头部是 YAML，正文是写者的 Markdown，
按原样保存。头部的 ``type`` 给出类型；取出时多两行 ``id`` 与 ``base``（:func:`add_checkout`），检入时去掉
（:func:`strip_checkout`）。Skill 用 Agent Skills 格式，顶层字段固定，``type``、``id``、``base`` 写在 ``metadata``
下。每个版本的文档存为 ``artifacts/<标题>.v<版本>.md``（:func:`version_file_name`）。表格按 :func:`tables` 解析，
供类型契约按行键对齐。

**旧版 Agent 算子**（已下线；库中已有的文档只读，``_stale``、引用核对与 T1 的检查仍要读它们）：写入后不可修改的
文档，头部与正文，需要被其他算子读取的产物在正文末尾附数据块：

    ---
    title: …
    nodes_used: [<inputs 中的引用>]
    abs: …
    ---
    <正文>

    ```yaml
    <数据块>
    ```

旧版文档存放在材料根目录下的 ``artifacts/<标题>.md``，标题重复时依次加 `` (1)``、`` (2)``
（:func:`file_name`，共同产物的文件名也由它生成）；写入后不再改动。Material 的 id 由内容哈希给出
（``material_<sha256 前 12 位>``），与文件名无关；头部不含 Artifact 的 id，所以内容相同的文档只存一份。
共同产物的 Material id 另由产物与版本一起算出（paperweave.artifact.checkin）。
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import yaml

DIRECTORY = "artifacts"
_HEADER = re.compile(r"\A---\n(?P<header>.*?)\n---\n", re.DOTALL)
_FENCE = "```yaml\n"


@dataclass(frozen=True, slots=True)
class Document:
    text: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()

    @property
    def material_id(self) -> str:
        """与论文材料相同的 id 规则（paperweave.commit.translate）。"""
        return f"material_{self.sha256[:12]}"


_UNSAFE = re.compile(r'[\x00-\x1f\x7f<>:"/\\|?*]')  # 控制字符与 Linux、Windows 文件名中不能用的字符
NAME_BYTES = 200  # 文件名（不含序号与扩展名）的最大字节数；文件系统的上限是 255


def file_name(title: str, n: int = 0) -> str:
    """标题对应的文件名：不能用的字符换成空格，连续空白并成一个，去掉首尾的空白与点，按 UTF-8 截到
    :data:`NAME_BYTES` 字节；``n`` 大于 0 时加 `` (n)``。"""
    stem = " ".join(_UNSAFE.sub(" ", title).split()).strip(" .")  # 不以点开头：不成为隐藏文件
    stem = stem.encode("utf-8")[:NAME_BYTES].decode("utf-8", "ignore").rstrip(" .") or "artifact"
    return f"{stem} ({n}).md" if n else f"{stem}.md"


def header_of(text: str) -> dict[str, Any]:
    """文档头部；没有头部时为空。"""
    match = _HEADER.match(text)
    header = yaml.safe_load(match["header"]) if match else None
    return header if isinstance(header, dict) else {}


def data_of(text: str) -> Any:
    """正文末尾的数据块；没有时为 ``None``。"""
    start = text.rfind(_FENCE)
    end = text.find("```", start + len(_FENCE)) if start >= 0 else -1
    return yaml.safe_load(text[start + len(_FENCE) : end]) if end >= 0 else None


def record_keys(op: str, data: Any) -> list[str]:
    """Artifact 数据块中可用 ``<artifact>#<key>`` 引用的记录键。"""
    if not isinstance(data, Mapping):
        return []
    if op == "Extract":
        return [r["key"] for r in data.get("rows") or [] if isinstance(r, Mapping) and "key" in r]
    if op == "Check":
        return ["~".join(p) for p in data.get("pairs") or [] if isinstance(p, list)]
    if op == "Filter":
        return list(data.get("items") or {})
    if op == "MatrixConstruct":
        return [f"{c['row']}~{c['col']}" for c in data.get("cells") or [] if isinstance(c, Mapping)]
    return []


# ── 共同产物 ──────────────────────────────────────────────────────────

CHECKOUT = ("id", "base")  # 取出时加在头部、检入时去掉的两行
_KEY = re.compile(r"(?P<indent> *)(?P<key>[A-Za-z_][\w-]*)\s*:(?P<value>.*)$")


@dataclass(frozen=True, slots=True)
class Parsed:
    """解析后的共同产物文档。``text`` 是文档全文，``lines`` 是它的行（行号从 1 起，``lines[0]`` 是第 1 行）；
    ``header`` 是头部，``body_start`` 是正文第一行的行号。"""

    text: str
    header: dict[str, Any]
    body_start: int

    @property
    def lines(self) -> list[str]:
        return self.text.split("\n")

    @property
    def body(self) -> str:
        return "\n".join(self.lines[self.body_start - 1 :])


class HeaderError(ValueError):
    """文档没有头部，或头部不是 YAML 映射。``line`` 是出错的行号。"""

    def __init__(self, msg: str, line: int = 1) -> None:
        super().__init__(msg)
        self.line = line


def parse(text: str) -> Parsed:
    """解析文档：头部以第一行的 ``---`` 开始、下一行 ``---`` 结束。

    Raises:
        HeaderError: 没有头部，或头部不是 YAML 映射。
    """
    match = _HEADER.match(text)
    if match is None:
        raise HeaderError("the document starts with a YAML header between two --- lines")
    try:
        header = yaml.safe_load(match["header"])
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        raise HeaderError(f"the header is not valid YAML: {exc}", 2 + (mark.line if mark else 0)) from None
    if not isinstance(header, dict):
        raise HeaderError("the header is a YAML mapping such as title: ...")
    return Parsed(text, header, match["header"].count("\n") + 4)


def nested(header: Mapping[str, Any]) -> bool:
    """``type``、``id``、``base`` 是否写在 ``metadata`` 下（Skill 的 Agent Skills 格式）。"""
    meta = header.get("metadata")
    return "type" not in header and isinstance(meta, Mapping) and "type" in meta


def header_field(header: Mapping[str, Any], name: str) -> Any:
    """头部的 ``type``、``id`` 或 ``base``：顶层没有时取 ``metadata`` 下的。"""
    if name in header:
        return header[name]
    meta = header.get("metadata")
    return meta.get(name) if isinstance(meta, Mapping) else None


def strip_checkout(text: str) -> str:
    """去掉头部的 ``id`` 与 ``base`` 两行（顶层的，或 ``metadata`` 下第一层的），其余各行原样保留。"""
    match = _HEADER.match(text)
    if match is None:
        return text
    kept: list[str] = []
    top: str | None = None
    child: int | None = None
    for line in match["header"].split("\n"):
        m = _KEY.match(line)
        indent = len(line) - len(line.lstrip(" "))
        if m is not None and indent == 0:
            top, child = m["key"], None
        elif m is not None and top == "metadata" and child is None:
            child = indent
        scalar = m is not None and m["value"].strip() != ""
        if scalar and m["key"] in CHECKOUT and (indent == 0 or (top == "metadata" and indent == child)):
            continue
        kept.append(line)
    return "---\n" + "\n".join(kept) + "\n---\n" + text[match.end() :]


def add_checkout(text: str, art_id: str, base: str) -> str:
    """在头部加上 ``id`` 与 ``base``：通常加在头部最前面；``type`` 写在 ``metadata`` 下时加在 ``metadata`` 下。"""
    match = _HEADER.match(text)
    assert match is not None, "a stored document always has a header"
    lines = match["header"].split("\n")
    if nested(yaml.safe_load(match["header"])):
        at = next(i for i, line in enumerate(lines) if line.startswith("metadata:"))
        following = lines[at + 1] if at + 1 < len(lines) else ""
        pad = " " * ((len(following) - len(following.lstrip(" "))) or 2)
        lines[at + 1 : at + 1] = [f"{pad}id: {art_id}", f"{pad}base: {base}"]
    else:
        lines[0:0] = [f"id: {art_id}", f"base: {base}"]
    return "---\n" + "\n".join(lines) + "\n---\n" + text[match.end() :]


def line_map(longer: str, shorter: str) -> list[int]:
    """``shorter`` 的每一行在 ``longer`` 中的行号（从 1 起）；``shorter`` 是 ``longer`` 去掉若干行（取出时加的
    ``id``、``base`` 两行）后的文字。"""
    out: list[int] = []
    original = longer.split("\n")
    i = 0
    for line in shorter.split("\n"):
        while i < len(original) and original[i] != line:
            i += 1
        out.append(i + 1)
        i += 1
    return out


def version_file_name(title: str, version: int, n: int = 0) -> str:
    """某个版本的文档在材料根目录 ``artifacts/`` 下的文件名：``<标题>.v<版本>.md``，被内容不同的文件占用时为
    ``<标题> (n).v<版本>.md``。"""
    stem = file_name(title, n)[: -len(".md")]
    return f"{stem}.v{version}.md"


@dataclass(frozen=True, slots=True)
class Row:
    """表格的一行：``line`` 是行号，``cells`` 是列名 → 单元格文字（去掉首尾空白）。"""

    line: int
    cells: dict[str, str]


@dataclass(frozen=True, slots=True)
class Table:
    """Markdown 表格：``heading`` 是它之前最近的标题（不带 ``#``），``columns`` 是表头的列名，``lines`` 是表头到
    最后一行的行号范围（含两端）。"""

    heading: str
    columns: list[str]
    rows: list[Row]
    lines: tuple[int, int]


_SEPARATOR_CELL = re.compile(r":?-{3,}:?")


def cells_of(line: str) -> list[str] | None:
    """表格一行的单元格；不是表格行时为 ``None``。``\\|`` 是单元格中的竖线。"""
    stripped = line.strip()
    if not stripped.startswith("|"):
        return None
    parts = re.split(r"(?<!\\)\|", stripped)
    parts = parts[1:-1] if stripped.endswith("|") and len(parts) > 2 else parts[1:]
    return [p.strip().replace("\\|", "|") for p in parts]


def tables(doc: Parsed) -> list[Table]:
    """正文中的 Markdown 表格（表头、分隔行与数据行），按出现顺序。"""
    out: list[Table] = []
    heading = ""
    lines = doc.lines
    i = doc.body_start - 1
    while i < len(lines):
        line = lines[i]
        if line.lstrip().startswith("#"):
            heading = line.lstrip().lstrip("#").strip()
        head = cells_of(line)
        sep = cells_of(lines[i + 1]) if i + 1 < len(lines) else None
        if head and sep and len(sep) == len(head) and all(_SEPARATOR_CELL.fullmatch(c) for c in sep):
            rows: list[Row] = []
            j = i + 2
            while j < len(lines) and (cells := cells_of(lines[j])) is not None:
                padded = [*cells, *[""] * (len(head) - len(cells))]
                rows.append(Row(j + 1, dict(zip(head, padded, strict=False))))
                j += 1
            out.append(Table(heading, head, rows, (i + 1, j)))
            i = j
            continue
        i += 1
    return out


__all__ = [
    "CHECKOUT",
    "DIRECTORY",
    "NAME_BYTES",
    "Document",
    "HeaderError",
    "Parsed",
    "Row",
    "Table",
    "add_checkout",
    "cells_of",
    "data_of",
    "file_name",
    "header_field",
    "header_of",
    "line_map",
    "nested",
    "parse",
    "record_keys",
    "strip_checkout",
    "tables",
    "version_file_name",
]
