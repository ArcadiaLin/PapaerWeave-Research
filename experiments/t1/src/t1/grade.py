"""探针判分：数值按规则自动判，要点（rubric）留给判分者填写。

    python -m t1.grade <运行名> [--config …]     # 写出 <运行目录>/grades.yml

- **数值清单**：读者在回答末尾按固定格式列出报告的每个数值（``claims`` 块：论文 | 方法 | 数据集 | 预测长度 | 指标 |
  数值）。判分只认这个清单，不从正文中找数。
- **召回**：金标准中带方法与指标的数值（检查点时已写入的论文，:func:`t1.probe.gold_at`）成对判：清单中有一条的出处
  论文、方法、数据集、预测长度、指标与数值都对上才算命中。数值按相等比较（0.37 与 0.370 相同）。不带方法的金标准
  数值（消融变体、标准误）只看数值是否出现在回答中。
- **精确率**：清单中每一条对照原文结果表（:mod:`t1.source_tables`）核对，分为 ``supported``（所称论文的表中，该方法、
  数据集、预测长度与指标的格子就是这个数）、``misattributed``（所称论文同一数据集与预测长度的行中有这个数，但不在
  所称的方法或指标下）、``unsupported``（所称论文的这些行中没有这个数）、``unknown_paper``（论文认不出）。精确率是
  ``supported`` 的比例，``unchecked``（所称论文的索引中没有这个数据集，例如转置的表）不计入。论文有多个版本时
  （:mod:`t1.versions`），只写简称或不带版本号的 id 按检查点时的当前版本核对；所称版本中没有、同一论文的另一版本
  中有这个格子，记为 ``outdated``（计入精确率的分母，不算对）。开放的问题（C1 等）里，读者列出金标准以外、但原文确实报告的数值，不算错。
- **要点**：``pass`` 留空，由判分者填 ``true`` / ``false``；已填的在重新生成时保留。E2 这类动态金标准的探针没有
  预设要点，判分者按检查点时库中的内容填写 ``dynamic``。
- 每条另带读者轨迹的统计（工具调用次数、直接读论文的次数），供逐题归因（evaluation_draft.md §4.3）。
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml
from e09.config import REPO

from . import source_tables, versions
from .probe import PROBES, condition_of, gold_at, load


def numbers_in(text: str) -> list[float]:
    return [float(x) for x in re.findall(r"(?<![\d.])\d*\.\d+", text)]


def claims_in(answer: str) -> list[dict[str, Any]] | None:
    """回答末尾 ``claims`` 块中的各条；没有这个块时为 None（与“块中写了 none”区分）。"""
    blocks = re.findall(r"```claims\s*\n(.*?)```", answer, flags=re.S)
    if not blocks:
        return None
    out = []
    for line in blocks[-1].splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 6 or cells[0].lower() == "paper":
            continue
        horizon = re.search(r"\d+", cells[3])
        value = numbers_in(cells[5])
        metric = re.search(r"\b(mse|mae)\b", cells[4].lower())
        std = "_std" if re.search(r"\bstd\b|standard", cells[4].lower()) else ""
        out.append({
            "paper": cells[0], "method": cells[1], "dataset": cells[2],
            "horizon": int(horizon.group()) if horizon else None,
            "metric": metric.group(1) + std if metric else cells[4].lower(),
            "value": value[0] if value else None,
        })  # fmt: skip
    return out


def paper_aliases(config: dict[str, Any], k: int | None = None) -> dict[str, str]:
    """读者可能写的论文名（arXiv id，带或不带版本号；简称）→ 语料中的 arXiv id。带版本号的 id 指那个版本；
    简称与不带版本号的 id 指检查点 ``k`` 时的当前版本（``None``：时间线结束时）。"""
    out = {}
    for p in [*config["corpus"]["seeds"], *config["corpus"]["papers"]]:
        current = versions.version_at(config, p["arxiv"], k)
        for name in (p["arxiv"].rsplit("v", 1)[0], p.get("short", "")):
            if name:
                out[_key(name)] = current
        for version in (p["arxiv"], p.get("first_version")):
            if version:
                out[_key(version)] = version
    return out


def paper_of(name: str, aliases: dict[str, str]) -> str | None:
    """论文名 → 语料中的 arXiv id。依次试整个名字、其中的 arXiv id、去掉括注后的名字、括注中的名字
    （读者写 ``2106.13008 (Autoformer)``、``SCINet (paper_0002)``）。A0 笔记的文件名把 id 写成
    ``patchtst-2211-14730``，其中的 ``2211-14730`` 也认作 arXiv id。"""
    tries = [name]
    tries += [m.group(0) for m in re.finditer(r"\d{4}\.\d{4,5}(?:v\d+)?", name)]
    tries += [f"{a}.{b}" for a, b in re.findall(r"(?<!\d)(\d{4})-(\d{4,5})(?![\d.])", name)]
    tries += [re.sub(r"\([^)]*\)", "", name), *re.findall(r"\(([^)]*)\)", name)]
    return next((aliases[_key(t)] for t in tries if t.strip() and _key(t) in aliases), None)


def _key(name: str) -> str:
    """规范化的论文名：去掉 ``arXiv:`` 前缀与空白，以及库中论文键的年份前缀（``2021-Autoformer``）。"""
    return re.sub(r"^arxiv:?|^\d{4}-|\s+", "", name.strip().lower())


def verify(
    claim: dict[str, Any], material_root: Path, aliases: dict[str, str], others: dict[str, list[str]] | None = None
) -> str:
    """``others``：版本 → 同一论文的其他版本（:func:`t1.versions.siblings`），用于认出 ``outdated``。"""
    arxiv = paper_of(claim["paper"], aliases)
    if arxiv is None:
        return "unknown_paper"
    status = _verify_in(claim, material_root, arxiv)
    if status in ("misattributed", "unsupported") and any(
        _verify_in(claim, material_root, other) == "supported" for other in (others or {}).get(arxiv, [])
    ):
        return "outdated"
    return status


def _verify_in(claim: dict[str, Any], material_root: Path, arxiv: str) -> str:
    if claim["value"] is None or claim["horizon"] is None:
        return "unsupported"
    dataset = source_tables.dataset_in(material_root, arxiv, claim["dataset"])
    if dataset not in source_tables.datasets_of(material_root, arxiv):
        return "unchecked"  # 这篇论文的这个数据集没有建索引（如转置表），核对不了
    row = [
        c
        for m in {"mse", "mae", claim["metric"]}
        for c in source_tables.lookup(material_root, arxiv, dataset, claim["horizon"], m)
    ]
    same = [c for c in row if abs(c.value - claim["value"]) < 1e-9]
    if any(c.metric == claim["metric"] and source_tables.same_method(claim["method"], c.header) for c in same):
        return "supported"
    return "misattributed" if same else "unsupported"


def grade(record: dict[str, Any], probe: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """一条回答的判分。参照线（闭卷、神谕）用完整的金标准。"""
    k = record["checkpoint"] or len(config["corpus"]["papers"]) // config["schedule"]["checkpoint_every_papers"]
    gold = gold_at(probe, config, k)
    material = REPO / config["corpus"]["material_root"]
    aliases = paper_aliases(config, k)
    claims = claims_in(record["answer"])
    for claim in claims or []:
        claim["status"] = verify(claim, material, aliases, versions.siblings(config))
    found = numbers_in(record["answer"])
    values = []
    for v in gold.get("values", []):
        if "method" in v:
            hit = any(
                paper_of(c["paper"], aliases) == v["paper"]
                and c["value"] is not None
                and abs(c["value"] - v["value"]) < 1e-9
                and c["metric"] == v["metric"].lower()
                and c["horizon"] == v["horizon"]
                and source_tables.dataset_in(material, v["paper"], c["dataset"]) == source_tables.norm_dataset(v["dataset"])
                and source_tables.same_method(c["method"], v["method"])
                for c in claims or []
            )
            what = f"{v['paper']} {v['method']} {v['dataset']}-{v['horizon']} {v['metric']}"
            values.append({"what": what, "value": v["value"], "mode": "pair", "hit": hit})
        else:
            hit = any(abs(x - v["value"]) < 1e-9 for x in found)
            values.append({"what": v["what"], "value": v["value"], "mode": "number", "hit": hit})
    supported = [c for c in claims or [] if c["status"] == "supported"]
    checked = [c for c in claims or [] if c["status"] != "unchecked"]
    out: dict[str, Any] = {
        "arm": record["arm"],
        "condition": condition_of(record),
        "checkpoint": record["checkpoint"],
        "probe": record["probe"],
        "values": values,
        "value_recall": round(sum(v["hit"] for v in values) / len(values), 3) if values else None,
        "claims": claims,
        "claim_precision": round(len(supported) / len(checked), 3) if checked else None,
        "rubric": [{"point": r["point"], "pass": None} for r in gold.get("rubric", [])],
        "audit": record.get("audit"),
        "exit": record.get("exit"),
        "answer": record["answer"],
    }
    if "dynamic" in gold:
        out["dynamic"] = {"gold": gold["dynamic"].strip(), "recorded": None, "recalled": None, "with_basis": None}
    if gold.get("reuse"):
        out["reuse"] = None  # 判分者填：读者是否引用了库中已有的记录或产物
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m t1.grade", description=__doc__.split("\n\n")[0])
    parser.add_argument("name")
    parser.add_argument("--config", default=str(REPO / "experiments/t1/config/pilot-ltsf.yml"))
    parser.add_argument("--probes-file", default=str(PROBES))
    args = parser.parse_args(argv)
    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    probes = {p["id"]: p for p in load(Path(args.probes_file))["probes"]}
    run = Path(config["runner"]["workdir_root"]).expanduser() / args.name
    from .run import run_config

    config = run_config(run, config)
    path = run / "grades.yml"
    previous = {}
    if path.exists():  # 保留已填的判分
        for g in yaml.safe_load(path.read_text(encoding="utf-8")) or []:
            previous[(g["arm"], g.get("condition", condition_of(g)), g["checkpoint"], g["probe"])] = g
    grades = []
    for line in (run / "probes.jsonl").read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        g = grade(record, probes[record["probe"]], config)
        old = previous.get((g["arm"], g["condition"], g["checkpoint"], g["probe"]))
        if old:
            for r, o in zip(g["rubric"], old.get("rubric", []), strict=False):
                if r["point"] == o["point"]:
                    r["pass"] = o["pass"]
            for key in ("dynamic", "reuse", "note"):
                if key in old:
                    g[key] = old[key]
        grades.append(g)
    path.write_text(yaml.safe_dump(grades, sort_keys=False, allow_unicode=True, width=120), encoding="utf-8")
    print(f"{len(grades)} answers graded -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
