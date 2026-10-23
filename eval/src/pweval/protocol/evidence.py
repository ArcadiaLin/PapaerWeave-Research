"""逐题的依据材料：D 段落组的作答材料与判分包中的判题证据（docs/designs/v3/evaluation.md §10.1、§5.4）。

    python -m pweval.protocol.evidence --out <空目录> [--ids <题号,…>] [--tokenizer <推理服务地址>]

只读冻结的题库（``~/pw-lab/probes``）、论文（``~/pw-lab/data/formal/papers``）与代码快照，不调用模型（``--tokenizer``
只调用推理服务的分词接口数 token），不改题库。同样的输入得到逐字节相同的输出。

**依据**（§10.1，2026-10-21 确认）：

- 锚点：题的 ``evidence``、``refs``（题面所指论文的描述原文），金标准中要点、条目与 T3 排名的锚点；T1 加上金标准的位置；
  T3 加上各候选方法输入长度的依据（``facts/own.yml``，含代码）。``gold.notes`` 是判分背景，只进判分包。
- 展开：整张表（落在表内的行扩展为整表，起止行见 ``facts/tables.csv``）、整段（上下取到空行）；代码前后各补 8 行。
  同一来源的区间合并、去重，按来源与行号排序；每行带原文行号。
- **题目定义的结果范围，封闭世界：** 题面把“一篇论文的结果”定义为它主基准的多变量结果表（含附录中的完整结果表）。
  跨论文的集合题（自动题 T5–T8）补上库中每篇论文（各取最新版本）的这些表（题库 ``facts/papers/*.yml`` 中 ``role``
  以 ``main`` 开头、``variate`` 为 ``multivariate`` 的表），“出现”与“没有出现”都能在材料内判断。不补全文：原文中
  “没有说”的声明（来源、代码链接）由 D 的说明句写明封闭世界（:mod:`pweval.harness.refs`）。
- **D 材料中的表按题目切行**（2026-10-21 确认）：题目指定了数据集（``D`` 槽位）时，表只留表头、分隔行与该数据集的行
  （各预测长度都留）；T6 不指定数据集、只问哪些方法出现，补上的表只留表头（方法在行上的转置表留全表）。行属于哪个
  数据集按 ``facts/cells.csv`` 判；数据集名先归一，一行中的数据集都认得、又都不是题目所问的，才删去，认不出的行保留。
  切掉的行在材料中标出。判分包不切。
- 材料开头列出库中的论文（标题、所用版本、首个 arXiv 版本的日期），供按日期筛选的题使用。

**两种材料：**

- :func:`reader_material`（D 作答，英文）：论文清单与依据段落；没有参考答案、评分规则，也不说明题面所指的是哪篇论文。
- :func:`judge_material`（判分包，中文标题）：同一依据，加上“题面所指的论文”说明、只供判分的背景段落（``gold.notes``
  等的锚点；T1 与 T8 加上所涉论文的全部结果表，用来核对另一处位置或另一组实验）、参考答案与评分规则。不含封闭世界
  补上的全部主结果表（判分以参考答案为准，原文只用来核对）。待评回答与输出格式由判分包的生成器加上。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

PAPER = re.compile(r"(\d{4}\.\d{4,5}v\d+):(T?)(\d+)(?:-(\d+))?")
CODE = re.compile(r"([\w.-]+)@([0-9a-f]{7,40}):([^\s:;]+):(\d+)(?:-(\d+))?")
ANCHOR = re.compile(f"{CODE.pattern}|{PAPER.pattern}")
CODE_CONTEXT = 8  # 代码锚点前后各补的行数
SCOPED = ("T5", "T6", "T7", "T8")  # 跨论文的集合题：补上库中全部论文的主结果表（自动题）
EXCLUDED_TABLES = {"2205.08897v4:T1067"}  # 与 FiLM 表 1 重复的附录表，出题时也排除（题库 scripts/gen.py）
# 参考答案记为“作者自己跑的”（source: run）却没有锚点的 T7 条目：补上原文中作者交代自己搭建、设置基线的段落，
# 否则封闭世界的说明会把读者引向“没有说明”（2026-10-21 核对 D 材料时发现）。题库已冻结，故补在这里。
SUPPLEMENT = {
    "T7-bccfce23": ("2012.07436v3:302", "2012.07436v3:306"),  # Informer：比较方法含 LogSparse；按推荐设置运行比较方法
    "T7-6d4ffdbe": ("2106.13008v5:972",),  # Autoformer：Transformer 基线都按两层编码器、一层解码器搭建
    "T7-4c4f6b77": ("2106.13008v5:972",),
}
DATASETS = {"etth1", "etth2", "ettm1", "ettm2", "electricity", "traffic", "weather", "exchange", "ili", "solar",
            "pems03", "pems04", "pems07", "pems08"}  # fmt: skip
DATASET_ALIASES = {"elec": "electricity", "illness": "ili", "solarenergy": "solar", "weather-noaa": "weather"}

BANK = Path("~/pw-lab/probes").expanduser()
PAPERS = Path("~/pw-lab/data/formal/papers").expanduser()
CODE_ROOT = Path("~/pw-lab/code").expanduser()
REPOS = Path(__file__).resolve().parents[4] / "references/repos"  # 代码快照之外的其他固定提交，从本地克隆中取


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_yaml(path: Path) -> Any:
    return yaml.load(path.read_text(encoding="utf-8"), Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))


def _strings(value: Any) -> Any:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def anchors(value: Any) -> set[str]:
    return {m[0] for text in _strings(value) for m in ANCHOR.finditer(text)}


def clean(text: str) -> str:
    """去掉原文中的 HTML 跳转锚与站内链接目标，保留链接文字。"""
    text = re.sub(r"<a\s+[^>]*>\s*</a>", "", text)
    return re.sub(r"\[([^\]]+)\]\(#[^)]*\)", r"\1", text)


def merge(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for lo, hi in sorted(spans):
        if out and lo <= out[-1][1] + 1:
            out[-1] = (out[-1][0], max(hi, out[-1][1]))
        else:
            out.append((lo, hi))
    return out


def papers_at(bank: Path, papers: int) -> set[str]:
    """检查点 ``papers`` 时库中的论文版本：种子，加上这个检查点之前建库与更新的论文（计划表 ``tasks/plan.yml``）。"""
    present = set(read_yaml(bank / "tasks/reader.yml")["seed_papers"])
    for step in read_yaml(bank / "tasks/plan.yml"):
        if step["type"] == "checkpoint" and step["papers"] == papers:
            return present
        if step["type"] in ("build", "update"):
            present.add(step["paper"])
    raise KeyError(f"no checkpoint at {papers} papers")


def latest(present: set[str]) -> dict[str, str]:
    """编号 → 库中的最新版本。"""
    out: dict[str, str] = {}
    for paper in sorted(present, key=lambda p: (p.split("v")[0], int(p.split("v")[1]))):
        out[paper.split("v")[0]] = paper
    return out


@dataclass
class Passage:
    source: str  # 论文版本，或 ``<仓库>@<提交>:<路径>``
    first: int
    last: int
    role: str  # evidence（依据）、scope（封闭世界补上的主结果表）、judge（只供判分）
    lines: list[str] = field(repr=False)
    hidden: set[int] = field(default_factory=set)  # D 材料中切掉的行（原文行号）；判分包不切

    def text(self, cut: bool = False) -> str:
        out, skipping = [], False
        for n, line in enumerate(self.lines, self.first):
            if cut and n in self.hidden:
                if not skipping:
                    out.append("\t[rows not asked about are omitted here]")
                skipping = True
                continue
            skipping = False
            out.append(f"{n:>5}\t{line}")
        return clean("\n".join(out))


@dataclass
class Material:
    probe: str
    passages: list[Passage]
    errors: list[str]
    refs: dict[str, str]  # 论文版本 → 题面对它的指称（只进判分包）


class Evidence:
    def __init__(self, bank: Path = BANK, papers: Path = PAPERS, code: Path = CODE_ROOT, checkpoint: int = 30,
                 repos: Path = REPOS):  # fmt: skip
        self.bank, self.papers, self.code, self.repos = bank, papers, code, repos
        self.aliases = read_yaml(bank / "facts/aliases.yml")["papers"]
        self.dates = json.loads((bank / "facts/arxiv_versions.json").read_text(encoding="utf-8"))
        with (bank / "facts/tables.csv").open(encoding="utf-8") as f:
            self.tables = list(csv.DictReader(f))
        self.own = read_yaml(bank / "facts/own.yml")
        self.facts = [read_yaml(p) for p in sorted((bank / "facts/papers").glob("*.yml"))]
        self.present = papers_at(bank, checkpoint)
        self._sources: dict[str, list[str]] = {}
        self._rows: dict[str, dict[int, tuple[set[str], set[str]]]] | None = None

    # ------------------------------------------------------------ 来源与锚点

    def title(self, paper: str) -> str:
        return self.aliases[paper.split("v")[0]]["title"]

    def label(self, source: str) -> str:
        if "@" in source:
            repo_commit, path = source.split(":", 1)
            repo, commit = repo_commit.split("@")
            return f"code repository {repo} at commit {commit}, file {path}"
        return f"{self.title(source)} (arXiv {source})"

    def lines(self, source: str) -> list[str]:
        if source not in self._sources:
            if "@" not in source:
                data = (self.papers / source / "paper.md").read_text(encoding="utf-8")
            else:
                repo_commit, path = source.split(":", 1)
                repo, commit = repo_commit.split("@")
                if ".." in Path(path).parts or Path(path).is_absolute():
                    raise ValueError(f"unsafe code path: {source}")
                snapshots = [p for p in sorted(self.code.glob(f"{repo}@*")) if commit.startswith(p.name.split("@")[1])]
                if len(snapshots) > 1:
                    raise ValueError(f"code snapshot for {source} is ambiguous: {[p.name for p in snapshots]}")
                if snapshots:
                    data = (snapshots[0] / path).read_text(encoding="utf-8")
                else:  # 题库引用了同一仓库的另一固定提交（例如辅助组的 CATS@2c32c60）
                    data = subprocess.run(["git", "-C", str(self.repos / repo), "show", f"{commit}:{path}"],
                                          capture_output=True, text=True, check=True).stdout  # fmt: skip
            self._sources[source] = data.splitlines()
        return self._sources[source]

    def expand(self, anchor: str) -> tuple[str, int, int]:
        """锚点 → （来源，起，止）：整表、整段，或代码前后各补几行。"""
        if m := CODE.fullmatch(anchor):
            repo, commit, path, lo, hi = m.groups()
            source = f"{repo}@{commit}:{path}"
            lines = self.lines(source)
            a, b = int(lo), int(hi or lo)
            _check(a, b, lines)
            return (source, *code_block(lines, a, b))
        if not (m := PAPER.fullmatch(anchor)):
            raise ValueError(f"unrecognized anchor: {anchor}")
        source, table, lo, hi = m.groups()
        lines = self.lines(source)
        a, b = int(lo), int(hi or lo)
        _check(a, b, lines)
        if table:
            found = [t for t in self.tables if t["table"] == anchor]
            if len(found) != 1:
                raise ValueError(f"table anchor does not resolve uniquely: {anchor}")
            a, b = int(found[0]["first"]), int(found[0]["last"])
        tables = [(int(t["first"]), int(t["last"])) for t in self.tables if t["arxiv"] == source]
        return (source, *paper_block(lines, a, b, tables))

    def rows(self) -> dict[str, dict[int, tuple[set[str], set[str]]]]:
        """表 → 数据行的行号 → （数据集，方法列），来自 ``facts/cells.csv``。"""
        if self._rows is None:
            rows: dict[str, dict[int, tuple[set[str], set[str]]]] = defaultdict(dict)
            with (self.bank / "facts/cells.csv").open(encoding="utf-8") as f:
                for c in csv.DictReader(f):
                    datasets, headers = rows[c["table"]].setdefault(int(c["line"]), (set(), set()))
                    datasets.add(dataset_key(c["dataset"]))
                    headers.add(c["header"])
            self._rows = dict(rows)
        return self._rows

    def cut(self, probe: dict[str, Any], passage: Passage) -> set[int]:
        """D 材料中这一段要切掉的行：题目指定数据集时删去其他数据集的行；T6 补上的表只留表头。"""
        if "@" in passage.source or passage.role == "judge":
            return set()
        dataset = (probe.get("slots") or {}).get("D")
        header_only = probe["template"] == "T6" and passage.role == "scope"
        if not isinstance(dataset, str) and not header_only:
            return set()
        target = dataset_key(dataset) if isinstance(dataset, str) else None
        hidden = set()
        for t in self.tables:
            if t["arxiv"] != passage.source or int(t["last"]) < passage.first or int(t["first"]) > passage.last:
                continue
            rows = self.rows().get(t["table"], {})
            transposed = bool(rows) and max(len(h) for _, h in rows.values()) == 1  # 方法在行上
            for line, (datasets, _) in rows.items():
                if not passage.first <= line <= passage.last:
                    continue
                if header_only and not transposed:
                    hidden.add(line)
                elif target and datasets <= DATASETS and target not in datasets:
                    hidden.add(line)
        return hidden

    def main_tables(self) -> list[str]:
        """库中每篇论文（最新版本）主基准的多变量结果表。"""
        current = set(latest(self.present).values())
        out = []
        for fact in self.facts:
            for t in fact.get("tables", []):
                paper = t["table"].split(":")[0]
                multivariate = t.get("role", "").startswith("main") and t.get("variate") == "multivariate"
                if multivariate and paper in current and t["table"] not in EXCLUDED_TABLES:
                    out.append(t["table"])
        return sorted(out)

    # ------------------------------------------------------------ 每题的材料

    def anchors_of(self, probe: dict[str, Any]) -> tuple[set[str], set[str], set[str]]:
        """（依据锚点，封闭世界补上的表，只供判分的锚点）。"""
        gold, template = probe["gold"], probe["template"]
        evidence = anchors(probe.get("evidence", [])) | anchors(probe.get("refs", {}))
        evidence |= set(SUPPLEMENT.get(probe["id"], ()))
        for part in ("points", "entries", "ranking"):
            evidence |= anchors(gold.get(part, []))
        if template == "T1":
            evidence |= anchors(gold.get("location", "")) | anchors(gold.get("also_at", []))
        if template == "T3":
            for own in self.own:
                if own["paper"] in probe["requires"]:
                    evidence |= anchors({k: v for k, v in own.items() if k in ("anchor", "code_anchor")})
        auto = "points" not in gold
        scope = set(self.main_tables()) if auto and template in SCOPED else set()
        judge = anchors(gold) - evidence
        if template == "T1" or (template == "T8" and auto):  # 另一处位置、另一组实验：所涉论文的全部结果表
            judge |= {t["table"] for t in self.tables if t["arxiv"] in probe["requires"]}
        return evidence, scope - evidence, judge - evidence

    def material(self, probe: dict[str, Any]) -> Material:
        evidence, scope, judge = self.anchors_of(probe)
        errors = [f"unsupported evidence locator: {e}" for e in probe.get("evidence", []) if not anchors(e)]
        spans: dict[tuple[str, str], list[tuple[int, int]]] = defaultdict(list)
        for role, group in (("evidence", evidence), ("scope", scope), ("judge", judge)):
            for anchor in sorted(group):
                try:
                    source, lo, hi = self.expand(anchor)
                except (ValueError, OSError, subprocess.CalledProcessError) as exc:
                    errors.append(f"{anchor}: {exc}")
                    continue
                spans[(source, role)].append((lo, hi))
        passages = []
        covered: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for role in ("evidence", "scope", "judge"):  # 依据优先；补上的表与判分背景只取依据之外的部分
            for (source, r), ranges in sorted(spans.items()):
                if r != role:
                    continue
                for lo, hi in merge(ranges):
                    for a, b in _subtract((lo, hi), covered[source]):
                        passages.append(Passage(source, a, b, role, self.lines(source)[a - 1 : b]))
                    covered[source] = merge([*covered[source], (lo, hi)])
        passages.sort(key=lambda p: (p.role == "judge", _order(p.source), p.first))
        for p in passages:
            p.hidden = self.cut(probe, p)
        if not any(p.role == "evidence" for p in passages):
            errors.append("no evidence passages")
        slots = probe.get("slots") or {}
        refs = {slots[slot]: ref["text"] for slot, ref in (probe.get("refs") or {}).items()
                if isinstance(slots.get(slot), str) and slots[slot] in self.present}  # fmt: skip
        return Material(probe["id"], passages, errors, refs)

    def paper_list(self) -> list[str]:
        out = []
        for paper in sorted(self.present, key=_order):
            first = self.dates.get(paper.split("v")[0], {}).get("1", "unknown")
            out.append(f"- {self.title(paper)} (arXiv {paper}; first arXiv version {first})")
        return out


def dataset_key(name: str) -> str:
    key = name.strip().lower()
    return DATASET_ALIASES.get(key, key)


def paper_block(lines: list[str], a: int, b: int, tables: list[tuple[int, int]]) -> tuple[int, int]:
    """论文中第 ``a``–``b`` 行所在的块：落在表内的行扩展为整表（``tables`` 为该论文各表的起止行，按
    ``facts/tables.csv`` 的顺序），再上下取到空行。D 的材料、判分包与读者的放行名单（:mod:`pweval.protocol.allowlist`）
    用同一规则。"""
    for first, last in tables:
        if first <= b and last >= a:
            a, b = min(a, first), max(b, last)
    while a > 1 and lines[a - 2].strip():
        a -= 1
    while b < len(lines) and lines[b].strip():
        b += 1
    return a, b


def code_block(lines: list[str], a: int, b: int) -> tuple[int, int]:
    """代码中第 ``a``–``b`` 行所在的块：前后各补 ``CODE_CONTEXT`` 行。"""
    return max(1, a - CODE_CONTEXT), min(len(lines), b + CODE_CONTEXT)


def _check(lo: int, hi: int, lines: list[str]) -> None:
    if not 1 <= lo <= hi <= len(lines):
        raise ValueError(f"anchor range {lo}-{hi} outside 1-{len(lines)}")


def _subtract(span: tuple[int, int], taken: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out, (lo, hi) = [], span
    for a, b in taken:
        if b < lo or a > hi:
            continue
        if a > lo:
            out.append((lo, a - 1))
        lo = max(lo, b + 1)
    if lo <= hi:
        out.append((lo, hi))
    return out


def _order(source: str) -> tuple[int, str]:
    return (1, source) if "@" in source else (0, source)


def _block(p: Passage, label: str, cut: bool = False) -> str:
    body = p.text(cut)
    if "@" in p.source:
        fence = "`" * max(3, 1 + max((len(x) for x in re.findall(r"`+", body)), default=0))
        body = f"{fence}\n{body}\n{fence}"
    return f"[{label}, lines {p.first}–{p.last}]\n\n{body}"


def reader_material(ev: Evidence, probe: dict[str, Any]) -> str:
    """D 作答用：库中的论文清单与依据段落（英文）。提取有错时报错，不给不完整的材料。"""
    m = ev.material(probe)
    if m.errors:
        raise ValueError(f"{probe['id']}: {m.errors}")
    shown = [p for p in m.passages if p.role != "judge"]
    blocks = [_block(p, ev.label(p.source), cut=True) for p in shown]
    heading = "Passages from these papers (each line starts with its line number in the paper):"
    if any("@" in p.source for p in shown):
        heading = ("Passages from these papers and their code repositories (each line starts with its line number "
                   "in the paper or file):")  # fmt: skip
    return (
        "Papers in the store (title; arXiv id and version; date of the first arXiv version):\n\n"
        + "\n".join(ev.paper_list())
        + f"\n\n{heading}\n\n"
        + "\n\n".join(blocks)
    )


def judge_material(ev: Evidence, probe: dict[str, Any]) -> str:
    """判分包的前半部分：问题、论文清单、判题证据、参考答案与评分规则（待评回答与输出格式由生成器加上）。"""
    m = ev.material(probe)
    if m.errors:
        raise ValueError(f"{probe['id']}: {m.errors}")
    blocks = []
    for p in m.passages:
        if p.role == "scope":
            continue
        note = f"（题面中的“{m.refs[p.source]}”指这篇论文）" if p.source in m.refs else ""
        kind = "只供判分的背景" if p.role == "judge" else "依据"
        blocks.append(f"### {kind}：{ev.label(p.source)}{note}\n\n" + _block(p, ev.label(p.source)))
    gold = yaml.safe_dump(probe["gold"], allow_unicode=True, sort_keys=False, width=110)
    return (
        f"## 问题\n\n{probe['question'].strip()}\n\n"
        "## 库中的论文\n\n" + "\n".join(ev.paper_list()) + "\n\n"
        "## 判题证据\n\n" + "\n\n".join(blocks) + "\n\n"
        f"## 参考答案\n\n```yaml\n{gold}```\n\n"
        f"## 评分规则\n\n{probe['scoring'].strip()}\n"
    )


# ---------------------------------------------------------------- 渲染出来查看


def load_probes(bank: Path) -> list[dict[str, Any]]:
    """200 道主题（``probes/sample.yml`` 的顺序）加上辅助组。"""
    pool = {p["id"]: p for name in ("auto.yml", "manual-rendered.yml") for p in read_yaml(bank / "probes" / name)}
    chosen = [pool[p["id"]] for p in read_yaml(bank / "probes/sample.yml")]
    return chosen + [p for p in pool.values() if p.get("group") == "auxiliary"]


def count_tokens(url: str, text: str) -> int:
    request = urllib.request.Request(url.rstrip("/").removesuffix("/v1") + "/tokenize", method="POST",
                                     data=json.dumps({"prompt": text}).encode(),
                                     headers={"Content-Type": "application/json"})  # fmt: skip
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=60) as response:
        return int(json.load(response)["count"])


def build(ev: Evidence, out: Path, ids: set[str] | None = None, tokenizer: str | None = None) -> dict[str, Any]:
    if out.exists() and any(out.iterdir()):
        raise ValueError(f"output directory must be empty: {out}")
    probes = [p for p in load_probes(ev.bank) if ids is None or p["id"] in ids]
    for folder in ("reader", "judge"):
        (out / folder).mkdir(parents=True, exist_ok=True)
    items = []
    for probe in probes:
        m = ev.material(probe)
        row: dict[str, Any] = {"id": probe["id"], "template": probe["template"], "errors": m.errors,
                               "passages": [{"source": p.source, "first": p.first, "last": p.last, "role": p.role}
                                            for p in m.passages]}  # fmt: skip
        if not m.errors:
            reader, judge = reader_material(ev, probe), judge_material(ev, probe)
            (out / "reader" / f"{probe['id']}.md").write_text(reader + "\n", encoding="utf-8")
            (out / "judge" / f"{probe['id']}.md").write_text(judge, encoding="utf-8")
            row |= {"reader_chars": len(reader), "judge_chars": len(judge), "reader_sha256": digest(reader.encode())}
            if tokenizer:
                row["reader_tokens"] = count_tokens(tokenizer, reader)
        items.append(row)
    inputs = {str(p.relative_to(ev.bank)): digest(p.read_bytes()) for part in ("probes", "facts", "tasks")
              for p in sorted((ev.bank / part).rglob("*")) if p.is_file()}  # fmt: skip
    manifest = {"renderer_sha256": digest(Path(__file__).read_bytes()), "inputs": inputs, "count": len(items),
                "groups": dict(Counter(p.get("group", "main") for p in probes)),
                "errors": {r["id"]: r["errors"] for r in items if r["errors"]}, "items": items}  # fmt: skip
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--ids", help="只渲染这些题（逗号分隔）；缺省为 200 道主题加辅助组")
    parser.add_argument("--tokenizer", help="推理服务地址，用它的分词接口数 D 材料的 token")
    args = parser.parse_args()
    manifest = build(Evidence(), args.out.resolve(), set(args.ids.split(",")) if args.ids else None, args.tokenizer)
    tokens = sorted((r.get("reader_tokens", 0), r["id"]) for r in manifest["items"])
    print(json.dumps({"count": manifest["count"], "errors": len(manifest["errors"]),
                      "max_reader_tokens": tokens[-3:] if tokens and tokens[-1][0] else None}))  # fmt: skip
    return int(bool(manifest["errors"]))


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["Evidence", "Material", "Passage", "anchors", "code_block", "judge_material", "latest", "paper_block", "papers_at",
           "reader_material"]
