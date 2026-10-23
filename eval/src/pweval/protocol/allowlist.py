"""读者的放行名单：检查点上，库中记录过的来源引用所在的块（docs/experiments/f3/2026-10-22-f3-design.md §6.3）。

    python -m pweval.protocol.allowlist <运行目录> --arm A3 --checkpoint 10 [--bank DIR] [--out DIR] [--force]

只读检查点快照（``snapshots/<组>/k<篇数>/``）、检查点备份的 ``meta.yml``（开放的来源与哈希）、组的来源目录与题库的
``facts/tables.csv``，不连库、不调用模型。同样的输入得到逐字节相同的输出。先实现 A3、A2（图库组）；A0、A4 另接入口，
后面的解析、筛选与扩块共用。

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
import re
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


def collect(run: Path, arm: str, papers: int, bank: Path = BANK) -> dict[str, Any]:
    if arm not in GRAPH_ARMS:
        raise NotImplementedError(f"{arm}: only the graph arms {GRAPH_ARMS} are implemented")
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
    sources = Sources(run / arm / "sources", opened)
    tables = load_tables(bank)

    origins: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    mentions: Counter[str] = Counter()
    blocks: set[tuple[str, int, int]] = set()

    def take(where: dict[str, Any], channel: str, raw: str, parsed: Ref | str) -> None:
        if parsed == "mention":
            mentions[channel] += 1
            return
        if isinstance(parsed, str):
            dropped.append({"channel": channel, "ref": raw, "reason": parsed, "where": where})
            return
        lines = sources.lines(parsed)
        if isinstance(lines, str):
            dropped.append({"channel": channel, "ref": raw, "reason": lines, "where": where})
            return
        if not 1 <= parsed.start <= parsed.end <= len(lines):
            dropped.append({"channel": channel, "ref": raw, "reason": "bad-range", "where": where, "lines": len(lines)})
            return
        if parsed.file:
            a, b = code_block(lines, parsed.start, parsed.end)
        else:
            a, b = paper_block(lines, parsed.start, parsed.end, tables.get(parsed.source, []))
        blocks.add((parsed.key, a, b))
        origins.append({"channel": channel, "ref": raw, "source": parsed.key, "lines": [parsed.start, parsed.end],
                        "passage": [a, b], "where": where})  # fmt: skip

    for where, field, value in visible_values(commits):
        structured = field in (STRUCTURED_EDGE if "edge" in where else STRUCTURED_NODE)
        for leaf in _leaves(value, field):
            if structured:
                take(where, "structured", leaf, parse(leaf))
            else:
                for raw, parsed in scan(leaf):
                    take(where, "text", raw, parsed)
        if structured and not isinstance(value, list | str):
            dropped.append({"channel": "structured", "ref": json.dumps(value), "reason": "format", "where": where})
    for doc in docs:
        where = {"commit": doc["commit"], "seq": doc["seq"], "document": doc["path"]}
        for raw, parsed in scan(doc["text"]):
            take(where, "text", raw, parsed)
    for c in commits:
        for field in COMMIT_FIELDS:
            where = {"commit": c["id"], "seq": int(c["seq"]), "field": field}
            for raw, parsed in scan(c.get(field) or ""):
                take(where, "commit", raw, parsed)

    passages: dict[str, list[list[int]]] = defaultdict(list)
    for key, a, b in sorted(blocks):
        passages[key].append([a, b])
    readable = {key: merge([tuple(s) for s in spans]) for key, spans in passages.items()}
    stats = _stats(origins, dropped, mentions, readable)
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
           readable: dict[str, list[list[int]]]) -> dict[str, Any]:  # fmt: skip
    """分通道：接受的引用、块、可读行、丢弃（按原因）与提及；``beyond_structured``：自由文本与提交两个通道各自、
    以及合起来，在结构化字段之外新增的块与可读行；``before_side``：取自修改前或删除前的值的引用出现次数（不等于只在
    历史中有的引用：同一引用可能也在当前状态中）。"""
    blocks = {ch: {(o["source"], *o["passage"]) for o in origins if o["channel"] == ch} for ch in CHANNELS}
    out: dict[str, Any] = {"channels": {}}
    for ch in CHANNELS:
        out["channels"][ch] = {
            "accepted": sum(o["channel"] == ch for o in origins), "blocks": len(blocks[ch]),
            "readable_lines": _lines_of(_spans(blocks[ch])),
            "dropped": dict(sorted(Counter(d["reason"] for d in dropped if d["channel"] == ch).items())),
            "mentions": mentions[ch],
        }  # fmt: skip
    base = _lines_of(_spans(blocks["structured"]))
    out["beyond_structured"] = {}
    for name, chs in (("text", ("text",)), ("commit", ("commit",)), ("text+commit", ("text", "commit"))):
        extra = set().union(*(blocks[c] for c in chs)) - blocks["structured"]
        out["beyond_structured"][name] = {
            "blocks": len(extra), "readable_lines": _lines_of(_spans(blocks["structured"] | extra)) - base,
            "sources": sorted({k for k, _, _ in extra}),
        }
    out["before_side"] = sum(o["where"].get("side") == "before" for o in origins)
    out["total"] = {"blocks": len(set().union(*blocks.values())), "readable_lines": _lines_of(readable),
                    "sources": len(readable)}  # fmt: skip
    return out


def _spans(blocks: set[tuple[str, int, int]]) -> dict[str, list[list[int]]]:
    spans: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for key, a, b in blocks:
        spans[key].append((a, b))
    return {k: merge(v) for k, v in spans.items()}


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
    parser.add_argument("--arm", required=True, choices=GRAPH_ARMS)
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

__all__ = ["InputError", "Ref", "collect", "merge", "normalize", "parse", "scan", "write"]
