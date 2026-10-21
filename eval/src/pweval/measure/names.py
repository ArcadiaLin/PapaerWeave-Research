"""判分时把回答中的方法名与论文指称归一（docs/designs/v3/evaluation.md §5.4；tmps/probes/grading-plan.md 第 3 节）。

依据题库的 ``facts/``：

- **方法**：``facts/methods.yml`` 的列名 → 规范方法名（变体归入原方法，``not-method`` 的列排除），加上 ``facts/aliases.yml``
  中方法的别名。比较时忽略大小写、空格、连字符与 ``†``、``*`` 一类记号，去掉 ``(Ours)``、``(2024)``、``/64`` 一类后缀；
  仍认不出时再去掉括号里的内容试一次。
- **论文**：arXiv 编号（带不带版本号都可以；不带时取检查点上库中的最新版本，带了就按所写版本），``facts/aliases.yml``
  中的完整标题、冒号前的部分、简称，以及“所提方法”（``proposes``，例如回答把论文写成 “PatchTST”）。语料以外的 arXiv
  编号记为 ``outside:<编号>``。

认不出的名称返回 ``None``，交给判分子代理对照语料清单判定（判定结果存在 ``grades/names.jsonl``，按名称字符串复用）。
"""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

NOT_METHOD = "not-method"
OUTSIDE = "outside:"
ARXIV = re.compile(r"(?<![\d.])(\d{4}\.\d{4,5})(v\d+)?(?![\d])")
_MARKS = re.compile(r"[\^†‡∗*$§]")
_SUFFIX = re.compile(r"\s*\((?:ours|\d{4})\)\s*$", re.I)
_PAREN = re.compile(r"\s*[(\[][^()\[\]]*[)\]]")


def key(name: str) -> str:
    """比较用的键：小写，去掉记号与后缀，只留字母、数字与 ``+``。"""
    text = _MARKS.sub("", name.strip().strip("`\"'"))
    text = _SUFFIX.sub("", text)
    text = re.sub(r"/\d+\s*$", "", text)  # PatchTST/64 → PatchTST（methods.yml 中登记过的按登记处理）
    return re.sub(r"[^a-z0-9+]", "", text.lower())


def _paper_key(name: str) -> str:
    text = re.sub(r"^(?:the\s+)", "", name.strip().strip("`\"'*"), flags=re.I)
    text = re.sub(r"\s+(?:paper|et al\.?)$", "", text, flags=re.I)
    return key(text)


@dataclass
class Names:
    methods: dict[str, str]  # 键 → 规范方法名（或 NOT_METHOD）
    by_table: dict[tuple[str, str], str]  # （表，列名）→ 规范方法名：同一写法在不同表中所指不同（methods.yml 的“表号|表头”键）
    papers: dict[str, str]  # 键 → arXiv 编号（不带版本）
    present: dict[str, str]  # 检查点上库中的最新版本：编号 → 带版本的编号
    judged: dict[tuple[str, str], str | None] = field(default_factory=dict)  # 子代理的判定：（种类, 原文）→ 结果

    def method(self, name: str, table: str | None = None) -> str | None:
        """规范方法名；不是方法的列为 ``NOT_METHOD``；认不出为 ``None``。"""
        if table and (hit := self.by_table.get((table, name.strip()))):
            return hit
        for candidate in (name, _PAREN.sub("", name)):
            if (k := key(candidate)) and k in self.methods:
                return self.methods[k]
        return self.judged.get(("method", name.strip()))

    def paper(self, name: str) -> str | None:
        """带版本的 arXiv 编号；语料以外的为 ``outside:<编号>``；认不出为 ``None``。"""
        text = name.strip()
        if m := ARXIV.search(text):
            base, version = m[1], m[2]
            if base not in {b for b in self.papers.values()}:
                return OUTSIDE + base
            return base + version if version else self.present.get(base, base)
        for candidate in (text, _PAREN.sub("", text), text.split(":")[0]):
            if (k := _paper_key(candidate)) and k in self.papers:
                base = self.papers[k]
                return self.present.get(base, base)
        judged = self.judged.get(("paper", text))
        if judged and not judged.startswith(OUTSIDE) and "v" not in judged:
            return self.present.get(judged, judged)
        return judged


def load(probes_repo: Path, present: set[str]) -> Names:
    """读题库的方法表与论文指称；``present`` 是检查点上库中的论文版本（:func:`pweval.harness.timeline.papers_at`）。"""
    facts = probes_repo / "facts"
    methods: dict[str, str] = {}
    by_table: dict[tuple[str, str], str] = {}
    columns = yaml.safe_load((facts / "methods.yml").read_text(encoding="utf-8"))["columns"]
    canonical = {v["method"] for v in columns.values() if "method" in v}
    for name in canonical:
        methods[key(name)] = name
    aliases = yaml.safe_load((facts / "aliases.yml").read_text(encoding="utf-8"))
    for name, alts in (aliases.get("methods") or {}).items():
        methods.setdefault(key(name), name)
        for alt in alts:
            methods.setdefault(key(alt["name"]), name)
    for column, entry in columns.items():
        target = entry.get("method", NOT_METHOD)
        if "|" in column:
            table, header = column.split("|", 1)
            by_table[(table, header)] = target
        else:
            methods.setdefault(key(column), target)
    papers: dict[str, str] = {}
    for base, entry in aliases["papers"].items():
        names = [entry["title"], entry["title"].split(":")[0], *entry.get("short", []), entry.get("proposes", "")]
        for name in names:
            if name:
                papers.setdefault(_paper_key(name), str(base))
    latest: dict[str, str] = {}
    for version in sorted(present, key=_version_order):
        latest[version.split("v")[0]] = version
    return Names(methods, by_table, papers, latest)


def _version_order(paper: str) -> tuple[str, int]:
    base, _, v = paper.partition("v")
    return base, int(v or 0)


def load_judged(path: Path) -> dict[tuple[str, str], str | None]:
    """``grades/names.jsonl``：每行 ``{"kind": "method"|"paper", "name": 原文, "resolved": 结果或 null}``，后写的覆盖先写的。"""
    out: dict[tuple[str, str], str | None] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                out[(row["kind"], row["name"].strip())] = row["resolved"]
    return out


@dataclass
class Tables:
    """原文结果表（``facts/tables.csv``、``cells.csv``）：表号与行号定位，以及“某表中是否有这个数”。"""

    numbered: dict[tuple[str, int], list[dict[str, Any]]]  # （论文版本, 表号）→ 表（同号可能有多张，例如正文与附录）
    rows: dict[str, list[dict[str, Any]]]  # 论文版本 → 表（含行号范围）
    cells: dict[str, list[dict[str, Any]]]  # 表 → 格子

    def by_line(self, paper: str, line: int) -> list[str]:
        return [t["table"] for t in self.rows.get(paper, []) if int(t["first"]) <= line <= int(t["last"])]


def load_tables(probes_repo: Path) -> Tables:
    facts = probes_repo / "facts"
    numbered: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with (facts / "tables.csv").open(encoding="utf-8") as f:
        for t in csv.DictReader(f):
            rows[t["arxiv"]].append(t)
            if t["number"].strip().isdigit():
                numbered[(t["arxiv"], int(t["number"]))].append(t)
    cells: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with (facts / "cells.csv").open(encoding="utf-8") as f:
        for c in csv.DictReader(f):
            cells[c["table"]].append(c)
    return Tables(dict(numbered), dict(rows), dict(cells))


__all__ = ["NOT_METHOD", "OUTSIDE", "Names", "Tables", "key", "load", "load_judged", "load_tables"]
