"""V3 判分：Final answer 段由正则解析，名称按题库归一，脚本按每题的 ``scoring`` 计分；只有脚本判不了的条目交给判分
子代理（docs/designs/v3/evaluation.md §5.4；tmps/probes/grading-plan.md）。

    python -m pweval.measure.grade_v3 <运行名> score [--groups C,A3,…] [--probes-repo …] [--runs-root …]

流程（本模块实现第 ①、④ 步，第 ②、③ 步的判分包与子代理另做）：

1. **解析：** :func:`pweval.protocol.final_answer.parse` 取 Final answer 段；方法与论文按 :mod:`pweval.measure.names` 归一。
2. **待判条目：** 脚本判不了的条目写进 ``grades/pending.jsonl``：
   - ``extract``：缺 Final answer 段或解析不出，子代理从全文按同一格式写出这一段，再经同一解析器计分；
   - ``name``：认不出的方法名或论文指称，子代理对照语料清单判定（存 ``grades/names.jsonl``，按名称复用）；
   - 语义子项：``t3-lookback``、``t7-source:<论文>``、``t7-note:<论文>``、``t7-match:<论文>``、``t8-declares``
     （见各题型）；
   - ``points``：要点题逐条判定（含辅助组）。
3. **子代理判定**写回 ``grades/judgments.jsonl``：每行 ``{"record", "answer_sha", "item", "value", "reason", "judge"}``；
   回答变了（哈希不同）的判定不再使用。
4. **计分：** 每条回答一行写进 ``grades/scores/<组>-k<篇数>[-aux].jsonl``；还有待判条目的，``score`` 为 ``null``。

**失控**（§5.1、§7 第 4 条）：触发安全上限（``exit`` 为 ``timeout``，或最后一条回复撞上输出上限 ``stop = length``）的回答，
协议分 ``score`` 记 0，标 ``runaway``；按内容算的分另存为 ``content_score``，只供敏感性分析，这类回答的待判条目不交给子代理。

**空回答：** 正文为空的回答（模型在思考中途就结束了，没有写出正文；C 组 206 条中有 13 条）记 0 分，标 ``empty-answer``，
不交给子代理。

**题库核对：** 判分前读运行目录的 ``run.yml``：每次调用记下的题库提交须与本机题库的当前提交相同、且运行时与现在
都没有改动（含未跟踪的文件），否则拒绝判分，除非给出 ``--allow-unfrozen``（开发用，记入 ``grades/score-run.json``）。

只依赖标准库与 pyyaml，不调用模型，不连库；同样的输入得到同样的分数。只为语义子项交给子代理的条目，脚本都先做了
机械判断：判得了的不交（例如 T3 的 look-back 金标准是一个数时直接比较，数值已经错了的不再问 look-back）。

各题型的计分（每题 ``scoring`` 原文为准）：

- **T1：** 两个值都对且位置对记 1；两个值都对但缺位置，或只对一个值，记 0.5；否则 0。位置对指：写出的表号就是金标准的表，
  或是同一篇中有同一组 MSE、MAE 的另一张表（``facts/cells.csv``）；写行号时按 ``facts/tables.csv`` 的行号范围找表。
- **T3：** 回答的（方法，论文）集合与金标准相同（并列须全部列出），且值与 look-back 都对，记 1；（方法，论文）都在金标准中
  但值或 look-back 错、或并列没列全，记 0.5；出现金标准以外的（方法，论文）记 0。
- **T4、T6：** 方法集合的 F1。**T5：** 被超过的基线的 F1 与（基线，后来论文）对的 F1 各占一半。
- **T7：** 按论文的软 F1 $2\\sum c / (|A| + |G|)$。找对的论文 $c$：来源类别对且（类别不是 cited，或所引出处也对）为 1；
  类别为 cited、出处不对为 0.5；论文未声明来源而回答把数值相同的出处（``match``）说成所引来源为 0.5；其余为 0。
  带 ``stated_note`` 的条目，回答的类别与金标准不同时按说明判是否接受，接受记 1。
- **T8（自动题）：** （论文，值）对的 F1；同一论文其他多变量实验的额外的对，若回答注明了表、且原文该表中这个方法确有此值，
  不计入；F1 大于 0 时再判回答是否断定某个值对、其余错（超出论文自己的说法），是则记 0。
- **要点题：** 各要点的平均（子代理给每个要点 0–1 的分，按集合 F1 计分的要点可以给小数）；违反 ``must_not`` 记 0。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from ..protocol.final_answer import format_for, is_auto, parse
from .names import NOT_METHOD, Names, Tables, load, load_judged, load_tables

PROBES_REPO = Path("~/pw-lab/probes").expanduser()
RUNS_ROOT = Path("~/pw-lab/runs").expanduser()
MAIN_CHECKPOINT = 30  # 参照组（C、D、P）与检查点无关，按主检查点的库判
RUNAWAY_EXITS = ("timeout",)  # 触发安全上限的退出（300 次工具调用的上限落地后加上它的退出码）


def runaway(record: dict[str, Any]) -> bool:
    return str(record.get("exit")) in RUNAWAY_EXITS or record.get("stop") == "length"


def load_probes(probes_repo: Path) -> dict[str, dict[str, Any]]:
    """题号 → 题（自动题与要点题，含辅助组）。"""
    pool: dict[str, dict[str, Any]] = {}
    for name in ("auto.yml", "manual-rendered.yml"):
        pool |= {p["id"]: p for p in yaml.safe_load((probes_repo / "probes" / name).read_text(encoding="utf-8"))}
    return pool


def papers_at(probes_repo: Path, papers: int) -> set[str]:
    """检查点 ``papers`` 时库中的论文版本：种子，加上这个检查点之前建库与更新的论文（同
    :func:`pweval.harness.timeline.papers_at`；测量层不依赖运行框架，这里直接读计划表）。"""
    tasks = probes_repo / "tasks"
    present = set(yaml.safe_load((tasks / "reader.yml").read_text(encoding="utf-8"))["seed_papers"])
    for step in yaml.safe_load((tasks / "plan.yml").read_text(encoding="utf-8")):
        if step["type"] == "checkpoint" and step["papers"] == papers:
            return present
        if step["type"] in ("build", "update"):
            present.add(step["paper"])
    raise KeyError(f"no checkpoint at {papers} papers")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def record_key(record: dict[str, Any]) -> str:
    """一条回答的标识：组/检查点/题集/题/次。"""
    checkpoint = record.get("checkpoint") or MAIN_CHECKPOINT
    return f"{record['arm']}/k{checkpoint}/{record.get('group', 'main')}/{record['probe']}/r{record.get('rep', 1)}"


def answer_sha(record: dict[str, Any]) -> str:
    return hashlib.sha256(record["answer"].encode("utf-8")).hexdigest()[:16]


def same(a: Any, b: Any) -> bool:
    """数值相等（0.37 与 0.370 相同），不设容差。"""
    try:
        return round(float(a), 6) == round(float(b), 6)
    except (TypeError, ValueError):
        return False


def f1(answer: set[Any], gold: set[Any]) -> float:
    if not answer and not gold:
        return 1.0
    return 2 * len(answer & gold) / (len(answer) + len(gold))


@dataclass
class Ask:
    """一条回答的判定：已有的取出来，没有的记为待判。"""

    judged: dict[str, Any]
    names: Names
    pending: list[dict[str, Any]] = field(default_factory=list)
    unknown: list[dict[str, str]] = field(default_factory=list)

    def get(self, item: str, **context: Any) -> Any:
        if item in self.judged:
            return self.judged[item]
        self.pending.append({"item": item, **context})
        return None

    def method(self, name: str, table: str | None = None) -> str | None:
        hit = self.names.method(name, table)
        if hit is None:
            self.unknown.append({"kind": "method", "name": name.strip()})
        return hit

    def paper(self, name: str) -> str | None:
        hit = self.names.paper(name)
        if hit is None:
            self.unknown.append({"kind": "paper", "name": name.strip()})
        return hit

    def methods(self, names: list[str]) -> set[str]:
        return {m for n in names if (m := self.method(n)) not in (None, NOT_METHOD)}


# ---------------------------------------------------------------- 各题型


def _numbers(text: str | None, pattern: str) -> list[int]:
    return [int(x) for x in re.findall(pattern, text or "", flags=re.I)]


def _has_pair(tables: Tables, table: str, mse: float, mae: float) -> bool:
    """表中某一列在同一数据集、预测长度下同时有这组 MSE 与 MAE。"""
    seen: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for c in tables.cells.get(table, []):
        if c["metric"] == "mse" and same(c["value"], mse):
            seen[(c["dataset"], c["horizon"], c["header"])].add("mse")
        elif c["metric"] == "mae" and same(c["value"], mae):
            seen[(c["dataset"], c["horizon"], c["header"])].add("mae")
    return any(v == {"mse", "mae"} for v in seen.values())


def located(location: str | None, gold: dict[str, Any], tables: Tables) -> bool:
    """T1 的位置：写出的表号或行号落在金标准的表上，或落在同一篇中有同一组 MSE、MAE 的表上。"""
    paper = gold["location"].split(":")[0]
    right = {t["table"] for t in tables.numbered.get((paper, int(gold["table"])), [])}
    right |= {a.split(":")[0] for a in gold.get("also_at", []) if ":T" in a}

    def ok(table: str) -> bool:
        return table in right or _has_pair(tables, table, gold["mse"], gold["mae"])

    for number in _numbers(location, r"\btab(?:le|\.)?\s*([0-9]+)"):
        if number == int(gold["table"]) or any(ok(t["table"]) for t in tables.numbered.get((paper, number), [])):
            return True
    for line in _numbers(location, r"(?:\blines?\s*|\bL|::)([0-9]+)"):
        if any(ok(t) for t in tables.by_line(paper, line)):
            return True
    return False


def t1(probe: dict[str, Any], a: dict[str, Any], ask: Ask, tables: Tables) -> float | None:
    g = probe["gold"]
    mse, mae = same(a["mse"], g["mse"]), same(a["mae"], g["mae"])
    if mse and mae:
        return 1.0 if located(a.get("location"), g, tables) else 0.5
    return 0.5 if mse or mae else 0.0


def t3(probe: dict[str, Any], a: dict[str, Any], ask: Ask, tables: Tables) -> float | None:
    g = probe["gold"]
    gold = {(ask.method(m), p) for m, p in zip(g["method"], g["paper"], strict=True)}
    rows = [(ask.method(r["method"]), ask.paper(r["paper"]), r) for r in a["best"]]
    if ask.unknown:
        return None
    given = {(m, p) for m, p, _ in rows}
    if not given or not given <= gold:
        return 0.0
    if given != gold or not all(same(r["mse"], g["mse"]) for _, _, r in rows):
        return 0.5
    stated = [r["lookback"].strip() for _, _, r in rows]
    gold_lookback = str(g["lookback"]).strip()
    if re.fullmatch(r"\d+", gold_lookback):
        right = all(re.findall(r"\d+", s) == [gold_lookback] for s in stated)
    elif all(s.lower() == gold_lookback.lower() for s in stated):
        right = True
    else:
        right = ask.get("t3-lookback", answer=stated, gold=gold_lookback)
        if right is None:
            return None
    return 1.0 if right else 0.5


def t4(probe: dict[str, Any], a: dict[str, Any], ask: Ask, tables: Tables) -> float | None:
    gold = probe["gold"]["methods" if probe["template"] == "T4" else "dropped"]
    given = ask.methods(a["methods"])
    return None if ask.unknown else f1(given, set(gold))


def t5(probe: dict[str, Any], a: dict[str, Any], ask: Ask, tables: Tables) -> float | None:
    g = probe["gold"]
    beaten = ask.methods(a["beaten"])
    pairs = {(ask.method(p["baseline"]), ask.paper(p["paper"])) for p in a["later_papers"]}
    if ask.unknown:
        return None
    gold_pairs = {(b, p) for b, ps in g["later_papers"].items() for p in ps}
    return 0.5 * f1(beaten, set(g["beaten"])) + 0.5 * f1(pairs, gold_pairs)


def t7(probe: dict[str, Any], a: dict[str, Any], ask: Ask, tables: Tables) -> float | None:
    gold = {e["paper"]: e for e in probe["gold"]["entries"]}
    given = {ask.paper(e["paper"]): e for e in a["entries"]}
    if ask.unknown:
        return None
    credits = []  # 待判的条目一次收齐，有一条没判就不出分
    for paper in sorted(given.keys() & gold.keys()):
        said, g = given[paper], gold[paper]
        kind = "own" if g["source"] in ("own", "run") else g["source"]
        context = {"paper": paper, "answer": said}
        if said["provenance"] == kind:
            right = True if kind != "cited" else ask.get(f"t7-source:{paper}", **context, gold=g["from"])
            credits.append(None if right is None else 1.0 if right else 0.5)
        elif g.get("stated_note"):
            accepted = ask.get(f"t7-note:{paper}", **context, gold=kind, note=g["stated_note"])
            credits.append(None if accepted is None else 1.0 if accepted else 0.0)
        elif kind == "not stated" and said["provenance"] == "cited" and g.get("match"):
            is_match = ask.get(f"t7-match:{paper}", **context, match=g["match"])
            credits.append(None if is_match is None else 0.5 if is_match else 0.0)
        else:
            credits.append(0.0)
    if None in credits:
        return None
    credit = sum(credits)
    return 2 * credit / (len(given) + len(gold)) if given or gold else 1.0


def t8(probe: dict[str, Any], a: dict[str, Any], ask: Ask, tables: Tables) -> float | None:
    g = probe["gold"]
    first = g["groups"][0]["entries"][0]
    method = ask.names.method(first["header"], first["table"])
    gold = {(p, round(float(grp["mse"]), 6)) for grp in g["groups"] for p in grp["papers"]}
    given = set()
    for pair in a["pairs"]:
        paper = ask.paper(pair["paper"])
        if paper is None:
            continue
        value = round(float(pair["mse"]), 6)
        if (paper, value) not in gold and _elsewhere(paper, value, pair.get("table"), method, ask.names, tables):
            continue  # 同一论文其他多变量实验中确有此值，且回答注明了表：不算错
        given.add((paper, value))
    if ask.unknown:
        return None
    score = f1(given, gold)
    if score > 0 and (declares := ask.get("t8-declares")) is not None:
        return 0.0 if declares else score
    return None if score > 0 else 0.0


def _elsewhere(paper: str, value: float, table: str | None, method: str | None, names: Names, tables: Tables) -> bool:
    for number in _numbers(table, r"\btab(?:le|\.)?\s*([0-9]+)"):
        for t in tables.numbered.get((paper, number), []):
            for c in tables.cells.get(t["table"], []):
                if c["metric"] == "mse" and same(c["value"], value) and names.method(c["header"], t["table"]) == method:
                    return True
    return False


SCORERS: dict[str, Callable[[dict[str, Any], dict[str, Any], Ask, Tables], float | None]] = {
    "T1": t1, "T3": t3, "T4": t4, "T5": t5, "T6": t4, "T7": t7, "T8": t8,
}  # fmt: skip


def points(probe: dict[str, Any], ask: Ask) -> float | None:
    """要点题：子代理给每个要点 0–1 的分（``{"points": {id: 分}, "must_not": bool}``）。"""
    gold = probe["gold"]
    judged = ask.get("points", points=[p["id"] for p in gold["points"]], must_not=gold.get("must_not"))
    if judged is None:
        return None
    marks = judged["points"]
    if set(marks) != {p["id"] for p in gold["points"]}:
        raise ValueError(f"{probe['id']}: judged points {sorted(marks)} do not match the gold points")
    if judged.get("must_not"):
        return 0.0
    return sum(float(v) for v in marks.values()) / len(marks)


# ---------------------------------------------------------------- 一条回答


def grade(record: dict[str, Any], probe: dict[str, Any], names: Names, tables: Tables,
          judged: dict[str, Any]) -> dict[str, Any]:  # fmt: skip
    """一条回答的计分。``judged`` 是这条回答已有的判定（条目 → 值）。"""
    ask = Ask(judged, names)
    flags = []
    if record.get("stop") == "length":
        flags.append("output-limit")
    if str(record.get("exit")) not in ("0", "None"):
        flags.append(f"exit-{record.get('exit')}")
    if record.get("network"):
        flags.append("network")
    parsed = None
    if not record["answer"].strip():
        flags.append("empty-answer")
        score = 0.0
    elif not is_auto(probe):
        score = points(probe, ask)
    else:
        parsed = parse(probe["template"], record["answer"])
        if parsed is None:
            flags.append("no-final-answer")
            extract = ask.get("extract", format=format_for(probe))
            parsed = None if extract is None else parse(probe["template"], f"Final answer\n{extract}")
            if extract is not None and parsed is None:
                parsed = {"empty": True}  # 子代理判定全文中也没有答案
        if parsed is None:
            score = None
        elif parsed.get("empty"):
            score = 0.0
        else:
            score = SCORERS[probe["template"]](probe, parsed, ask, tables)
    if ask.unknown:
        score = None
    content_score = score
    if runaway(record):
        flags.insert(0, "runaway")
        score, ask.pending, ask.unknown = 0.0, [], []
    return {
        "key": record_key(record),
        "arm": record["arm"],
        "checkpoint": record.get("checkpoint"),
        "group": record.get("group", "main"),
        "probe": probe["id"],
        "rep": record.get("rep", 1),
        "template": probe["template"],
        "score": score,
        "content_score": content_score,
        "flags": flags,
        "parsed": parsed,
        "pending": ask.pending,
        "unknown": _unique(ask.unknown),
        "answer_sha": answer_sha(record),
    }


def _unique(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [dict(t) for t in dict.fromkeys(tuple(sorted(r.items())) for r in rows)]


# ---------------------------------------------------------------- 运行目录


def load_judgments(path: Path) -> dict[str, dict[str, Any]]:
    """``grades/judgments.jsonl`` → 回答标识 → {条目: 值}；回答的哈希须一致，后写的覆盖先写的。"""
    out: dict[str, dict[str, Any]] = defaultdict(dict)
    for row in read_jsonl(path):
        out[f"{row['record']}@{row['answer_sha']}"][row["item"]] = row["value"]
    return out


def answer_files(run: Path, groups: list[str] | None) -> list[Path]:
    files = sorted(f for f in (run / "answers").glob("*/k*.jsonl") if re.fullmatch(r"k\d+(?:-aux)?\.jsonl", f.name))
    return [f for f in files if groups is None or f.parent.name in groups]


def check_probes(run: Path, probes_repo: Path) -> list[str]:
    """运行时记下的题库提交与本机题库是否一致、是否都干净；返回不一致之处（空表示一致）。"""
    head = _git(probes_repo, "rev-parse", "HEAD")
    problems = []
    if _git(probes_repo, "status", "--porcelain"):
        problems.append(f"{probes_repo} has uncommitted or untracked changes")
    path = run / "run.yml"
    if not path.exists():
        return [*problems, f"{path} is missing"]
    for i, invocation in enumerate(yaml.safe_load(path.read_text(encoding="utf-8"))["invocations"]):
        used = invocation.get("probes") or {}
        if used.get("commit") != head:
            used_at = str(used.get("commit"))[:7]
            problems.append(f"invocation {i} used probes {used_at}, the local repo is at {head[:7]}")
        if used.get("dirty", True):
            problems.append(f"invocation {i} ran with uncommitted changes in the probes repo")
    return problems


def score_run(run: Path, probes_repo: Path, groups: list[str] | None, *,
              allow_unfrozen: bool = False) -> dict[str, Any]:  # fmt: skip
    if (problems := check_probes(run, probes_repo)) and not allow_unfrozen:
        raise SystemExit("probes repo does not match the run (pass --allow-unfrozen for development runs):\n  "
                         + "\n  ".join(problems))  # fmt: skip
    probes = load_probes(probes_repo)
    tables = load_tables(probes_repo)
    judged_names = load_judged(run / "grades/names.jsonl")
    judgments = load_judgments(run / "grades/judgments.jsonl")
    names_at: dict[int, Names] = {}
    out_dir = run / "grades/scores"
    out_dir.mkdir(parents=True, exist_ok=True)
    pending, unknown, summary = [], {}, {}
    for path in answer_files(run, groups):
        rows = []
        for record in read_jsonl(path):
            checkpoint = record.get("checkpoint") or MAIN_CHECKPOINT
            if checkpoint not in names_at:
                names_at[checkpoint] = load(probes_repo, papers_at(probes_repo, checkpoint))
                names_at[checkpoint].judged = judged_names
            judged = judgments.get(f"{record_key(record)}@{answer_sha(record)}", {})
            row = grade(record, probes[record["probe"]], names_at[checkpoint], tables, judged)
            rows.append(row)
            pending += [{"record": row["key"], "answer_sha": row["answer_sha"], "probe": row["probe"],
                         "template": row["template"], **p} for p in row["pending"]]  # fmt: skip
            for u in row["unknown"]:
                unknown.setdefault((u["kind"], u["name"]), {**u, "records": []})["records"].append(row["key"])
        name = f"{path.parent.name}-{path.name}"
        _write_jsonl(out_dir / name, rows)
        scored = [r["score"] for r in rows if r["score"] is not None]
        summary[name] = {
            "answers": len(rows),
            "scored": len(scored),
            "mean": round(sum(scored) / len(scored), 4) if scored else None,
            "runaway": sum("runaway" in r["flags"] for r in rows),
            "empty_answer": sum("empty-answer" in r["flags"] for r in rows),
            "no_final_answer": sum("no-final-answer" in r["flags"] for r in rows),
            "pending": sum(r["score"] is None for r in rows),
        }
    _write_jsonl(run / "grades/pending.jsonl", pending + [{"item": "name", **u} for u in unknown.values()])
    meta = {"at": datetime.now(UTC).isoformat(timespec="seconds"),
            "probes_commit": _git(probes_repo, "rev-parse", "HEAD"),
            "eval_commit": _git(Path(__file__).parent, "rev-parse", "HEAD"), "unfrozen": problems,
            "summary": summary}  # fmt: skip
    (run / "grades/score-run.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return meta


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    tmp.replace(path)


def _git(path: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, check=True).stdout.strip()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("name", help="运行名，例如 ref1、f1")
    parser.add_argument("command", choices=("score", "packets", "import"))
    parser.add_argument("package", nargs="?", help="import：判分包目录（grades/packets/<包名>/package）")
    parser.add_argument("--name", dest="package_name", help="packets：包名（缺省为 <组>-<日期时间>）")
    parser.add_argument("--judge", help="import：判分者（例如 claude-code:<合作者>）")
    parser.add_argument("--groups", help="只判这些组（逗号分隔），例如 C 或 A0,A3")
    parser.add_argument("--probes-repo", default=str(PROBES_REPO))
    parser.add_argument("--runs-root", default=str(RUNS_ROOT))
    parser.add_argument("--allow-unfrozen", action="store_true", help="题库与运行时不一致也判（开发用）")
    args = parser.parse_args(argv)
    probes_repo = Path(args.probes_repo).expanduser()
    run = Path(args.runs_root).expanduser() / args.name
    groups = args.groups.split(",") if args.groups else None
    if args.command == "import":
        from .packets import import_judgments

        if not args.package or not args.judge:
            parser.error("import needs the package directory and --judge")
        result = import_judgments(run, Path(args.package).expanduser().resolve(), args.judge)
        print(json.dumps({k: v if isinstance(v, int) else len(v) for k, v in result.items()}))
        for line in result["rejected"] + result["missing"][:50]:
            print("  " + line)
    meta = score_run(run, probes_repo, groups, allow_unfrozen=args.allow_unfrozen)
    for name, s in meta["summary"].items():
        print(f"{name:24} answers={s['answers']:4} scored={s['scored']:4} pending={s['pending']:4} "
              f"runaway={s['runaway']:3} empty={s['empty_answer']:3} no_final_answer={s['no_final_answer']:3} "
              f"mean={s['mean']}")  # fmt: skip
    if args.command == "packets":
        from .packets import build

        name = args.package_name or f"{'-'.join(groups or ['all'])}-{datetime.now(UTC):%Y%m%dT%H%M}"
        package = build(run, name, probes_repo, groups)
        print(f"package: {package}\narchive: {package.parent / (name + '.tar.gz')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["SCORERS", "f1", "grade", "located", "main", "record_key", "same", "score_run"]
