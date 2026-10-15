"""库健康度（evaluation_draft.md §4.3，诊断，不用 judge）：在检查点上从库中统计四项，两组用同一口径。

    python -m pweval.health <运行名> --checkpoint K [--arms A3,A0]    # 写出 <运行目录>/health/<组>-cp<K>.yml

只读：A3 读检查点的冻结快照（:mod:`pweval.snapshot`，``checkpoints/<K>/A3/``），A0 用 ``git show <检查点标签>:<路径>``，
都不改动写者的库。评测代码不导入被测系统（evaluation_draft §10.1）：产物文档的头部与数据块按格式自行解析。

1. **有据层忠实度**：库中抄下的每个结果数值，抽成（论文, 方法, 数据集, 预测长度, 指标, 数值），与核对读者清单的
   :func:`pweval.grade.verify` 一样对照原文结果表，分为 supported / misattributed / unsupported / unknown_paper。带出处
   行号的，另核对原文中对上的格子是否落在所引的行内（``anchor``：ok；near 为差 3 行以内，多是表的首尾行；off 为
   更远，多是引错了表）。A3 取 Extract 产物的数据行；A0 取论文笔记
   （``papers/*.md``）中的 Markdown 结果表，表上方最近的标题段中的 ``lines a-b`` 或 ``::a:b`` 作为出处行。其余形式
   的数值（正文、MatrixConstruct、方法笔记中的表）不计入，``coverage`` 给出计入与跳过的数量。
   论文有多个版本时（:mod:`pweval.versions`），数值按所引的版本核对（忠实于所引版本）；``versions`` 另计检查点时
   仍引用旧版本的数值（``cites_old``），以及其中当前版本已经不是这个数的（``outdated``：读者照此会读到旧值）。
2. **悬空引用率**：解析不了的引用占全部引用的比例。A3：数据行的来源引用（材料在、哈希一致、行号不越界）、数据行
   中引用的节点、产物文档的 ``nodes_used``、FROM 关系上的定位。A0：笔记间的相对链接、论文笔记中 ``::a:b`` 形式的
   行号引用（不越出材料的行数）、``material:`` 指向的材料。
3. **覆盖**：写者改动或删除了别的写者（含种子）写下的内容，分两类。``value``：数值丢失（A0 中删去的行里的数值在提交
   后的文件中不再出现；挪动或改格式不算）。``text``：别人写下的文字被改写或删除（A0 中删去的行在提交后的文件中不再
   原样出现；A3 中他人创建的节点的属性被改写或节点被删除）。文字类多是补全（种子的 stub 被写满）或润色，也可能是
   覆盖了别人的判断，自动分不开，``judgment`` 留空待标注。A3 提交元数据 ``revisions`` 中给了理由的标出 ``reason``。
   git 历史与 graph-vc 都留有痕迹，但读者读当前状态时看不到。
4. **重复实体候选**：方法、数据集、任务与论文按名字规范化后聚类，输出候选组供标注（``<组>-cp<K>-entities.yml``
   中的 ``same``，已填的在重新生成时保留）。重复率与误合并率由标注得出。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from . import snapshot, source_tables, versions
from .grade import paper_aliases, paper_of, verify
from .paths import REPO

SECTION_LINES = re.compile(r"::(\d+):(\d+)")
NOTE_LINES = re.compile(r"lines?\s+(\d+)\s*[-–]\s*(\d+)")
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
DERIVED = {"embedding", "embedding_key"}  # 派生属性，不算内容改写
NEAR = 3  # 对上的格子在所引行范围外不超过这么多行：记为 near（多是表的首尾行），而不是引错了表


@dataclass
class Fact:
    """库中的一个结果数值。``lines`` 是所引的原文行范围（若有）。"""

    paper: str
    method: str
    dataset: str
    horizon: int | None
    metric: str
    value: float | None
    lines: tuple[int, int] | None
    where: str

    def claim(self) -> dict[str, Any]:
        return {"paper": self.paper, "method": self.method, "dataset": self.dataset, "horizon": self.horizon,
                "metric": self.metric.lower(), "value": self.value}  # fmt: skip


def fidelity(
    facts: list[Fact], material_root: Path, aliases: dict[str, str], config: dict[str, Any] | None = None, k: int | None = None
) -> dict[str, Any]:
    counts: dict[str, int] = {}
    anchors = {"ok": 0, "near": 0, "off": 0, "none": 0}
    problems = []
    others = versions.siblings(config) if config else {}
    current = {old: versions.version_at(config, new, k) for new, old in versions.first_versions(config).items()} if config else {}
    old = {"cites_old": 0, "outdated": 0, "items": []}
    for fact in facts:
        claim = fact.claim()
        status = verify(claim, material_root, aliases, others)
        cited = paper_of(fact.paper, aliases)
        if cited in current and current[cited] != cited:
            old["cites_old"] += 1
            if verify({**claim, "paper": current[cited]}, material_root, aliases) != "supported":
                old["outdated"] += 1
                old["items"].append({"where": fact.where, **claim})
        counts[status] = counts.get(status, 0) + 1
        if status == "supported" and fact.lines:
            arxiv = paper_of(fact.paper, aliases) or ""
            cells = [
                c
                for c in source_tables.lookup(material_root, arxiv, source_tables.dataset_in(material_root, arxiv, fact.dataset), fact.horizon or 0, claim["metric"])
                if abs(c.value - (fact.value or 0)) < 1e-9 and source_tables.same_method(fact.method, c.header)
            ]
            gap = min(max(fact.lines[0] - c.line, c.line - fact.lines[1], 0) for c in cells)
            kind = "ok" if gap == 0 else "near" if gap <= NEAR else "off"
            anchors[kind] += 1
            if kind == "off":
                problems.append({"where": fact.where, "status": "anchor_off", "cited": list(fact.lines),
                                 "found": sorted({c.line for c in cells})})  # fmt: skip
        elif status == "supported":
            anchors["none"] += 1
        if status != "supported":
            problems.append({"where": fact.where, "status": status, **claim})
    total = len(facts)
    return {
        "values": total,
        "status": counts,
        "supported_rate": round(counts.get("supported", 0) / total, 4) if total else None,
        "anchor": anchors,
        "problems": problems,
        **({"versions": old} if current else {}),
    }


def _alias(name: str) -> str:
    return re.sub(r"^arxiv:?|\s+", "", name.strip().lower())


def rate(bad: list[dict[str, Any]], total: int) -> dict[str, Any]:
    return {"references": total, "dangling": len(bad), "rate": round(len(bad) / total, 4) if total else None, "items": bad}


def candidates(objects: list[tuple[str, str, str]]) -> list[dict[str, Any]]:
    """（类型, id 或路径, 名字）按规范化名字聚类：名字相同，或一个是另一个加变体后缀（``PatchTST`` 与 ``PatchTST/64``、
    ``Weather`` 与 ``Weather (NOAA)``）；数据集名先按别名归一（``Exchange-Rate`` 与 ``Exchange``）。只输出多于一个成员
    的组。这只是给标注者的候选：名字完全不同的重复（``ECL`` 之外的别名）找不到，标注时另记。"""

    def base(kind: str, name: str) -> str:
        head = re.split(r"[/(:]", name, maxsplit=1)[0]
        return source_tables.norm_dataset(head) if kind == "Dataset" else re.sub(r"[^a-z0-9]", "", head.lower())

    groups: dict[tuple[str, str], list[dict[str, str]]] = {}
    for kind, ident, name in objects:
        key = (kind, base(kind, name))
        if key[1]:
            groups.setdefault(key, []).append({"id": ident, "name": name})
    return [
        {"kind": k, "members": sorted(m, key=lambda x: x["id"]), "same": None}
        for (k, _), m in sorted(groups.items())
        if len(m) > 1
    ]


# ---------------------------------------------------------------- A3


def a3_health(
    state: Any,
    history: list[Any],
    since: str,
    until: str,
    locate: Callable[[str], Path],
    material_root: Path,
    config: dict[str, Any],
    k: int | None = None,
) -> dict[str, Any]:
    """检查点状态 ``state``；覆盖只计 ``since``（检查点 0）之后、``until``（含）之前的提交。``locate`` 把材料的相对
    路径映射到文件（产物文档取快照中的副本，论文取材料根目录）。"""
    aliases = paper_aliases(config, k)
    nodes = state.nodes
    facts, skipped, refs, bad = [], {}, 0, []

    def name(ident: Any) -> str:
        node = nodes.get(str(ident))
        return str(node.props.get("name", ident)) if node else str(ident)

    materials = {i: n.props for i, n in nodes.items() if "Material" in n.labels}
    artifact_file = {
        e.dst: materials[e.src]["path"] for e in state.edges if e.type == "MATERIAL_OF" and e.src in materials
    }

    def check_ref(ref: str, where: str) -> tuple[str | None, tuple[int, int] | None]:
        """来源引用 ``<材料或论文 id>::<章节>::a:b``：返回论文 arXiv id 与行范围；解析不了的记入悬空。"""
        nonlocal refs
        refs += 1
        head, _, rest = ref.partition("::")
        lines = SECTION_LINES.search("::" + rest.rsplit("::", 1)[-1]) if rest else None
        material = materials.get(head) or _paper_material(head, nodes, state, materials)
        if material is None:
            bad.append({"where": where, "ref": ref, "why": "no such material"})
            return None, None
        path = locate(material["path"])
        if not path.exists():
            bad.append({"where": where, "ref": ref, "why": "file missing"})
            return None, None
        text = path.read_bytes()
        if _sha256(text) != material.get("content_hash"):
            bad.append({"where": where, "ref": ref, "why": "file changed"})
        n = text.decode("utf-8").count("\n") + 1
        span = (int(lines.group(1)), int(lines.group(2))) if lines else None
        if span and not 1 <= span[0] <= span[1] <= n:
            bad.append({"where": where, "ref": ref, "why": f"lines out of range (1-{n})"})
        arxiv = re.match(r"papers/([^/]+)/", material["path"])
        return (arxiv.group(1) if arxiv else None), span

    for art, props in sorted((i, n.props) for i, n in nodes.items() if "Artifact" in n.labels):
        path = artifact_file.get(art)
        if path is None:
            refs += 1
            bad.append({"where": art, "ref": "document", "why": "no document material"})
            continue
        text = locate(path).read_text(encoding="utf-8")
        for used in _header_of(text).get("nodes_used") or []:
            if "::" in str(used):
                check_ref(str(used), f"{art} nodes_used")
            else:
                refs += 1
                if str(used).split("#")[0] not in nodes:
                    bad.append({"where": f"{art} nodes_used", "ref": used, "why": "no such node"})
        if props.get("op") != "Extract":
            skipped[props.get("op", "?")] = skipped.get(props.get("op", "?"), 0) + 1
            continue
        block = _data_of(text) or {}
        fields = (block.get("schema") or {}).get("fields") or {}
        role = _roles(fields)
        default_paper = _used_paper(art, state, nodes)
        for n, row in enumerate(block.get("rows") or []):
            where = f"{art}#{row.get('key', n)}"
            for f, t in fields.items():
                if t == "ref" and row.get(f) is not None:
                    refs += 1
                    if str(row[f]) not in nodes:
                        bad.append({"where": where, "ref": row[f], "why": f"field {f}: no such node"})
            paper, span = (None, None)
            if row.get("source"):
                paper, span = check_ref(str(row["source"]), where)
            paper = paper or default_paper
            for metric, value_field, suffix in role["values"]:
                if row.get(value_field) is None:
                    continue
                facts.append(Fact(
                    paper=paper or "?",
                    method=name(row.get(role["method"])) if role["method"] else "?",
                    dataset=name(row.get(role["dataset"])) if role["dataset"] else "?",
                    horizon=_int(row.get(role["horizon"])) if role["horizon"] else _last_int(row.get(role["setting"])),
                    metric=str(row.get(role["metric"]) if metric is None else metric) + suffix,
                    value=_float(row.get(value_field)),
                    lines=span,
                    where=where,
                ))  # fmt: skip
    for e, props in state.edges.items():
        if e.type == "FROM" and props.get("material_ref"):
            for locator in props.get("locators") or []:
                check_ref(f"{props['material_ref']}::{locator}", f"{e.src} FROM")

    objects = [
        (kind, i, str(n.props.get("name", "")))
        for i, n in nodes.items()
        for kind in ("Method", "Dataset", "Task", "Paper")
        if kind in n.labels
    ]
    return {
        "fidelity": fidelity(_unique(facts), material_root, aliases, config, k) | {"skipped_artifacts": skipped},
        "dangling": rate(bad, refs),
        "overwrites": a3_overwrites(history, since, until),
        "objects": {k: sum(1 for o in objects if o[0] == k) for k in ("Method", "Dataset", "Task", "Paper")},
        "_candidates": candidates(objects),
    }


def a3_overwrites(history: list[Any], since: str, until: str) -> dict[str, Any]:
    """创建者从全部历史中取（改写种子节点也算）；只计 ``since`` 之后的提交。"""
    creator: dict[str, str] = {}
    items = []
    counting = False
    for record in history:
        revisions = (record.meta or {}).get("revisions") or {}
        for change in record.changeset.nodes:
            if change.op == "create":
                creator[change.id] = record.author
                continue
            owner = creator.get(change.id)
            if owner is None or owner == record.author:
                continue
            if change.op == "delete":
                keys = ["(node deleted)"]
            else:
                before, after = change.before or {}, change.after or {}
                keys = [k for k in after if k not in DERIVED and before.get(k) is not None and before.get(k) != after[k]]
            if keys and counting:
                lost = [str((change.before or {}).get(k)) for k in keys if isinstance((change.before or {}).get(k), (int, float))]
                items.append({"commit": record.id, "node": change.id, "by": record.author, "owner": owner,
                              "kind": "value" if lost else "text", "fields": keys,
                              "reason": change.id in revisions, "judgment": None})  # fmt: skip
        if record.id == until:
            break
        counting = counting or record.id == since
    return _overwrite_summary(items) | {"without_reason": sum(not i["reason"] for i in items)}


def _overwrite_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "value": sum(i["kind"] == "value" for i in items),
        "text": sum(i["kind"] == "text" for i in items),
        "items": items,
    }


def _roles(fields: dict[str, Any]) -> dict[str, Any]:
    """Extract 的字段名由写者声明：按名字认出方法、数据集、预测长度、指标与数值列（宽表的 MSE、MAE 列也认；``std``
    列按所在行的指标记为 ``mse_std`` / ``mae_std``）。"""
    low = {f.lower(): f for f in fields}

    def pick(*names: str) -> str | None:
        return next((low[n] for n in names if n in low), None)

    values: list[tuple[str | None, str, str]] = []
    if (v := pick("value", "score")) is not None:
        values.append((None, v, ""))
    if (v := pick("std", "stderr", "std_dev")) is not None:
        values.append((None, v, "_std"))
    values += [(m.upper(), low[m], "") for m in ("mse", "mae") if m in low]
    return {
        "method": pick("method", "model", "baseline"),
        "dataset": pick("dataset", "data"),
        "horizon": pick("horizon", "pred_len", "prediction_length", "output_length", "t"),
        "metric": pick("metric"),
        "setting": pick("setting", "setting_id", "config", "configuration"),  # 没有预测长度字段时取其中最后一个整数
        "values": values,
    }


def _unique(facts: list[Fact]) -> list[Fact]:
    """同一行中重复出现的同一个数只计一次（schema 同时有 ``value`` + ``metric`` 列与 ``mse`` / ``mae`` 列时）。"""
    seen, out = set(), []
    for f in facts:
        key = (f.where, f.metric.lower(), f.value)
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


def _last_int(value: Any) -> int | None:
    """``ett-96-720`` 这类合写的设置（数据集-回看长度-预测长度）：最后一个整数是预测长度。"""
    found = re.findall(r"\d+", str(value)) if value is not None else []
    return int(found[-1]) if found else None


def _used_paper(art: str, state: Any, nodes: dict[str, Any]) -> str | None:
    for e in state.edges:
        if e.src == art and e.type == "USED" and "Paper" in nodes.get(e.dst, _EMPTY).labels:
            return _arxiv_of(nodes[e.dst].props)
    return None


def _paper_material(head: str, nodes: dict[str, Any], state: Any, materials: dict[str, Any]) -> dict[str, Any] | None:
    if head not in nodes or "Paper" not in nodes[head].labels:
        return None
    for e in state.edges:
        if e.type == "MATERIAL_OF" and e.dst == head and e.src in materials and not materials[e.src].get("superseded_by"):
            return materials[e.src]  # 论文当前的材料（新版本出现后，旧材料带 superseded_by）
    return None


def _arxiv_of(props: dict[str, Any]) -> str | None:
    ids = props.get("identifiers") or []
    ids = yaml.safe_load(ids) if isinstance(ids, str) else ids
    return next((i.split(":", 1)[1] for i in ids if str(i).startswith("arxiv:")), None)


class _Empty:
    labels: frozenset[str] = frozenset()


_EMPTY = _Empty()


# ---------------------------------------------------------------- A0


def a0_health(
    store: Path, tag: str, base: str, material_root: Path, config: dict[str, Any], k: int | None = None
) -> dict[str, Any]:
    aliases = paper_aliases(config, k)
    files = {p: _show(store, tag, p) for p in _ls(store, tag) if p.endswith(".md")}
    facts, refs, bad, skipped = [], 0, [], 0
    corpus = {p.name for p in (material_root / "papers").iterdir()}
    for path, text in sorted(files.items()):
        lines = text.splitlines()
        meta = _note_fields(lines)
        paper = _note_paper(meta) if path.startswith("papers/") else None
        material_lines = None
        if paper and paper in corpus:
            material_lines = (material_root / "papers" / paper / "paper.md").read_text(encoding="utf-8").count("\n") + 1
        for number, line in enumerate(lines, 1):
            for target in LINK.findall(line):
                if re.match(r"[a-z]+:", target) or target.startswith("#"):
                    continue
                refs += 1
                resolved = str(PurePosixPath(_normpath(PurePosixPath(path).parent / target.split("#")[0])))
                if resolved not in files and not _exists(store, tag, resolved):
                    bad.append({"where": f"{path}:{number}", "ref": target, "why": "no such file"})
            if material_lines is not None:
                for a, b in SECTION_LINES.findall(line):
                    refs += 1
                    if not 1 <= int(a) <= int(b) <= material_lines:
                        bad.append({"where": f"{path}:{number}", "ref": f"::{a}:{b}", "why": f"lines out of range (1-{material_lines})"})
        if path.startswith("papers/") and meta.get("material"):
            refs += 1
            arxiv = re.match(r"papers/([^/]+)/", meta["material"])
            if not arxiv or arxiv.group(1) not in corpus:
                bad.append({"where": path, "ref": meta["material"], "why": "no such material"})
        for start, table in source_tables.tables(lines):
            context = "\n".join(lines[max(0, start - 3) : start])
            paper_lines = None
            if paper and paper in corpus:
                paper_lines = (material_root / "papers" / paper / "paper.md").read_text(encoding="utf-8").splitlines()
            span = _cited_lines(lines, start, paper_lines)
            got = _note_facts(table, paper, span, f"{path}:{start + 1}", context) if paper else []
            if got:
                facts += got
            elif any(source_tables.FLOAT.search(r) for r in table):
                skipped += 1
    objects = []
    for path, text in files.items():
        kind = {"methods": "Method", "datasets": "Dataset", "tasks": "Task", "papers": "Paper"}.get(path.split("/")[0])
        if kind:
            title = next((line[2:].strip() for line in text.splitlines() if line.startswith("# ")), path)
            objects.append((kind, path, title.split(":")[0] if kind == "Paper" else title))
    return {
        "fidelity": fidelity(_unique(facts), material_root, aliases, config, k) | {"skipped_tables": skipped},
        "dangling": rate(bad, refs),
        "overwrites": a0_overwrites(store, base, tag),
        "objects": {k: sum(1 for o in objects if o[0] == k) for k in ("Method", "Dataset", "Task", "Paper")},
        "_candidates": candidates(objects),
    }


def a0_overwrites(store: Path, base: str, tag: str) -> dict[str, Any]:
    log = _git(store, "log", "--reverse", "--format=%H%x09%ae", f"{base}..{tag}").splitlines()
    items = []
    for entry in log:
        commit, author = entry.split("\t")
        diff = _git(store, "diff", "-U0", "--no-renames", f"{commit}^", commit)
        for path, removed in _removed_lines(diff).items():
            after = _show(store, commit, path) or ""
            present, kept = set(source_tables.FLOAT.findall(after)), set(after.splitlines())
            blame = _blame(store, f"{commit}^", path)
            for number, text in removed:
                owner = blame.get(number)
                if not text.strip() or text in kept or not owner or owner == author:
                    continue
                lost = [x for x in source_tables.FLOAT.findall(text) if x not in present]
                items.append({"commit": commit[:7], "file": path, "line": number, "by": author, "owner": owner,
                              "kind": "value" if lost else "text", "lost": lost[:6], "text": text[:160],
                              "judgment": None})  # fmt: skip
    return _overwrite_summary(items)


def _note_fields(lines: list[str]) -> dict[str, str]:
    out = {}
    for line in lines[:20]:
        m = re.match(r"- \*\*([a-z_ ]+):\*\*\s*(.*)", line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def _note_paper(meta: dict[str, str]) -> str | None:
    """论文笔记的 arXiv id（带版本号）：取 ``material:`` 的路径，没有时取 ``identifiers`` 与 ``version``。"""
    m = re.search(r"papers/(\d{4}\.\d{4,5}v\d+)/", meta.get("material", ""))
    if m:
        return m.group(1)
    m = re.search(r"arxiv:(\d{4}\.\d{4,5})", meta.get("identifiers", ""))
    v = re.search(r"v\d+", meta.get("version", ""))
    return m.group(1) + (v.group() if v else "") if m else None


def _cited_lines(lines: list[str], start: int, paper_lines: list[str] | None = None) -> tuple[int, int] | None:
    """表的出处行：表上方到最近的标题之间，``anchors`` 中给出的原文表 id（如 ``S4.T1``，按原文中的
    ``<a id="S4.T1">`` 取到表尾），否则第一处提到 table / source 的行中的 ``lines a-b`` 或 ``::a:b``。
    其余说明中的行号（如实现细节的出处）不算这张表的出处。"""
    top = next((i for i in range(start - 1, -1, -1) if lines[i].startswith("#")), -1)
    section = lines[max(top, 0) : start][::-1]  # 从表往上，含标题行
    for line in section:
        anchors = re.search(r"anchors?\W*:?\**\s*(.+)", line, flags=re.I)
        if anchors and paper_lines is not None:
            for table_id in re.findall(r"\b[A-Z]\d+\.T\d+\b", anchors.group(1)):
                span = _table_span(paper_lines, table_id)
                if span:
                    return span
    for line in section:
        m = NOTE_LINES.search(line) or SECTION_LINES.search(line)
        if m and re.search(r"table|source", line, flags=re.I):
            return int(m.group(1)), int(m.group(2))
    return None


def _table_span(paper_lines: list[str], table_id: str) -> tuple[int, int] | None:
    """原文中 id 为 ``table_id`` 的表：锚点行到表的最后一行（行号从 1 开始）。"""
    tag = f'id="{table_id}"'
    first = next((i for i, line in enumerate(paper_lines) if tag in line), None)
    if first is None:
        return None
    i = first + 1
    while i < len(paper_lines) and not paper_lines[i].startswith("|"):
        i += 1
    while i < len(paper_lines) and paper_lines[i].startswith("|"):
        i += 1
    return first + 1, i


def _note_facts(
    table: list[str], paper: str, span: tuple[int, int] | None, where: str, context: str = ""
) -> list[Fact]:
    """笔记中的结果表。认三种写法：``<方法> MSE`` 这样方法与指标合在表头；``value`` 列配方法、指标列；方法占列、
    一格写 ``MSE / MAE`` 两个数（顺序取表上方说明中的 ``MSE / MAE`` 或 ``MAE / MSE``）。"""
    rows = [source_tables.cells_of(r) for r in table if not set(r) <= set("|-: ")]
    if len(rows) < 2:
        return []
    head = [h.lower() for h in rows[0]]

    def col(*keys: str) -> int | None:
        return next((j for j, h in enumerate(head) if any(k == h or (len(k) > 2 and k in h) for k in keys)), None)

    c_data, c_meth, c_metric = col("dataset", "data"), col("method", "model"), col("metric")
    c_hor = col("horizon", "pred", "t", "o", "h", "output")
    values: list[tuple[int, str | None, str | None]] = []
    paired = [re.match(r"^(.*?)\s*\b(MSE|MAE)\s*/\s*(MSE|MAE)$", h.strip(), flags=re.I) for h in rows[0]]
    for j, h in enumerate(rows[0]):
        m = re.match(r"^(.*?)\s*\b(MSE|MAE)$", h.strip(), flags=re.I)
        if paired[j]:
            continue
        if m:
            values.append((j, m.group(1).strip() or None, m.group(2).upper()))
        elif h.lower() == "value":
            values.append((j, None, None))
    order = re.search(r"\b(MSE|MAE)\s*/\s*(MSE|MAE)\b", context + " " + " ".join(rows[0]), flags=re.I)
    if not values and order and c_data is not None and c_hor is not None:
        headers = [(m.group(1).strip() if m else h) for h, m in zip(rows[0], paired, strict=True)]
        std = "std" in context.lower() or "standard deviation" in context.lower()
        first, second = order.group(1).upper(), order.group(2).upper()
        out, dataset = [], ""
        for n, row in enumerate(rows[1:], 2):
            if len(row) < len(rows[0]):
                continue
            dataset = row[c_data] or dataset
            for j, method in enumerate(headers):
                if j in (c_data, c_hor) or not method:
                    continue
                pair = re.fullmatch(r"\**\s*(\d*\.\d+)\s*\**\s*/\s*\**\s*(\d*\.\d+)\s*\**", row[j])
                if not pair:
                    continue
                for metric, value in ((first, pair.group(1)), (second, pair.group(2))):
                    metric += "_std" if std else ""
                    out.append(Fact(paper, method, dataset, _int(row[c_hor]), metric, float(value), span, f"{where}+{n}"))
        return out
    if c_data is None or c_hor is None or not values:
        return []
    out, dataset = [], ""
    for n, row in enumerate(rows[1:], 2):
        if len(row) < len(rows[0]):
            continue
        dataset = row[c_data] or dataset
        horizon = _int(row[c_hor])
        for j, method, metric in values:
            value = source_tables.FLOAT.search(row[j])
            out.append(Fact(
                paper=paper,
                method=method or (row[c_meth] if c_meth is not None else "?"),
                dataset=dataset,
                horizon=horizon,
                metric=metric or (row[c_metric] if c_metric is not None else "?"),
                value=float(value.group()) if value else None,
                lines=span,
                where=f"{where}+{n}",
            ))  # fmt: skip
    return [f for f in out if f.value is not None]


def _removed_lines(diff: str) -> dict[str, list[tuple[int, str]]]:
    out: dict[str, list[tuple[int, str]]] = {}
    path, old = None, 0
    for line in diff.splitlines():
        if line.startswith("--- "):
            path = line[6:] if line.startswith("--- a/") else None
        elif line.startswith("@@"):
            old = int(re.match(r"@@ -(\d+)", line).group(1))
        elif line.startswith("-") and not line.startswith("---") and path:
            out.setdefault(path, []).append((old, line[1:]))
            old += 1
    return out


def _blame(store: Path, rev: str, path: str) -> dict[int, str]:
    out, current = {}, None
    text = _git(store, "blame", "--line-porcelain", rev, "--", path, check=False)
    for line in text.splitlines():
        m = re.match(r"^[0-9a-f]{40} \d+ (\d+)", line)
        if m:
            current = int(m.group(1))
        elif line.startswith("author-mail ") and current is not None:
            out[current] = line[len("author-mail ") :].strip("<>")
    return out


def _git(store: Path, *args: str, check: bool = True) -> str:
    done = subprocess.run(["git", "-C", str(store), *args], capture_output=True, text=True)
    if check and done.returncode != 0:
        raise RuntimeError(done.stderr)
    return done.stdout


def _ls(store: Path, tag: str) -> list[str]:
    return _git(store, "ls-tree", "-r", "--name-only", tag).splitlines()


def _show(store: Path, rev: str, path: str) -> str | None:
    done = subprocess.run(["git", "-C", str(store), "show", f"{rev}:{path}"], capture_output=True, text=True)
    return done.stdout if done.returncode == 0 else None


def _exists(store: Path, tag: str, path: str) -> bool:
    return subprocess.run(["git", "-C", str(store), "cat-file", "-e", f"{tag}:{path}"], capture_output=True).returncode == 0


def _normpath(path: PurePosixPath) -> str:
    parts: list[str] = []
    for p in path.parts:
        if p == "..":
            if parts:
                parts.pop()
        elif p != ".":
            parts.append(p)
    return "/".join(parts)


def _sha256(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def _int(x: Any) -> int | None:
    m = re.search(r"\d+", str(x)) if x is not None else None
    return int(m.group()) if m else None


def _float(x: Any) -> float | None:
    m = source_tables.FLOAT.search(str(x)) if x is not None else None
    return float(m.group()) if m else (float(x) if isinstance(x, int) else None)


# ---------------------------------------------------------------- 入口


def measure(run: Path, config: dict[str, Any], arm: str, k: int, *, at_head: bool = False) -> dict[str, Any]:
    """``at_head``：读库的当前状态而不是检查点（试跑用；A3 临时导出一份快照）。"""
    material_root = REPO / config["corpus"]["material_root"]
    checkpoints = yaml.safe_load((run / "checkpoints.yml").read_text(encoding="utf-8"))
    if arm == "A0":
        return a0_health(run / "A0/store", "HEAD" if at_head else f"checkpoint-{k}", "checkpoint-0", material_root, config, k)
    if not at_head:
        snap = snapshot.load(run / f"checkpoints/{k}/A3")
        return a3_measure(snap, checkpoints["A3"][0], checkpoints["A3"][k], run / "A3/data", material_root, config, k)
    with tempfile.TemporaryDirectory() as tmp:
        snapshot.export_a3(config["arms"]["A3"]["neo4j"], run / "A3/data", Path(tmp))
        snap = snapshot.load(Path(tmp))
        until = yaml.safe_load((Path(tmp) / "meta.yml").read_text(encoding="utf-8"))["branches"]["main"]
        return a3_measure(snap, checkpoints["A3"][0], until, run / "A3/data", material_root, config, k)


def a3_measure(
    snap: snapshot.Snapshot, since: str, until: str, data: Path, material_root: Path, config: dict[str, Any], k: int
) -> dict[str, Any]:
    """快照上的 A3 健康度：产物文档读快照中的副本，其余材料（论文）读 ``data``。"""
    assert snap.root is not None
    documents = snap.root / "documents"

    def locate(path: str) -> Path:
        copy = documents / path
        return copy if path.startswith("artifacts/") and copy.exists() else data / path

    return a3_health(_state(snap), _history(snap), since, until, locate, material_root, config, k)


# 快照读回成 a3_health 用的形状：节点（labels、props）、以 (src, type, dst) 为键的边、主分支上从早到晚的提交。


@dataclass(frozen=True)
class _Node:
    labels: frozenset[str]
    props: dict[str, Any]


@dataclass(frozen=True)
class _Edge:
    src: str
    type: str
    dst: str


@dataclass
class _State:
    nodes: dict[str, _Node] = field(default_factory=dict)
    edges: dict[_Edge, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class _Change:
    id: str
    op: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None


@dataclass(frozen=True)
class _Changeset:
    nodes: list[_Change]


@dataclass(frozen=True)
class _Record:
    id: str
    author: str
    meta: dict[str, Any]
    changeset: _Changeset


def _state(snap: snapshot.Snapshot) -> _State:
    state = _State()
    for ident, node in snap.nodes.items():
        state.nodes[ident] = _Node(frozenset(node["labels"]), {k: v for k, v in node["props"].items() if k != "id"})
    for src, rel, dst, props in snap.edges:
        state.edges[_Edge(src, rel, dst)] = props
    return state


def _history(snap: snapshot.Snapshot, branch: str = "main") -> list[_Record]:
    """提交的变更集按 graph-vc 写下的 JSON 读：create 有 ``after``，delete 有 ``before``，update 的 ``props`` 是
    ``{属性: {before, after}}``。"""
    out = []
    for c in sorted((c for c in snap.commits if c.get("branch", branch) == branch), key=lambda c: c["seq"]):
        changes = []
        for n in json.loads(c["changeset"]).get("nodes", []):
            if n["op"] == "update":
                diff = n.get("props") or {}
                before, after = {k: v["before"] for k, v in diff.items()}, {k: v["after"] for k, v in diff.items()}
            else:
                before, after = n.get("before"), n.get("after")
            changes.append(_Change(n["id"], n["op"], before, after))
        out.append(_Record(c["id"], c["author"], json.loads(c.get("meta") or "{}"), _Changeset(changes)))
    return out


_HEADER = re.compile(r"\A---\n(?P<header>.*?)\n---\n", re.DOTALL)
_FENCE = "```yaml\n"


def _header_of(text: str) -> dict[str, Any]:
    """产物文档的 YAML 头部（``---`` 之间）；没有时为空。"""
    match = _HEADER.match(text)
    header = yaml.safe_load(match["header"]) if match else None
    return header if isinstance(header, dict) else {}


def _data_of(text: str) -> Any:
    """产物文档正文末尾的数据块（最后一个 ```yaml 代码块）；没有时为 ``None``。"""
    start = text.rfind(_FENCE)
    end = text.find("```", start + len(_FENCE)) if start >= 0 else -1
    return yaml.safe_load(text[start + len(_FENCE) : end]) if end >= 0 else None


def write(run: Path, arm: str, k: int, result: dict[str, Any]) -> Path:
    out = run / "health"
    out.mkdir(exist_ok=True)
    found = result.pop("_candidates")
    path = out / f"{arm}-cp{k}-entities.yml"
    if path.exists():  # 保留已填的标注
        old = {json.dumps([m["id"] for m in c["members"]]): c["same"] for c in yaml.safe_load(path.read_text(encoding="utf-8")) or []}
        for c in found:
            c["same"] = old.get(json.dumps([m["id"] for m in c["members"]]), c["same"])
    path.write_text(yaml.safe_dump(found, sort_keys=False, allow_unicode=True, width=120), encoding="utf-8")
    result["duplicate_candidates"] = {"groups": len(found), "annotated": sum(c["same"] is not None for c in found),
                                      "file": path.name}  # fmt: skip
    target = out / f"{arm}-cp{k}.yml"
    target.write_text(yaml.safe_dump(result, sort_keys=False, allow_unicode=True, width=120), encoding="utf-8")
    return target


def summary(result: dict[str, Any]) -> str:
    f, d, o = result["fidelity"], result["dangling"], result["overwrites"]
    return (
        f"values {f['values']} supported {f['supported_rate']} {f['status']} anchor {f['anchor']} | "
        f"dangling {d['dangling']}/{d['references']} | overwrites value {o['value']} text {o['text']} | "
        f"objects {result['objects']} | "
        f"duplicate candidates {result['duplicate_candidates']['groups']}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pweval.health", description=__doc__.split("\n\n")[0])
    parser.add_argument("name")
    parser.add_argument("--config", default=str(REPO / "eval/config/pilot-ltsf.yml"))
    parser.add_argument("--arms", default="A3,A0")
    parser.add_argument("--checkpoint", type=int, required=True)
    parser.add_argument("--at-head", action="store_true", help="读库的当前状态而不是检查点（试跑用）")
    args = parser.parse_args(argv)
    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    run = Path(config["runner"]["workdir_root"]).expanduser() / args.name
    from .run import run_config

    config = run_config(run, config)
    for arm in args.arms.split(","):
        result = measure(run, config, arm, args.checkpoint, at_head=args.at_head)
        path = write(run, arm, args.checkpoint, result)
        print(f"[{arm} cp{args.checkpoint}] {summary(result)} -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
