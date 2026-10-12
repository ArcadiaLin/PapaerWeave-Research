"""原文结果表的索引：（论文, 数据集, 预测长度, 方法, 指标）→ 原文中的数值与行号。用于核对读者给出的数值（t1.grade）。

语料是 Markdown 化的论文，结果表是连续的 ``|`` 行：表头若干行（方法行、指标行 MSE/MAE），然后是数据行。解析规则：

- 指标行：表头中含 MSE 或 MAE 的一行；它决定哪些列是数值列。
- 方法行：指标行之上、离它最近、在数值列上有名字的一行；名字向右填满空单元格（一个方法占 MSE、MAE 两列）。
  没有单独的指标行时，认“方法 + 指标”合在一格的表头（``Informer<br>MSE``）。方法名去掉引文链接与 ``<br>``。
- 数据集名按 :data:`DATASETS` 归一；个别论文的表用自己的简称，按 :data:`PAPER_DATASETS` 换成通用名。
- 数据行：数据集取第一格，空则沿用上一行；预测长度取第二格的整数，或第一格中括号里的整数（``Electricity (96)``）。
- 指标格写作 ``MSE  MAE`` 时，一格中两个数依次是 MSE 与 MAE（Informer 表 1）。
- 单元格取第一个小数（``0.3752±0.0008`` 取 0.3752）；带 ± 的另记标准差，指标为 ``mse_std`` / ``mae_std``。

方法占行、预测长度占列的转置表（种子论文 Informer、SCINet 的主表）不解析；这些论文中没有建索引的数据集，核对时记为
unchecked（t1.grade.verify）。不是方法名的表头（例如按 look-back 分列的表）也照样建索引，只是方法名对不上，这些数值在核对中落到“原文同一行中有、
但不在所称的列”一类，由判分者复核。解析不了的表跳过，:func:`coverage` 报告每篇论文建了多少格。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

FLOAT = re.compile(r"(?<![\d.])\d*\.\d+")
METRICS = {"mse", "mae"}
COMBINED = re.compile(r"^(.*?)\s*\b(MSE|MAE)$", flags=re.I)
DATASETS = {"exchangerate": "exchange", "ecl": "electricity"}  # 规范化后的别名 → 通用名
PAPER_DATASETS = {"2106.13008v5": {"ett": "ettm2"}}  # Autoformer 表 1 的 ETT* 即 ETTm2（原文第 317 行的脚注）


@dataclass(frozen=True)
class Cell:
    arxiv: str
    dataset: str  # 规范化
    horizon: int
    method: str  # 规范化
    metric: str  # mse / mae
    value: float
    line: int  # 原文行号（从 1 开始）
    header: str  # 原样的方法名


def norm_dataset(text: str) -> str:
    name = re.sub(r"[^a-z0-9]", "", re.sub(r"<br\s*/?>", "", text.lower()))
    return DATASETS.get(name, name)


def norm_method(text: str) -> str:
    text = re.sub(r"\[\[[^\]]*\]\([^)]*\)\]|\[[^\]]*\]\([^)]*\)|<br\s*/?>", " ", text)  # 引文链接、换行
    text = re.sub(r"\$|\\[a-z]+|\^|[†∗*{}]", "", text.lower())
    return re.sub(r"\s+", "", text).strip("-_")


def _metric(cell: str) -> str:
    """指标格：``mse``、``mae``，或一格两个指标的 ``mse+mae``；不是指标格时为空。"""
    text = cell.strip().lower()
    if text in METRICS:
        return text
    return "mse+mae" if re.fullmatch(r"mse\s+mae", text) else ""


def _clean(header: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\[\[[^\]]*\]\([^)]*\)\]|<br\s*/?>", " ", header)).strip()


def same_method(claimed: str, column: str) -> bool:
    """PatchTST 与 PatchTST/64 视为同一方法（变体号可省）；名字带说明词或括注时也只比第一个词（表头
    ``PatchTST/42 supervised``、``CATS (2L)``，读者写的 ``PatchTST/64 (L=512)``）；其余要求规范化后相等
    （``Autoformer-CI`` 与 ``Autoformer`` 不同）。写者常用的简称（``fed``）按前缀认。"""

    def forms(name: str) -> set[str]:
        words = name.split()
        out = {f for f in (norm_method(name), norm_method(words[0]) if words else "") if f}
        return out | {re.sub(r"^[a-z]+=", "", f) for f in out}  # 消融变体：``K=16`` 即表头 ``16``

    def same(a: str, b: str) -> bool:  # 简称：至少 3 个字符的前缀（``fed`` 即 FEDformer）
        return a == b or b.startswith(a + "/") or a.startswith(b + "/") or (len(a) >= 3 and b.startswith(a) and len(b) > len(a) and b[len(a)].isalpha())

    return any(same(a, b) for a in forms(claimed) for b in forms(column))


def cells_of(row: str) -> list[str]:
    return [c.strip() for c in row.strip().strip("|").split("|")]


def tables(lines: list[str]) -> list[tuple[int, list[str]]]:
    out, start = [], None
    for i, line in enumerate([*lines, ""]):
        if line.startswith("|") and start is None:
            start = i
        elif not line.startswith("|") and start is not None:
            out.append((start, lines[start:i]))
            start = None
    return out


def parse(arxiv: str, lines: list[str]) -> list[Cell]:
    cells: list[Cell] = []
    for start, rows in tables(lines):
        parsed = [(start + n + 1, cells_of(r)) for n, r in enumerate(rows) if not set(r) <= set("|-: ")]
        header = []
        for number, row in parsed:
            if any(FLOAT.search(c) for c in row[1:]):
                break
            header.append(row)
        metric_rows = [r for r in header if any(_metric(c) for c in r)]
        if metric_rows:
            metric = [_metric(c) for c in metric_rows[-1]]
            cols = [j for j, c in enumerate(metric) if c]
            above = header[: header.index(metric_rows[-1])]
            named = [r for r in above if any(j < len(r) and r[j] for j in cols)]
            if not named:
                continue
            names, current = [], ""
            for c in named[-1]:
                current = _clean(c) or current
                names.append(current)
        elif header:  # 方法与指标合在一格
            combined = [COMBINED.match(_clean(c)) for c in header[-1]]
            cols = [j for j, m in enumerate(combined) if m and m.group(1)]
            if not cols:
                continue
            names = [m.group(1) if m else "" for m in combined]
            metric = [m.group(2).lower() if m else "" for m in combined]
        else:
            continue
        dataset = ""
        for number, row in parsed[len(header) :]:
            first = row[0] if row else ""
            inline = re.search(r"\((\d+)\)\s*$", first)
            if first:
                dataset = norm_dataset(re.sub(r"\(\d+\)\s*$", "", first))
                dataset = PAPER_DATASETS.get(arxiv, {}).get(dataset, dataset)
            if inline:
                horizon = int(inline.group(1))
            elif len(row) > 1 and row[1].isdigit():
                horizon = int(row[1])
            else:
                continue
            for j in cols:
                if j >= len(row) or j >= len(names) or not names[j]:
                    continue
                found = FLOAT.findall(row[j])
                if not found:
                    continue
                method = norm_method(names[j])
                if metric[j] == "mse+mae":
                    for m, v in zip(("mse", "mae"), found, strict=False):
                        cells.append(Cell(arxiv, dataset, horizon, method, m, float(v), number, names[j]))
                    continue
                cells.append(Cell(arxiv, dataset, horizon, method, metric[j], float(found[0]), number, names[j]))
                if len(found) > 1 and re.search(r"±|\\pm", row[j]):
                    cells.append(Cell(arxiv, dataset, horizon, method, f"{metric[j]}_std", float(found[1]), number, names[j]))
    return cells


@cache
def index(material_root: Path) -> tuple[Cell, ...]:
    out: list[Cell] = []
    for paper in sorted((material_root / "papers").iterdir()):
        source = paper / "paper.md"
        if source.exists():
            out += parse(paper.name, source.read_text(encoding="utf-8").splitlines())
    return tuple(out)


def coverage(material_root: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for cell in index(material_root):
        counts[cell.arxiv] = counts.get(cell.arxiv, 0) + 1
    return counts


def lookup(material_root: Path, arxiv: str, dataset: str, horizon: int, metric: str) -> list[Cell]:
    """论文 ``arxiv``（版本号可省）中该数据集、预测长度与指标的全部格子。"""
    d, m = norm_dataset(dataset), metric.lower()
    return [
        c
        for c in index(material_root)
        if (c.arxiv == arxiv or c.arxiv.rsplit("v", 1)[0] == arxiv) and c.dataset == d and c.horizon == horizon and c.metric == m
    ]


def dataset_in(material_root: Path, arxiv: str, text: str) -> str:
    """读者或写者写的数据集名在论文 ``arxiv`` 中对应的（规范化）名字：依次试整个名字、去掉括注后的名字、括注中的
    名字，按这篇论文自己的叫法换算（:data:`PAPER_DATASETS`）；都不在这篇论文的索引中时返回整个名字的规范化形式。"""
    inner = re.findall(r"\(([^)]*)\)", text)
    candidates = [text, re.sub(r"\([^)]*\)", "", text), *inner]
    known = datasets_of(material_root, arxiv)
    mapped = [PAPER_DATASETS.get(arxiv, {}).get(norm_dataset(c), norm_dataset(c)) for c in candidates if c.strip()]
    return next((d for d in mapped if d in known), norm_dataset(text))


def datasets_of(material_root: Path, arxiv: str) -> set[str]:
    """论文 ``arxiv`` 的索引中出现过的数据集（规范化）。"""
    return {c.dataset for c in index(material_root) if c.arxiv == arxiv}
