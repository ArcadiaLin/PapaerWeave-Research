"""读者的放行名单：检查点上，库中记录过的来源引用所在的块（docs/experiments/f3/2026-10-22-f3-design.md §6.3）。

    python -m pweval.protocol.allowlist <运行目录> --arm A3 --checkpoint 10 [--bank DIR] [--out DIR] [--force]

只读检查点快照（``snapshots/<组>/k<篇数>/``）、检查点备份的 ``meta.yml``（开放的来源与哈希）、组的来源目录与题库的
``facts/tables.csv``，不连库、不调用模型。同样的输入得到逐字节相同的输出。A3、A2（图库组）与 A0 已实现；A4 另接
入口，后面的解析、筛选与扩块共用（:class:`Gather`）。

**A0**（:func:`collect_a0`，10-24 用户定）：共享仓库 ``A0/shared.git`` 在检查点标签及之前的每个提交写下的每个文件
版本，正文统一按 :func:`scan` 扫描（``text`` 通道，不按 YAML 解析，没有 ``structured`` 通道），完整的提交说明（``%B``）
为 ``commit`` 通道。开放的来源以写者运行时的计划与材料表为准（运行记录中的题库提交，从 Git 取那个版本），与 A0 的
会话记录交叉核对；标签、``checkpoints.yml`` 与快照一致，快照的文件树与提交列表（逐字段）与 Git 相同。另报告开放来源的原文逐行进入仓库的程度（``source_text``）。

**收集范围：读者可见的已发布内容**（10-23 用户定，补充设计 §6.3）。检查点之前每次提交的变更集（``commits.jsonl``）：

- 节点与边的可见属性，按变更集的真实格式取：创建取对象级 ``after``，修改取 ``props.<字段>`` 的 ``before`` 与
  ``after``，删除取 ``before``。被修改或删除的旧记录也收（读者能经 ``as_of``、``show`` 看到）。可见属性与系统读视图
  （``get``）一致：系统节点 Material 不收，NameKey 只收 ``raw``（读视图中的 ``alias``）；节点不收 ``NODE_HIDDEN``，
  边不收 ``EDGE_HIDDEN``，连着 Material、NameKey 的边不收。这两组字段名抄自 ``system/src/paperweave/model/schema.py``
  的 ``SYSTEM_FIELDS``、``SYSTEM_REL_PROPS`` 与 ``DERIVED_FIELDS``（eval 不导入 system）。
- 已发布产物的每个版本的正文：以提交中的文件记录（``path``、``sha256``）为文档清单，逐份读 ``documents/<path>`` 并核对
  哈希；缺失或不符即停。

- 每次提交的 ``message`` 与 ``input``（读者经 ``log``、``show`` 看到；10-23 用户定纳入）。

分三个通道，分别标注、分别统计：

- ``structured``：节点与边的 ``anchor``、``USED`` 边的 ``locators``，逐项按 :func:`parse` 解析；
- ``text``：其余可见属性（字符串、列表与 ``extra`` 中的各个字符串）与产物文档正文，按 :func:`scan` 找出其中的来源引用；
- ``commit``：提交的 ``message`` 与 ``input``，同样按 :func:`scan`；出处记提交 ID 与字段名。

三个通道的来源校验与扩块相同。

**接受的写法**（与系统 ``model/refs.py`` 的 ``normalize_ref``、``parse_ref`` 相同）：``<来源 ID>::[<章节>::]<行>``，
代码 ``<仓库>@<commit>::<文件>::<行>``；``<行>`` 为 ``a:b``，也接受系统兜底的 ``a-b``、``a–b``、``a—b``、``a~b``、
``a..b``、``La-Lb``、``lines a-b`` 与单个行号 ``a``，都规范为 ``a:b``。来源 ID 为带版本的 arXiv 编号或
``<仓库>@<8 位 commit>``。正文中一行内可以有几条引用（``2404.05192v1::143:164 (Section 4), 2404.05192v1::92:93``）；
章节段不跨越另一个来源 ID，也不含冒号。正文中只写来源 ID、后面没有 ``::`` 的记为提及（``mentions``），不是锚点。

**丢弃**（逐条记入 ``dropped``，不静默）：``no-locator``（只到来源、文件或章节，设计 §4.1）、``format``（认不出的写法、
不安全的路径）、``unopened``（不在本检查点的开放清单中）、``file-missing``（代码仓库中没有这个文件）、``not-text``
（不是 UTF-8 文本）、``bad-range``（行号为 0、起大于止或超出文件）。开放来源的哈希不符、历史不完整属于输入损坏，直接报错。

**扩块**：与 D 组的材料同一规则（:func:`pweval.protocol.evidence.paper_block`、``code_block``）：论文中落在表内的行
扩展为整表（``facts/tables.csv``），再上下取到空行；代码前后各补 8 行。

**输出** ``<out>/<组>/k<篇数>.json``，旁边 ``k<篇数>.json.sha256`` 记它的 SHA-256：

- ``passages``：每个来源（代码为 ``<仓库>@<commit>::<文件>``）去重后的扩块结果，保留原始块边界，读取时按块交付；
- ``readable``：同一来源的块合并（重叠或相邻）后的区间，只用于授权判断；
- ``origins``：每条接受的引用、它出自哪里与扩成的块；``dropped``：每条丢弃的引用与原因；
- ``inputs``：所用输入文件与来源的哈希；``checks``：历史与文档的完整性核对；``stats``：分通道的统计。

**历史完整性**（:func:`commits_of`、:func:`replay_check`）：编号连续、父链不断、最后一个提交就是检查点；按变更集重放，
修改的每个字段的 ``before`` 与当时状态相同、删除的 ``before`` 与被删对象当时的属性相同，重放结果与检查点的当前图
逐个相同。任何一处不符即停：旧值对不上说明变更集记录的历史不可信，从中收集的旧锚点也就不可信。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from .evidence import BANK, code_block, paper_block

RULE = "f3-allowlist-2"  # 2：纳入提交的 message 与 input（10-23）
GRAPH_ARMS = ("A3", "A2")

PAPER_ID = r"\d{4}\.\d{4,5}v\d+"
CODE_ID = r"[A-Za-z0-9][A-Za-z0-9._-]*@[0-9a-f]{8}"
PAPER_SOURCE = re.compile(PAPER_ID)
CODE_SOURCE = re.compile(CODE_ID)
SOURCE_ID = re.compile(f"{PAPER_ID}|{CODE_ID}")
ANCHOR = re.compile(r"(?P<start>\d+):(?P<end>\d+)")
_LINES = re.compile(r"(?:lines?\s*|L)?(?P<start>\d+)(?:\s*(?:[-–—:~]|\.\.)\s*L?(?P<end>\d+))?", re.I)
_PATH = re.compile(r"[^\s:]+")

# 正文中的来源引用：来源 ID 之后紧跟 ::，再是行（直接）或 章节／文件 :: 行。先试直接写行，这样
# “::1016 (Appendix D.2), 2404.05192v1::103” 中的 1016 不会被当成章节。
_LINES_TEXT = r"(?:lines?\s*|L)?\d+(?:\s*(?:[-–—:~]|\.\.)\s*L?\d+)?"
_HEAD = re.compile(rf"(?<![\w.@-])(?P<head>{CODE_ID}|{PAPER_ID})(?![\w@])")
_TAIL = re.compile(
    rf"\s*::\s*(?:(?P<direct>{_LINES_TEXT})(?![\w:.])"
    rf"|(?P<mid>(?:(?!{PAPER_ID}|{CODE_ID})[^:\n]){{1,120}}?)\s*::\s*(?P<lines>{_LINES_TEXT})(?![\w:.])"
    rf"|(?P<rest>[^\s,;)\]]+))"
)

# 读视图不给出的字段（system/src/paperweave/model/schema.py：SYSTEM_FIELDS、SYSTEM_REL_PROPS、DERIVED_FIELDS）
NODE_HIDDEN = frozenset({"formed_by", "formed_at", "exp_key", "embedding", "embedding_key", "search_text"})
EDGE_HIDDEN = frozenset({"material_ref", "formed_by", "formed_at", "embedding", "embedding_key", "search_text"})
SYSTEM_LABELS = frozenset({"Material", "NameKey"})
STRUCTURED_NODE = ("anchor",)
STRUCTURED_EDGE = ("anchor", "locators")
COMMIT_FIELDS = ("message", "input")
CHANNELS = ("structured", "text", "commit")


class InputError(RuntimeError):
    """输入损坏或不完整：开放来源的哈希不符、提交历史断链、文档缺失。不生成名单。"""


@dataclass(frozen=True)
class Ref:
    source: str  # 来源 ID
    file: str | None  # 代码的仓库内路径
    start: int
    end: int

    @property
    def key(self) -> str:
        """名单中的来源键：论文为来源 ID，代码为 ``<仓库>@<commit>::<文件>``。"""
        return f"{self.source}::{self.file}" if self.file else self.source


# ---------------------------------------------------------------- 解析


def normalize(text: str) -> str:
    """同系统 ``normalize_ref``：去掉两端的空白、反引号、引号与一对方括号，``::`` 两侧不留空白，行写成 ``a:b``。"""
    text = text.strip().strip("`'\"").strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1].strip()
    parts = [p.strip() for p in text.split("::")]
    if len(parts) < 2:
        return "::".join(parts)
    lines = _LINES.fullmatch(parts[-1])
    if lines is not None:
        parts[-1] = f"{lines['start']}:{lines['end'] or lines['start']}"
    return "::".join(parts)


def parse(item: Any) -> Ref | str:
    """一条引用 → :class:`Ref`，或丢弃的原因（``no-locator``、``format``）。"""
    if not isinstance(item, str) or not item.strip():
        return "format"
    text = normalize(item)
    head, sep, rest = text.partition("::")
    if not SOURCE_ID.fullmatch(head):
        return "format"
    if not sep:
        return "no-locator"
    parts = rest.split("::")
    lines = ANCHOR.fullmatch(parts[-1])
    if CODE_SOURCE.fullmatch(head):
        path = parts[0]
        if not _PATH.fullmatch(path) or not _safe(path):
            return "format"
        if len(parts) == 1:
            return "no-locator"  # 只到文件
        if len(parts) == 2 and lines:
            return Ref(head, path, int(lines["start"]), int(lines["end"]))
        return "format"
    if lines:
        return Ref(head, None, int(lines["start"]), int(lines["end"]))
    return "no-locator"  # 只到章节


def _safe(path: str) -> bool:
    p = PurePosixPath(path.removeprefix("./"))
    return not p.is_absolute() and ".." not in p.parts and str(p) not in ("", ".")


def scan(text: str) -> Iterator[tuple[str, Ref | str]]:
    """正文中的来源引用：（原文写法，解析结果）。只写来源 ID、后面没有 ``::`` 的给出 ``mention``。"""
    for m in _HEAD.finditer(text):
        head = m["head"]
        tail = _TAIL.match(text, m.end())
        if tail is None:
            yield head, "mention"
            continue
        if tail["direct"]:
            raw = f"{head}::{tail['direct']}"
        elif tail["lines"]:
            raw = f"{head}::{tail['mid'].strip()}::{tail['lines']}"
        else:
            raw = f"{head}::{tail['rest']}"
        yield text[m.start():tail.end()], parse(raw)


# ---------------------------------------------------------------- 输入


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_sha256(root: Path) -> str:
    """目录内容的哈希，与来源服务、材料表相同的算法（``pweval.harness.source_server.tree_sha256``；protocol 不导入
    harness，两份由测试核对一致）：按相对路径排序，逐个文件的 路径、NUL、内容 SHA-256。"""
    digest = hashlib.sha256()
    for f in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(f"{f.relative_to(root).as_posix()}\0".encode() + hashlib.sha256(f.read_bytes()).digest())
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def commits_of(snapshot: Path, head: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """检查点之前的全部提交，按提交顺序；核对编号连续、父链从头到根不断、最后一个就是 ``head``、条数与快照记录相同。"""
    rows = read_jsonl(snapshot / "commits.jsonl")
    meta = yaml.safe_load((snapshot / "meta.yml").read_text(encoding="utf-8"))
    rows.sort(key=lambda r: int(r["seq"]))
    seqs = [int(r["seq"]) for r in rows]
    if seqs != list(range(1, len(rows) + 1)):
        raise InputError(f"commit seq is not contiguous from 1: {seqs[:5]}…")
    ids = [r["id"] for r in rows]
    if len(set(ids)) != len(ids):
        raise InputError("duplicate commit ids")
    if not rows or ids[-1] != head:
        raise InputError(f"last commit {ids[-1] if rows else None} is not the checkpoint head {head}")
    for prev, row in zip([None, *ids], rows, strict=False):
        parent = row.get("parent") or None
        if parent != prev:
            raise InputError(f"{row['id']}: parent {parent!r}, expected {prev!r}")
    if meta["counts"]["commits"] != len(rows):
        raise InputError(f"snapshot says {meta['counts']['commits']} commits, commits.jsonl has {len(rows)}")
    for row in rows:
        row["changeset"] = json.loads(row["changeset"]) if isinstance(row["changeset"], str) else row["changeset"]
    return rows, {"commits": len(rows), "first": ids[0], "head": ids[-1], "parent_chain": "ok"}


class Sources:
    """本检查点开放的来源：只读组的来源目录，先按开放清单逐个核对哈希，不符或缺失即停；不回退到语料或本地仓库。"""

    def __init__(self, root: Path, opened: dict[str, str]):
        self.root, self.opened = root, opened
        self._lines: dict[str, list[str] | str] = {}
        for source, digest in sorted(opened.items()):
            path = root / source
            if CODE_SOURCE.fullmatch(source):
                actual = tree_sha256(path) if path.is_dir() else None
            else:
                actual = sha256_file(path / "paper.md") if (path / "paper.md").is_file() else None
            if actual != digest:
                raise InputError(f"source {source}: sha256 {actual}, opened list says {digest}")

    def lines(self, ref: Ref) -> list[str] | str:
        """所引文件的各行（与系统读锚点相同：UTF-8 解码后 ``splitlines``），或丢弃原因。"""
        if ref.source not in self.opened:
            return "unopened"
        if ref.key not in self._lines:
            path = self.root / ref.source / (ref.file.removeprefix("./") if ref.file else "paper.md")
            if not path.is_file():
                self._lines[ref.key] = "file-missing"
            else:
                try:
                    self._lines[ref.key] = path.read_bytes().decode("utf-8").splitlines()
                except UnicodeDecodeError:
                    self._lines[ref.key] = "not-text"
        return self._lines[ref.key]


def load_tables(bank: Path) -> dict[str, list[tuple[int, int]]]:
    """论文 → 各表的起止行，按 ``facts/tables.csv`` 的顺序（与 :meth:`Evidence.expand` 相同）。"""
    tables: dict[str, list[tuple[int, int]]] = defaultdict(list)
    with (bank / "facts/tables.csv").open(encoding="utf-8") as f:
        for t in csv.DictReader(f):
            tables[t["arxiv"]].append((int(t["first"]), int(t["last"])))
    return tables


# ---------------------------------------------------------------- 可见内容


def _leaves(value: Any, field: str) -> Iterator[str]:
    """属性值中的字符串；``extra`` 存为 JSON 字符串，解开后逐个取。"""
    if field == "extra" and isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            pass
    if isinstance(value, str):
        yield value
    elif isinstance(value, list | tuple):
        for v in value:
            yield from _leaves(v, "")
    elif isinstance(value, dict):
        for k in sorted(value):
            yield from _leaves(value[k], "")


def visible_values(commits: list[dict[str, Any]]) -> Iterator[tuple[dict[str, Any], str, Any]]:
    """变更集中读者可见的属性值：（出处，字段，值）。出处含提交、操作、对象、字段与取自 before 还是 after。"""
    labels: dict[str, list[str]] = {}
    for c in commits:
        for it in c["changeset"].get("nodes", []):
            labels.setdefault(it["id"], it.get("labels") or [])
    for c in commits:
        base = {"commit": c["id"], "seq": int(c["seq"])}
        for it in c["changeset"].get("nodes", []):
            node_labels = it.get("labels") or labels.get(it["id"], [])
            if "Material" in node_labels:
                continue
            fields = {"raw"} if "NameKey" in node_labels else None
            for side, field, value in _changed(it):
                if (fields is not None and field not in fields) or field in NODE_HIDDEN:
                    continue
                yield {**base, "op": it["op"], "node": it["id"], "field": field, "side": side}, field, value
        for it in c["changeset"].get("edges", []):
            ends = labels.get(it["from"], []) + labels.get(it["to"], [])
            if SYSTEM_LABELS & set(ends):
                continue
            edge = f"{it['from']}-[{it['type']}]->{it['to']}"
            for side, field, value in _changed(it):
                if field in EDGE_HIDDEN:
                    continue
                yield {**base, "op": it["op"], "edge": edge, "field": field, "side": side}, field, value


def _changed(item: dict[str, Any]) -> Iterator[tuple[str, str, Any]]:
    """变更集的一项 → （before／after，字段，值）：创建取 after，删除取 before，修改取 props 中每个字段的两侧。"""
    if item["op"] == "update":
        for field, change in sorted((item.get("props") or {}).items()):
            for side in ("before", "after"):
                if change.get(side) is not None:
                    yield side, field, change[side]
        return
    side = "after" if item["op"] == "create" else "before"
    for field, value in sorted((item.get(side) or {}).items()):
        if value is not None:
            yield side, field, value


def documents_of(snapshot: Path, commits: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """提交中的文件记录（产物文档的各个版本）：逐份读 ``documents/<path>``，核对哈希；缺失或不符即停。"""
    docs, seen = [], set()
    for c in commits:
        for f in c["changeset"].get("files", []):
            path = snapshot / "documents" / f["path"]
            if not path.is_file():
                raise InputError(f"{c['id']}: document {f['path']} is missing from the snapshot")
            if sha256_file(path) != f["sha256"]:
                raise InputError(f"{c['id']}: document {f['path']} does not match its sha256")
            if f["path"] in seen:
                raise InputError(f"document {f['path']} is recorded twice")
            seen.add(f["path"])
            docs.append({"commit": c["id"], "seq": int(c["seq"]), "path": f["path"], "sha256": f["sha256"],
                         "text": path.read_text(encoding="utf-8")})  # fmt: skip
    on_disk = {p.relative_to(snapshot / "documents").as_posix() for p in (snapshot / "documents").rglob("*") if p.is_file()}
    return docs, {"documents": len(docs), "hash_ok": len(docs), "not_in_history": sorted(on_disk - seen)}


def replay_check(snapshot: Path, commits: list[dict[str, Any]]) -> dict[str, Any]:
    """按变更集重放出节点与边的属性，与检查点的当前图（``graph.jsonl``）逐个比对：历史能完整解释当前状态，才说明
    没有漏掉提交。修改与删除先核对旧值：修改的每个字段的 ``before`` 与当时状态相同（字段原来没有时为 ``None``），删除的
    ``before`` 与被删对象当时的全部属性相同。只比对受版本管理的字段（不含派生字段）。"""
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[tuple[str, str, str], dict[str, Any]] = {}
    for c in commits:
        for sect, store in (("nodes", nodes), ("edges", edges)):
            for it in c["changeset"].get(sect, []):
                key = it["id"] if sect == "nodes" else (it["from"], it["type"], it["to"])
                if it["op"] == "create":
                    if key in store:
                        raise InputError(f"{c['id']}: {key} created twice")
                    store[key] = dict(it.get("after") or {})
                elif it["op"] == "delete":
                    if key not in store:
                        raise InputError(f"{c['id']}: {key} deleted but never created")
                    if (it.get("before") or {}) != store[key]:
                        raise InputError(f"{c['id']}: replay: the before of deleting {key} is not its state then")
                    del store[key]
                else:
                    if key not in store:
                        raise InputError(f"{c['id']}: {key} updated but never created")
                    for field, change in (it.get("props") or {}).items():
                        if change.get("before") != store[key].get(field):
                            raise InputError(f"{c['id']}: replay: the before of {key}.{field} is not its state then")
                        if change.get("after") is None:
                            store[key].pop(field, None)
                        else:
                            store[key][field] = change["after"]
    derived = {"embedding", "embedding_key", "search_text", "name_embedding", "fact_embedding"}
    current_nodes, current_edges = {}, {}
    for r in read_jsonl(snapshot / "graph.jsonl"):
        props = {k: v for k, v in r["props"].items() if k not in derived}
        if "node" in r:
            current_nodes[r["node"]] = props
        else:
            current_edges[tuple(r["edge"])] = props
    norm = lambda d: {k: v for k, v in d.items() if k not in derived and k != "id"}  # noqa: E731
    diff_nodes = sorted(k for k in nodes.keys() | current_nodes.keys() if norm(nodes.get(k, {"?": 1})) != norm(current_nodes.get(k, {"!": 1})))
    diff_edges = sorted(k for k in edges.keys() | current_edges.keys() if norm(edges.get(k, {"?": 1})) != norm(current_edges.get(k, {"!": 1})))
    if diff_nodes or diff_edges:
        raise InputError(f"history does not replay to the checkpoint graph: nodes {diff_nodes[:5]}, edges {diff_edges[:5]}")
    return {"nodes": len(nodes), "edges": len(edges), "replay": "ok"}


# ---------------------------------------------------------------- 收集


def merge(spans: list[tuple[int, int]]) -> list[list[int]]:
    """重叠或相邻的区间合并。"""
    out: list[list[int]] = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1] + 1:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


class Gather:
    """各组共用的接受、校验与扩块：每条引用要么扩成块记入 ``origins``，要么连同原因记入 ``dropped``；只写来源的记为提及。"""

    def __init__(self, sources: Sources, tables: dict[str, list[tuple[int, int]]]):
        self.sources, self.tables = sources, tables
        self.origins: list[dict[str, Any]] = []
        self.dropped: list[dict[str, Any]] = []
        self.mentions: Counter[str] = Counter()
        self.blocks: set[tuple[str, int, int]] = set()

    def scan(self, where: dict[str, Any], channel: str, text: str) -> None:
        for raw, parsed in scan(text):
            self.take(where, channel, raw, parsed)

    def take(self, where: dict[str, Any], channel: str, raw: str, parsed: Ref | str) -> None:
        if parsed == "mention":
            self.mentions[channel] += 1
            return
        if isinstance(parsed, str):
            self.dropped.append({"channel": channel, "ref": raw, "reason": parsed, "where": where})
            return
        lines = self.sources.lines(parsed)
        if isinstance(lines, str):
            self.dropped.append({"channel": channel, "ref": raw, "reason": lines, "where": where})
            return
        if not 1 <= parsed.start <= parsed.end <= len(lines):
            self.dropped.append({"channel": channel, "ref": raw, "reason": "bad-range", "where": where,
                                 "lines": len(lines)})  # fmt: skip
            return
        if parsed.file:
            a, b = code_block(lines, parsed.start, parsed.end)
        else:
            a, b = paper_block(lines, parsed.start, parsed.end, self.tables.get(parsed.source, []))
        self.blocks.add((parsed.key, a, b))
        self.origins.append({"channel": channel, "ref": raw, "source": parsed.key, "lines": [parsed.start, parsed.end],
                             "passage": [a, b], "where": where})  # fmt: skip

    def result(self) -> tuple[dict[str, list[list[int]]], dict[str, list[list[int]]]]:
        """``passages``（每个来源去重后的块）与 ``readable``（合并后的可读区间）。"""
        passages: dict[str, list[list[int]]] = defaultdict(list)
        for key, a, b in sorted(self.blocks):
            passages[key].append([a, b])
        readable = {key: merge([tuple(s) for s in spans]) for key, spans in passages.items()}
        return dict(passages), readable


def collect(run: Path, arm: str, papers: int, bank: Path = BANK) -> dict[str, Any]:
    if arm == "A0":
        return collect_a0(run, papers, bank)
    if arm not in GRAPH_ARMS:
        raise NotImplementedError(f"{arm}: only {GRAPH_ARMS} and A0 are implemented")
    snapshot = run / "snapshots" / arm / f"k{papers}"
    backup_meta = run / "backups" / arm / f"k{papers}" / "meta.yml"
    recorded = yaml.safe_load((run / "checkpoints.yml").read_text(encoding="utf-8"))[arm][papers]
    snap_meta = yaml.safe_load((snapshot / "meta.yml").read_text(encoding="utf-8"))
    backup = yaml.safe_load(backup_meta.read_text(encoding="utf-8"))
    versions = {"checkpoints.yml": recorded, "snapshot": snap_meta["branches"]["main"], "backup": backup["version"]}
    if len(set(versions.values())) != 1:
        raise InputError(f"checkpoint versions disagree: {versions}")
    if backup.get("arm") != arm or backup.get("papers") != papers:
        raise InputError(f"backup meta is for {backup.get('arm')} k{backup.get('papers')}")
    commits, history = commits_of(snapshot, recorded)
    replay = replay_check(snapshot, commits)
    docs, doc_check = documents_of(snapshot, commits)
    opened = dict(backup["sources"])
    gather = Gather(Sources(run / arm / "sources", opened), load_tables(bank))

    for where, field, value in visible_values(commits):
        structured = field in (STRUCTURED_EDGE if "edge" in where else STRUCTURED_NODE)
        for leaf in _leaves(value, field):
            if structured:
                gather.take(where, "structured", leaf, parse(leaf))
            else:
                gather.scan(where, "text", leaf)
        if structured and not isinstance(value, list | str):
            gather.dropped.append({"channel": "structured", "ref": json.dumps(value), "reason": "format", "where": where})
    for doc in docs:
        gather.scan({"commit": doc["commit"], "seq": doc["seq"], "document": doc["path"]}, "text", doc["text"])
    for c in commits:
        for field in COMMIT_FIELDS:
            gather.scan({"commit": c["id"], "seq": int(c["seq"]), "field": field}, "commit", c.get(field) or "")

    passages, readable = gather.result()
    stats = _stats(gather.origins, gather.dropped, gather.mentions, readable)
    origins, dropped = gather.origins, gather.dropped
    inputs = {
        "snapshot": {n: sha256_file(snapshot / n) for n in ("meta.yml", "commits.jsonl", "graph.jsonl")},
        "backup_meta": sha256_file(backup_meta),
        "tables_csv": sha256_file(bank / "facts/tables.csv"),
        "sources": opened,
        "documents": {d["path"]: d["sha256"] for d in docs},
    }
    return {
        "arm": arm, "checkpoint": papers, "version": recorded, "rule": RULE,
        "inputs": inputs,
        "checks": {"versions": versions, "history": history, "replay": replay, "documents": doc_check,
                   "sources": "sha256 ok"},
        "stats": stats,
        "passages": dict(sorted(passages.items())),
        "readable": dict(sorted(readable.items())),
        "origins": origins,
        "dropped": dropped,
    }  # fmt: skip


def _lines_of(readable: dict[str, list[list[int]]]) -> int:
    return sum(b - a + 1 for spans in readable.values() for a, b in spans)


def _stats(origins: list[dict[str, Any]], dropped: list[dict[str, Any]], mentions: Counter[str],
           readable: dict[str, list[list[int]]], channels: tuple[str, ...] = CHANNELS) -> dict[str, Any]:  # fmt: skip
    """分通道：接受的引用、块、可读行、丢弃（按原因）与提及；``beyond_structured``：自由文本与提交两个通道各自、
    以及合起来，在结构化字段之外新增的块与可读行；``before_side``：取自修改前或删除前的值的引用出现次数（不等于只在
    历史中有的引用：同一引用可能也在当前状态中）。A0 没有结构化通道，只有前一部分与 ``total``。"""
    blocks = {ch: {(o["source"], *o["passage"]) for o in origins if o["channel"] == ch} for ch in channels}
    out: dict[str, Any] = {"channels": {}}
    for ch in channels:
        out["channels"][ch] = {
            "accepted": sum(o["channel"] == ch for o in origins), "blocks": len(blocks[ch]),
            "readable_lines": _lines_of(_spans(blocks[ch])),
            "dropped": dict(sorted(Counter(d["reason"] for d in dropped if d["channel"] == ch).items())),
            "mentions": mentions[ch],
        }  # fmt: skip
    out["total"] = {"blocks": len(set().union(*blocks.values())), "readable_lines": _lines_of(readable),
                    "sources": len(readable)}  # fmt: skip
    if "structured" not in channels:
        return out
    base = _lines_of(_spans(blocks["structured"]))
    out["beyond_structured"] = {}
    for name, chs in (("text", ("text",)), ("commit", ("commit",)), ("text+commit", ("text", "commit"))):
        extra = set().union(*(blocks[c] for c in chs)) - blocks["structured"]
        out["beyond_structured"][name] = {
            "blocks": len(extra), "readable_lines": _lines_of(_spans(blocks["structured"] | extra)) - base,
            "sources": sorted({k for k, _, _ in extra}),
        }
    out["before_side"] = sum(o["where"].get("side") == "before" for o in origins)
    return out


def _spans(blocks: set[tuple[str, int, int]]) -> dict[str, list[list[int]]]:
    spans: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for key, a, b in blocks:
        spans[key].append((a, b))
    return {k: merge(v) for k, v in spans.items()}


# ---------------------------------------------------------------- A0：Git 历史

A0_REPO = "A0/shared.git"  # 共享仓库：裸仓库，只存已发布的提交（pweval.harness.timeline.shared_repo）
A0_CHANNELS = ("text", "commit")
LOG_FORMAT = "%H%x1f%an%x1f%aI%x1f%s"  # 快照 log.jsonl 的导出格式（pweval.harness.export.export_a0）
LOG_FIELDS = ("id", "author", "at", "message")
NULL_SHA = "0" * 40
SHINGLE = 12  # 原文核对：连续 12 个词的滑窗；论文一段常是一整行，按行比只能发现整段照抄
WORD = re.compile(r"\w+")


def _git(repo: Path, *args: str, data: bytes | None = None) -> bytes:
    return subprocess.run(["git", "-C", str(repo), *args], input=data, capture_output=True, check=True).stdout


def _objects(repo: Path, shas: Sequence[str]) -> dict[str, bytes]:
    """一次 ``git cat-file --batch`` 读出全部对象；缺一个即停。"""
    wanted = sorted(set(shas))
    if not wanted:
        return {}
    out = _git(repo, "cat-file", "--batch", data="".join(f"{s}\n" for s in wanted).encode())
    objects, pos = {}, 0
    for sha in wanted:
        end = out.index(b"\n", pos)
        head = out[pos:end].decode().split()
        if len(head) != 3 or head[0] != sha:
            raise InputError(f"git object {sha} is missing from {repo}")
        size = int(head[2])
        objects[sha] = out[end + 1 : end + 1 + size]
        pos = end + 2 + size
    return objects


def a0_history(repo: Path, snapshot: Path, recorded: str,
               ref: str | None = None) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:  # fmt: skip
    """检查点之前的全部提交，按提交顺序，带完整的提交说明（``%B``，收集引用用它）。核对：``checkpoints.yml``、快照
    标签所指的提交与快照的 ``head`` 相同；只有一个根；快照的 ``log.jsonl`` 与 Git 按原导出格式重新导出的逐条逐字段
    相同（id、作者、时间与首行标题 ``%s``；标题只用于这项核对）。``ref`` 缺省为快照的标签；读者仓库没有标签，给
    ``refs/heads/main``（:mod:`pweval.harness.store_readers`）。"""
    meta = yaml.safe_load((snapshot / "meta.yml").read_text(encoding="utf-8"))
    head = _git(repo, "rev-parse", "--verify", f"{ref or meta['tag']}^{{commit}}").decode().strip()
    versions = {"checkpoints.yml": recorded, "tag": head, "snapshot": meta["head"]}
    if len(set(versions.values())) != 1:
        raise InputError(f"checkpoint versions disagree: {versions}")
    chain = [line.split() for line in _git(repo, "rev-list", "--reverse", "--parents", head).decode().splitlines()]
    ids = [c[0] for c in chain]
    if [c for c in chain if len(c) == 1] != [chain[0]]:
        raise InputError("the history must have exactly one root, its first commit")
    log = _git(repo, "log", "--reverse", f"--format={LOG_FORMAT}", head).decode("utf-8")
    exported = [dict(zip(LOG_FIELDS, line.split("\x1f"), strict=True)) for line in log.splitlines() if line]
    if read_jsonl(snapshot / "log.jsonl") != exported or [r["id"] for r in exported] != ids:
        raise InputError(f"the snapshot log differs from the history of {head}")
    if meta["counts"]["commits"] != len(ids):
        raise InputError(f"the snapshot says {meta['counts']['commits']} commits, the history of {head} has {len(ids)}")
    raw = _objects(repo, ids)
    commits = []
    for seq, (cid, *parents) in enumerate(chain, 1):
        _, _, message = raw[cid].decode("utf-8").partition("\n\n")  # 提交对象：头部、空行、完整说明
        commits.append({"id": cid, "seq": seq, "parents": parents, "message": message})
    merges = sum(len(c) > 2 for c in chain)
    return commits, versions, {"commits": len(ids), "first": ids[0], "head": head, "merges": merges, "log": "ok"}


def a0_tree(repo: Path, head: str, snapshot: Path) -> dict[str, Any]:
    """检查点提交的文件树与快照的 ``tree/`` 逐个相同（按 Git 的 blob 哈希比）。"""
    want = {}
    for item in filter(None, _git(repo, "ls-tree", "-r", "-z", "--full-tree", head).decode("utf-8").split("\0")):
        info, path = item.split("\t", 1)
        _, kind, sha = info.split()
        if kind != "blob":
            raise InputError(f"{head}: {path} is a {kind}, not a file")
        want[path] = sha
    root, got = snapshot / "tree", {}
    for p in sorted(root.rglob("*")):
        if p.is_symlink():
            data = os.readlink(p).encode()
        elif p.is_file():
            data = p.read_bytes()
        else:
            continue
        got[p.relative_to(root).as_posix()] = hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()
    if differ := sorted(k for k in got.keys() | want.keys() if got.get(k) != want.get(k)):
        raise InputError(f"the snapshot tree differs from {head}: {differ[:5]}")
    return {"files": len(want), "tree": "ok"}


def a0_files(repo: Path, commits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """每个提交写下的文件版本（新增、修改与类型改变；与第一个父提交比），即读者经 ``git show`` 能看到的全部正文。"""
    out = []
    for c in commits:
        args = ["--root", c["id"]] if not c["parents"] else [c["parents"][0], c["id"]]
        fields = _git(repo, "diff-tree", "-r", "-z", "--no-renames", "--no-commit-id", *args).decode("utf-8").split("\0")
        for info, path in zip(fields[0::2], fields[1::2], strict=False):
            if not info:
                continue
            _, mode, _, sha, status = info.lstrip(":").split()
            if status != "D" and mode != "160000" and sha != NULL_SHA:
                out.append({"commit": c["id"], "seq": c["seq"], "file": path, "blob": sha})
    return out


def _arms_of(argv: list[str]) -> set[str]:
    """写者运行的 ``--arms``（缺省为 A3、A2，同 :data:`pweval.harness.timeline.DEFAULT_ARMS`）。"""
    for i, a in enumerate(argv):
        if a == "--arms" and i + 1 < len(argv):
            return set(argv[i + 1].split(","))
        if a.startswith("--arms="):
            return set(a.removeprefix("--arms=").split(","))
    return {"A3", "A2"}


def a0_frozen(run: Path, bank: Path) -> dict[str, Any]:
    """A0 写者运行时的计划与材料表：运行记录（``run.yml``）中跑过 A0 的每次调用都必须是同一个干净的题库提交、同一份
    计划与材料表的路径；内容从题库在那个提交的版本中取（``git show``），不读题库当前的工作树。"""
    calls = [c for c in yaml.safe_load((run / "run.yml").read_text(encoding="utf-8"))["invocations"]
             if "A0" in _arms_of(c["argv"])]  # fmt: skip
    if not calls:
        raise InputError(f"{run / 'run.yml'}: no invocation ran A0")
    used = {(c["probes"]["commit"], c["probes"]["dirty"], c["config"]["plan"], c["config"]["materials"]) for c in calls}
    if len(used) != 1:
        raise InputError(f"A0 ran with different probe banks or tables: {sorted(used)}")
    commit, dirty, plan, materials = used.pop()
    if dirty:
        raise InputError(f"A0 ran with uncommitted changes in the probe bank (at {commit})")
    out: dict[str, Any] = {"commit": commit, "invocations": [c["started"] for c in calls]}
    for name, path in (("plan", plan), ("materials", materials)):
        try:
            data = _git(bank, "show", f"{commit}:{path}")
        except subprocess.CalledProcessError as e:
            raise InputError(f"{bank}: cannot read {path} at {commit}") from e
        out[name] = {"path": path, "sha256": hashlib.sha256(data).hexdigest(), "text": data.decode("utf-8")}
    return out


def a0_opened(run: Path, papers: int, frozen: dict[str, Any], start: str, recorded: str) -> tuple[dict[str, str], dict[str, Any]]:
    """检查点上开放的来源（ID → 哈希）：以写者运行时冻结的计划与材料表为准（:func:`a0_frozen`），即种子加上检查点之前
    各会话新开放的来源；不看组的来源目录（那是最后一个检查点的状态）。再与 A0 的会话记录交叉核对：检查点之前每个会话
    恰好一条，点出与新开放的来源同材料表，可取的来源数（``available``）与推导相同，取到的来源都已开放，版本从第 0 个
    检查点首尾相接到这个检查点。"""
    steps = yaml.safe_load(frozen["plan"]["text"])
    table = yaml.safe_load(frozen["materials"]["text"])
    plan = frozen["plan"]["path"]
    last = None
    for step in steps:
        if step["type"] == "checkpoint" and step["papers"] == papers:
            break
        if "seq" in step:
            last = step["seq"]
    else:
        raise InputError(f"{plan}: no checkpoint at {papers} papers")
    plan_rows = {r["seq"]: r for r in table["sessions"]}
    through, ids = {}, list(table["seed"])
    for seq in range(1, last + 1):
        ids += [s for s in plan_rows.get(seq, {}).get("opens", []) if s not in ids]
        through[seq] = set(ids)
    opened = {s: table["sources"][s]["sha256"] for s in sorted(ids)}
    lines = [line for line in (run / "sessions.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = sorted((r for r in map(json.loads, lines) if r["arm"] == "A0" and r["seq"] <= last), key=lambda r: r["seq"])
    if [r["seq"] for r in rows] != list(range(1, last + 1)):
        raise InputError(f"A0 session records up to seq {last} are not one per session")
    version = start
    for r in rows:
        row = plan_rows.get(r["seq"], {})
        if (r["materials"]["named"], r["materials"]["opens"]) != (row.get("named", []), row.get("opens", [])):
            raise InputError(f"A0 session {r['seq']}: its materials differ from the frozen materials table")
        if r["materials"].get("available") != len(through[r["seq"]]):
            raise InputError(f"A0 session {r['seq']}: {r['materials'].get('available')} sources available, "
                             f"the frozen tables give {len(through[r['seq']])}")  # fmt: skip
        if unopened := set((r.get("read_source") or {}).get("fetched", [])) - through[r["seq"]]:
            raise InputError(f"A0 session {r['seq']} fetched unopened sources {sorted(unopened)}")
        if r["version_before"] != version:
            raise InputError(f"A0 session {r['seq']} starts at {r['version_before']}, the previous ended at {version}")
        version = r["version_after"]
    if version != recorded:
        raise InputError(f"A0 sessions end at {version}, the checkpoint is {recorded}")
    digest = hashlib.sha256("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows).encode()).hexdigest()
    return opened, {"last_session": last, "sessions": len(rows), "sessions_sha256": digest, "chain": "ok"}


def _shingles(text: str) -> set[str]:
    words = WORD.findall(text.lower())
    return {" ".join(words[i : i + SHINGLE]) for i in range(len(words) - SHINGLE + 1)}


def _source_shingles(sources: Sources) -> dict[str, set[str]]:
    """开放来源 → 其中的滑窗；代码取仓库中全部 UTF-8 文本文件。"""
    out = {}
    for source in sources.opened:
        path = sources.root / source
        files = sorted(p for p in path.rglob("*") if p.is_file()) if CODE_SOURCE.fullmatch(source) else [path / "paper.md"]
        found: set[str] = set()
        for f in files:
            try:
                found |= _shingles(f.read_bytes().decode("utf-8"))
            except UnicodeDecodeError:
                continue
        out[source] = found
    return out


def source_text(texts: list[tuple[dict[str, Any], str]], sources: Sources) -> dict[str, Any]:
    """原文进入仓库的程度（设计 §2、§6.3：A0 写者提交的原文单独报告）：每个开放来源的连续 ``SHINGLE`` 词滑窗（小写、
    只取字母数字词，不受换行、标点与 Markdown 记号影响），有多少逐字出现在检查点之前的某个文件版本中
    （``in_history``）、单个文件版本中最多有多少（``max_in_one_file``）。只列至少出现一个滑窗的来源。另列路径像来源
    副本的文件（``sources/`` 之下或名为 ``paper.md``）。改写过的转述不算。"""
    shingles = _source_shingles(sources)
    index: dict[str, list[str]] = defaultdict(list)
    for source, found in shingles.items():
        for g in found:
            index[g].append(source)
    union: dict[str, set[str]] = defaultdict(set)
    best: dict[str, tuple[int, dict[str, Any]]] = {}
    for where, text in texts:
        hits: dict[str, set[str]] = defaultdict(set)
        for g in _shingles(text):
            for source in index.get(g, ()):
                hits[source].add(g)
        for source, found in hits.items():
            union[source] |= found
            if len(found) > best.get(source, (0, {}))[0]:
                best[source] = (len(found), where)
    per_source = {
        s: {"shingles": len(shingles[s]), "in_history": len(union[s]),
            "share": round(len(union[s]) / len(shingles[s]), 4), "max_in_one_file": best[s][0], "file": best[s][1]}
        for s in sorted(union)
    }  # fmt: skip
    paths = sorted({w["file"] for w, _ in texts if "file" in w and (w["file"].startswith("sources/")
                                                                    or PurePosixPath(w["file"]).name == "paper.md")})  # fmt: skip
    return {"shingle_words": SHINGLE, "sources": per_source, "source_like_paths": paths}


def collect_a0(run: Path, papers: int, bank: Path = BANK) -> dict[str, Any]:
    """A0 的放行名单：检查点及之前每个提交写下的每个文件版本（text 通道）与完整的提交说明（commit 通道），同一套扫描、
    校验与扩块。不按 YAML 解析文件，没有 structured 通道（10-24 用户定）。"""
    repo, snapshot = run / A0_REPO, run / "snapshots" / "A0" / f"k{papers}"
    checkpoints = yaml.safe_load((run / "checkpoints.yml").read_text(encoding="utf-8"))["A0"]
    recorded = checkpoints[papers]
    commits, versions, history = a0_history(repo, snapshot, recorded)
    tree = a0_tree(repo, history["head"], snapshot)
    frozen = a0_frozen(run, bank)
    opened, sessions = a0_opened(run, papers, frozen, checkpoints[0], recorded)
    gather = Gather(Sources(run / "A0" / "sources", opened), load_tables(bank))

    files = a0_files(repo, commits)
    blobs = _objects(repo, [f["blob"] for f in files])
    texts, not_text = [], []
    for f in files:
        where = {"commit": f["commit"], "seq": f["seq"], "file": f["file"]}
        try:
            texts.append((where, blobs[f["blob"]].decode("utf-8")))
        except UnicodeDecodeError:
            not_text.append(where)
    for where, text in texts:
        gather.scan(where, "text", text)
    for c in commits:
        gather.scan({"commit": c["id"], "seq": c["seq"], "field": "message"}, "commit", c["message"])

    passages, readable = gather.result()
    inputs = {
        "repository": {"tag": yaml.safe_load((snapshot / "meta.yml").read_text(encoding="utf-8"))["tag"],
                       "head": history["head"]},
        "snapshot": {"meta.yml": sha256_file(snapshot / "meta.yml"), "log.jsonl": sha256_file(snapshot / "log.jsonl"),
                     "tree": tree_sha256(snapshot / "tree")},
        "probes": {"commit": frozen["commit"], "invocations": frozen["invocations"],
                   **{n: {k: frozen[n][k] for k in ("path", "sha256")} for n in ("plan", "materials")}},
        "sessions_sha256": sessions["sessions_sha256"],
        "tables_csv": sha256_file(bank / "facts/tables.csv"),
        "sources": opened,
    }  # fmt: skip
    return {
        "arm": "A0", "checkpoint": papers, "version": recorded, "rule": RULE,
        "inputs": inputs,
        "checks": {"versions": versions, "history": history, "tree": tree, "sessions": sessions,
                   "files": {"versions": len(files), "text": len(texts), "not_text": not_text}, "sources": "sha256 ok"},
        "stats": _stats(gather.origins, gather.dropped, gather.mentions, readable, A0_CHANNELS),
        "source_text": source_text(texts, gather.sources),
        "passages": dict(sorted(passages.items())),
        "readable": dict(sorted(readable.items())),
        "origins": gather.origins,
        "dropped": gather.dropped,
    }  # fmt: skip


# ---------------------------------------------------------------- 命令行


def write(result: dict[str, Any], out: Path, force: bool = False) -> Path:
    """写 ``<out>/<组>/k<篇数>.json`` 与旁边的 ``.sha256``。已有且内容不同时不覆盖，除非 ``force``。"""
    path = out / result["arm"] / f"k{result['checkpoint']}.json"
    data = (json.dumps(result, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")
    if path.exists() and path.read_bytes() != data and not force:
        raise FileExistsError(f"{path} exists with different content; pass --force to replace it")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.partial")
    tmp.write_bytes(data)
    tmp.replace(path)
    path.with_name(path.name + ".sha256").write_text(f"{hashlib.sha256(data).hexdigest()}  {path.name}\n", encoding="utf-8")
    return path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("run", type=Path, help="运行目录，如 ~/pw-lab/runs/f3")
    parser.add_argument("--arm", required=True, choices=(*GRAPH_ARMS, "A0"))
    parser.add_argument("--checkpoint", type=int, required=True, help="检查点（篇数）：10、20 或 30")
    parser.add_argument("--bank", type=Path, default=BANK, help="题库仓库（facts/tables.csv）")
    parser.add_argument("--out", type=Path, help="输出目录，默认 <运行目录>/allowlists")
    parser.add_argument("--force", action="store_true", help="已有名单内容不同时也覆盖")
    args = parser.parse_args(argv)
    run = args.run.expanduser()
    try:
        result = collect(run, args.arm, args.checkpoint, args.bank.expanduser())
    except InputError as e:
        print(f"input error: {e}", file=sys.stderr)
        return 2
    path = write(result, (args.out or run / "allowlists").expanduser(), args.force)
    print(path)
    print(json.dumps({"checks": result["checks"], "stats": result["stats"]}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

__all__ = ["Gather", "InputError", "Ref", "collect", "collect_a0", "merge", "normalize", "parse", "scan", "source_text", "write"]
