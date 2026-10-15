"""读者探针的数据（``config/probes-ltsf.yml``）：读取、有效范围与检查点时的金标准，以及金标准与原文的核对。
运行框架（:mod:`pweval.harness.readers` 让读者作答）与测量层（:mod:`pweval.measure.grade` 判分）共用。

探针在其金标准涉及的论文中最早的一篇写入后的检查点起有效（:func:`eligible`）；多篇论文的金标准只计入检查点时
已写入的论文（:func:`gold_at`）。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from ..paths import REPO
from . import source_tables, versions

PROBES = REPO / "eval/config/probes-ltsf.yml"
CONDITIONS = ("store_only", "with_papers")


def load(path: Path = PROBES) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def for_run(config: dict[str, Any], repo: Path) -> dict[str, Any] | None:
    """这次运行的探针：配置的 ``probes`` 文件去掉 ``probes_exclude`` 中的 id（例如不注入版本事件的运行去掉 G 类）。"""
    if not config.get("probes"):
        return None
    probes = load(repo / config["probes"])
    exclude = set(config.get("probes_exclude") or [])
    if unknown := exclude - {p["id"] for p in probes["probes"]}:
        raise ValueError(f"probes_exclude names unknown probes: {sorted(unknown)}")
    return {**probes, "probes": [p for p in probes["probes"] if p["id"] not in exclude]}


# ---------------------------------------------------------------- 有效范围与金标准


def _paper_of(item: dict[str, Any]) -> str:
    return item.get("paper") or item["anchor"].split(":", 1)[0]


def _items(probe: dict[str, Any]) -> list[dict[str, Any]]:
    gold = probe["gold"]
    return [*gold.get("values", []), *gold.get("rubric", [])]


def paper_index(config: dict[str, Any]) -> dict[str, int]:
    """写入论文的顺序（从 1 开始）；种子论文为 0，检查点 0 起就在库中。"""
    index = {p["arxiv"]: 0 for p in config["corpus"]["seeds"]}
    index |= {p["arxiv"]: n for n, p in enumerate(config["corpus"]["papers"], 1)}
    return index | {old: index[new] for new, old in versions.first_versions(config).items()}  # 早期版本同序


def start(probe: dict[str, Any], config: dict[str, Any]) -> int:
    """探针有效的第一个检查点。"""
    if "start" in probe:
        return probe["start"]
    every = config["schedule"]["checkpoint_every_papers"]
    first = min(paper_index(config)[_paper_of(i)] for i in _items(probe))
    return max(1, -(-first // every))


def eligible(probes: list[dict[str, Any]], config: dict[str, Any], k: int) -> list[dict[str, Any]]:
    return [p for p in probes if start(p, config) <= k]


def gold_at(probe: dict[str, Any], config: dict[str, Any], k: int) -> dict[str, Any]:
    """检查点 ``k`` 时的金标准：只保留出处论文已写入的项，以及检查点在其 ``from_checkpoint`` /
    ``until_checkpoint`` 之内的项（论文新版本改动的数值：事件之前是旧值，之后是新值，
    :mod:`pweval.protocol.versions`）。"""
    written = k * config["schedule"]["checkpoint_every_papers"]
    index = paper_index(config)
    gold = dict(probe["gold"])
    for key in ("values", "rubric"):
        if key in gold:
            gold[key] = [
                i
                for i in gold[key]
                if index[_paper_of(i)] <= written
                and i.get("from_checkpoint", 0) <= k <= i.get("until_checkpoint", k)
            ]
    return gold


def check_anchors(probes: dict[str, Any], material_root: Path) -> list[str]:
    """金标准的锚点都在原文中，且每个数值出现在它的锚点行上；带方法与指标的数值确实是锚点行上那一列（按
    :mod:`pweval.protocol.source_tables` 解析的结果表）；神谕的行范围都存在。"""
    problems: list[str] = []

    def lines(arxiv: str) -> list[str]:
        return (material_root / "papers" / arxiv / "paper.md").read_text(encoding="utf-8").splitlines()

    for probe in probes["probes"]:
        for item in _items(probe):
            arxiv, line = item["anchor"].split(":")
            text = lines(arxiv)
            if not 1 <= int(line) <= len(text):
                problems.append(f"{probe['id']}: {item['anchor']} is out of range")
            elif "value" in item:
                numbers = [float(x) for x in re.findall(r"\d+\.\d+", text[int(line) - 1])]
                if not any(abs(x - item["value"]) < 1e-9 for x in numbers):
                    problems.append(f"{probe['id']}: {item['value']} is not on {item['anchor']}")
                elif "method" in item:
                    cells = source_tables.lookup(material_root, arxiv, item["dataset"], item["horizon"], item["metric"])
                    if not any(
                        c.line == int(line) and abs(c.value - item["value"]) < 1e-9 and source_tables.same_method(item["method"], c.header)
                        for c in cells
                    ):
                        problems.append(f"{probe['id']}: {item['method']} {item['metric']} {item['value']} is not that cell of {item['anchor']}")
        for span in probe.get("oracle", []):
            arxiv, lines_ = span.split(":")
            first, last = map(int, lines_.split("-"))
            if not 1 <= first <= last <= len(lines(arxiv)):
                problems.append(f"{probe['id']}: oracle {span} is out of range")
    return problems


def condition_of(record: dict[str, Any]) -> str:
    """早先的记录没有条件字段：它们是能读论文的读者，或参照线。"""
    if "condition" in record:
        return record["condition"]
    return "none" if record["arm"] in ("closed_book", "oracle") else "with_papers"


__all__ = [
    "CONDITIONS",
    "PROBES",
    "check_anchors",
    "condition_of",
    "eligible",
    "for_run",
    "gold_at",
    "load",
    "paper_index",
    "start",
]
