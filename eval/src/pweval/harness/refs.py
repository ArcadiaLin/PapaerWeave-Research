"""V3 参照组的读者：C 闭卷、D 段落、P 原文（docs/designs/v3/evaluation.md §7 第 2 条、§10）。参照组没有写者，只依赖
冻结的题库、语料与模型，先于写者组运行。

    python -m pweval.harness.refs <运行名> --groups C [--reps 2] [--probes main|aux|all] [--ids <题号,…>]
        [--limit N] [--llm <服务地址>] [--config eval/config/refs-ltsf.yml] [--dry-run] [--allow-config-change]

- C 闭卷组：只给题目，不给库、原文与工具（pi ``--no-tools``）。提示语为题面、C 的说明句与题型的 Final answer 段
  （:mod:`pweval.protocol.final_answer`；要点题没有这一段）。
- D 段落组：同样不带工具；提示语为题面、依据材料（:func:`pweval.protocol.evidence.reader_material`：库中论文清单与
  依据段落，表按题目切行）、D 的说明句与 Final answer 段。回答记录另带 ``passages``（每段的出处、行号区间与切掉的行数）
  与 ``material_sha256``。
- P 原文组：带 pi 的默认内置工具（read、bash 等），不带库；按检查点 10 → 20 → 30 篇依次作答，每个检查点只给当时已入库的
  论文（:func:`pweval.harness.timeline.papers_at`，新旧版本都在），复制到 ``<运行目录>/P/papers/k<篇数>/``，只读挂载为
  ``/work/papers``；题为该检查点的有效题（严格规则，D31）。沙箱断网，模型调用经 unix socket 转发（``Arm.isolated_llm``）。
  P 的推理服务与并发可以单独配置（``llm_by_group``、``runner.workers_by_group``），与 C、D 不共用一台服务。

C、D 与库、检查点都无关，所以每题每次只答一次，第 10、20 篇检查点取其中的有效子集（严格规则，D31）。回答存在
``<运行目录>/answers/<组>/k30.jsonl``（主检验）与 ``k30-aux.jsonl``（辅助组）；P 按检查点存在 ``k<篇数>.jsonl`` 与
``k<篇数>-aux.jsonl``。一题一次一行，字段与正式时间线的读者相同（:func:`pweval.harness.timeline.answer`），另记 ``rep``
与 ``group``。运行时不判分。

中断后用同一条命令续跑：已存的（题，次）跳过。``run.yml`` 每次调用追加一条记录（参数、生效的配置、仓库与题库的
提交、pi 版本），续跑时配置或题库的提交变了即拒绝，除非 ``--allow-config-change``。``--dry-run`` 只打印提示语，
不调用模型、不写运行目录。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import sys
import traceback
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

from ..paths import EVAL
from ..protocol.evidence import SCOPED, Evidence, reader_material
from ..protocol.final_answer import format_for
from .sandbox import ENV_NOTE, Arm, Paths, Writer, prepare, run_session
from .timeline import (
    Timeline,
    _record_run,
    append_jsonl,
    eligible,
    emit,
    final_text,
    load_timeline,
    network_calls,
    papers_at,
    read_jsonl,
    stop_reason,
    tool_counts,
    usage,
)

CONFIG = EVAL / "config/refs-ltsf.yml"
GROUPS = ("C", "D", "P")  # 运行顺序：C → D → P
IMPLEMENTED = ("C", "D", "P")
CHECKPOINT = 30  # C、D 与检查点无关；回答按主检查点存放，前两个检查点取有效子集
CHECKPOINTS = (10, 20, 30)  # P 按检查点依次作答

# §10.3：题面中的 “store” 指库；C 没有库，按“所知的已发表论文”理解。说明是中性的，不鼓励也不劝阻“不知道”。
C_NOTE = (
    "No papers, store or tools are available. Answer from what you know.\n"
    'Where the question refers to "the store" or "the papers in the store", take it to\n'
    "mean the published papers on this topic that you know of."
)
# §10.1：D 只给依据段落。封闭世界（2026-10-21 确认）：材料包含这些论文对题目所问之事的全部说法，没有段落即没有说；
# 跨论文的集合题另补上库中每篇论文的主结果表（按题目切行）。
D_NOTE = (
    "No store or tools are available: the material above is all you have. Answer from these passages only.\n"
    "The passages contain every statement these papers make about what the question asks; if no passage shows a\n"
    "paper saying something, the paper does not say it."
)
D_SCOPE = (
    "The passages also include the main multivariate results tables of every paper in the store. For a question\n"
    "about one dataset only that dataset's rows are kept; where only the compared methods matter, only the table\n"
    "headers are kept."
)
D_STORE = (
    'Where the question refers to "the store" or "the papers in the store", it means the papers listed above.'
)
# §10.2：P 只有检查点上已入库的论文，用 pi 的默认工具自己找。前两句取 §7 第 3 条的说明句（只从论文作答、引用论文与
# 行号），另说明“the store”所指；断网与可用的 Python 由提示语末尾的共用环境说明交代（§7 第 5 条，``ENV_NOTE``）。
# 不列论文清单与日期，与写者组的读者一样只有论文目录。
P_NOTE = (
    "Answer only from the papers in papers/ (papers/<arXiv id with version>/paper.md; one directory per paper\n"
    "version, read-only). Cite the papers and lines your answer rests on. No store is available.\n"
    'Where the question refers to "the store" or "the papers in the store", it means these papers.'
)
# §7 第 3 条的写者组说明句，f3 定稿（10-23 用户定）：读者没有 read_source，原文只经评测侧的 read_evidence 读库中锚点
# 所在的块（f3 设计 §6）；末尾接该组的 TOOLS（tasks/hints.yml，与写者同一句）。“Do not change the store.”表达任务
# 要求，实际约束是撤掉写入工具与只读挂载。
STORE_NOTE = (  # 一行，与定稿逐字相同
    "Answer only from what the shared store records. The papers and code themselves are not available; read_evidence "
    "reads the source lines at the anchors the store records. Cite the ids, files or anchors your answer rests on. "
    "Do not change the store."
)
STORE_GROUPS = ("A0", "A2", "A3", "A3F", "A4")
# 要求引用的组带 Final answer 段时：引用写在正文，Final answer 段只放格式规定的字段（引用混进字段会使名称无法归一）。
CITE_OUTSIDE_FORMAT = "Give the citations in the body of your reply; the Final answer section holds only the fields below."
NO_TOOLS = ("--no-tools", "--no-mcp", "--no-skills", "--no-extensions", "--no-context-files", "--no-prompt-templates")


def load_config(path: Path) -> dict[str, Any]:
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    for key in ("probes_repo", "corpus_papers", "code", "workdir_root"):
        config[key] = Path(config[key]).expanduser()
    return config


def evidence_of(config: dict[str, Any]) -> Evidence:
    return Evidence(config["probes_repo"], config["corpus_papers"], config["code"])


def reader_prompt(group: str, probe: dict[str, Any], evidence: Evidence | None = None, tools: str | None = None) -> str:
    """题面原文、（D 的）依据材料、组的说明句，以及题型的 Final answer 段（要点题没有）。写者组（``STORE_GROUPS``）的
    说明句后接 ``tools``（该组的 TOOLS），与 P 一样在格式要求前说明引用放在正文、末尾接环境说明。"""
    cites = group == "P" or group in STORE_GROUPS
    if group == "C":
        parts = [probe["question"].strip(), C_NOTE]
    elif group == "D":
        if evidence is None:
            raise ValueError("group D needs the evidence material")
        scoped = probe["template"] in SCOPED and "points" not in probe["gold"]
        note = "\n".join([D_NOTE, *([D_SCOPE] if scoped else []), D_STORE])
        parts = [probe["question"].strip(), reader_material(evidence, probe), note]
    elif group == "P":
        parts = [probe["question"].strip(), P_NOTE]
    elif group in STORE_GROUPS:
        if not tools or not tools.strip():
            raise ValueError(f"group {group} needs its TOOLS sentence")
        parts = [probe["question"].strip(), f"{STORE_NOTE} {tools.strip()}"]
    else:
        raise NotImplementedError(f"group {group} is not implemented yet")
    if fmt := format_for(probe):
        if cites:
            parts.append(CITE_OUTSIDE_FORMAT)
        parts.append(fmt)
    if cites:  # 带工具的组：提示语末尾接共用的环境说明（§7 第 5 条）；C、D 不带工具，不加
        parts.append(ENV_NOTE)
    return "\n\n".join(parts) + "\n"


def select(timeline: Timeline, which: str, ids: set[str] | None, limit: int | None) -> list[tuple[str, dict[str, Any]]]:
    """（组别，题）：``main`` 为 200 道主题，``aux`` 为辅助组的代码题。"""
    groups = ("main", "aux") if which == "all" else (which,)
    chosen = [(g, p) for g in groups for p in timeline.group(g) if ids is None or p["id"] in ids]
    if ids is not None and (missing := ids - {p["id"] for _, p in chosen}):
        raise SystemExit(f"unknown probes: {sorted(missing)}")
    return chosen[:limit] if limit else chosen


def answers_file(run: Path, group: str, probe_group: str, checkpoint: int = CHECKPOINT) -> Path:
    name = f"k{checkpoint}.jsonl" if probe_group == "main" else f"k{checkpoint}-{probe_group}.jsonl"
    return run / "answers" / group / name


def answered(run: Path, group: str, probe_group: str, checkpoint: int = CHECKPOINT) -> set[tuple[str, int]]:
    return {(r["probe"], r["rep"]) for r in read_jsonl(answers_file(run, group, probe_group, checkpoint))}


def llm_of(config: dict[str, Any], group: str) -> str:
    return (config.get("llm_by_group") or {}).get(group, config["llm"])


def workers_of(config: dict[str, Any], group: str) -> int:
    runner = config["runner"]
    return (runner.get("workers_by_group") or {}).get(group, runner.get("reader_workers", 1))


def _digests(root: Path) -> dict[str, str]:
    return {str(f.relative_to(root)): hashlib.sha256(f.read_bytes()).hexdigest()
            for f in sorted(root.rglob("*")) if f.is_file()}  # fmt: skip


def papers_dir(config: dict[str, Any], timeline: Timeline, run: Path, checkpoint: int) -> tuple[Path, str]:
    """P 在检查点上的论文：当时已入库的各版本，从语料复制一份（只读挂载给读者）。返回目录与材料清单的 SHA-256。

    每篇先复制到临时目录再改名，复制中断不会留下半份论文；已有的副本逐个文件与语料比对，缺文件、多文件或内容不同
    都拒绝运行。逐文件的 SHA-256 写在 ``k<篇数>.manifest.json``，回答记录中存它的哈希。"""
    root = run / "P" / "papers"
    target = root / f"k{checkpoint}"
    wanted = papers_at(timeline, checkpoint)
    target.mkdir(parents=True, exist_ok=True)
    for leftover in target.glob(".*.partial"):  # 上次中断留下的临时目录
        shutil.rmtree(leftover)
    for paper in sorted(wanted - {p.name for p in target.iterdir()}):
        partial = target / f".{paper}.partial"
        shutil.copytree(config["corpus_papers"] / paper, partial)
        partial.rename(target / paper)
    if extra := {p.name for p in target.iterdir()} - wanted:
        raise SystemExit(f"{target} holds papers not in the store at {checkpoint}: {sorted(extra)}")
    manifest = {}
    for paper in sorted(wanted):
        have, expected = _digests(target / paper), _digests(config["corpus_papers"] / paper)
        if not expected or have != expected:
            raise SystemExit(f"{target / paper} differs from the corpus copy (missing, extra or changed files)")
        manifest |= {f"{paper}/{name}": digest for name, digest in have.items()}
    text = json.dumps(manifest, indent=1, sort_keys=True) + "\n"
    (root / f"k{checkpoint}.manifest.json").write_text(text, encoding="utf-8")
    return target, hashlib.sha256(text.encode()).hexdigest()


def box_of(config: dict[str, Any], group: str, papers: Path | None) -> Arm:
    if group == "P":  # 默认工具，断网；论文只读挂载
        return Arm("P", papers, read_only=True, isolated_llm=llm_of(config, "P"))
    return Arm(group, None, read_only=True, pi_args=NO_TOOLS)


def answer(config: dict[str, Any], run: Path, group: str, probe: dict[str, Any], rep: int, probe_group: str,
           reader: Writer, evidence: Evidence | None = None, checkpoint: int | None = None,
           papers: tuple[Path, str] | None = None) -> dict[str, Any]:  # fmt: skip
    """一题一次读者会话；C、D 不带任何工具，P 带默认工具与检查点上的论文。"""
    where = run / group / (f"k{checkpoint}" if checkpoint else "") / f"rep{rep}" / probe["id"]
    paths = Paths(where)
    if paths.root.exists():  # 中断后重跑：上次没存下回答的会话目录不留
        shutil.rmtree(paths.root)
    box = box_of(config, group, papers[0] if papers else None)
    runner = config["runner"]
    prepare(
        paths,
        box,
        model=runner["model"],
        llm=llm_of(config, group),
        thinking=runner["thinking"],
        context_window=runner["context_window"],
        idle_timeout_ms=runner.get("http_idle_timeout_ms"),
        reserve_tokens=runner["reserve_tokens"],
        max_tokens=runner.get("max_output_tokens"),
    )
    text = reader_prompt(group, probe, evidence)
    started = datetime.now(UTC).isoformat(timespec="seconds")
    result = run_session(paths, box, reader, text, timeout_s=runner["probe_timeout_min"] * 60,
                         max_tool_calls=runner.get("max_tool_calls"))
    events = paths.root / result["events"]
    material: dict[str, Any] = {"papers_manifest_sha256": papers[1]} if papers else {}
    if group == "D" and evidence is not None:
        m = evidence.material(probe)
        material = {
            "passages": [{"source": p.source, "first": p.first, "last": p.last, "role": p.role, "cut": len(p.hidden)}
                         for p in m.passages if p.role != "judge"],
            "material_sha256": hashlib.sha256(reader_material(evidence, probe).encode()).hexdigest(),
        }  # fmt: skip
    return {
        "arm": group,
        "checkpoint": checkpoint,
        "rep": rep,
        "group": probe_group,
        "probe": probe["id"],
        "template": probe["template"],
        "started": started,
        **result,
        "events": str(events.relative_to(run)),
        "session": [str((paths.root / s).relative_to(run)) for s in result["session"]],
        "llm": llm_of(config, group),
        "prompt": text,
        "answer": final_text(events),
        "stop": stop_reason(events),
        "usage": usage(events),
        "tools": tool_counts(events),
        "network": network_calls(events),
        **material,
    }


def at_checkpoint(timeline: Timeline, chosen: list[tuple[str, dict[str, Any]]],
                  checkpoint: int) -> list[tuple[str, dict[str, Any]]]:  # fmt: skip
    """``chosen`` 中在检查点上有效的题（严格规则，D31）。"""
    valid = {(g, p["id"]) for g in ("main", "aux") for p in eligible(timeline, checkpoint, g)}
    return [(g, p) for g, p in chosen if (g, p["id"]) in valid]


def run_group(config: dict[str, Any], run: Path, group: str, chosen: list[tuple[str, dict[str, Any]]],
              reps: int, timeline: Timeline, checkpoints: Sequence[int] = CHECKPOINTS) -> None:  # fmt: skip
    """C、D：一轮作答；P：按检查点依次作答，一个检查点答完再进下一个。"""
    reader = Writer("reader", timeline.reader["user"], f"{config['runner']['agent']}/{config['runner']['model']}")
    evidence = evidence_of(config) if group == "D" else None
    rounds = [(k, at_checkpoint(timeline, chosen, k)) for k in checkpoints] if group == "P" else [(None, chosen)]
    for checkpoint, probes in rounds:
        papers = papers_dir(config, timeline, run, checkpoint) if checkpoint else None
        k = checkpoint or CHECKPOINT
        done = {g: answered(run, group, g, k) for g in {g for g, _ in probes}}
        todo = [(g, p, r) for r in range(1, reps + 1) for g, p in probes if (p["id"], r) not in done[g]]
        for g in {g for g, _, _ in todo}:
            answers_file(run, group, g, k).parent.mkdir(parents=True, exist_ok=True)

        def ask(item: tuple[str, dict[str, Any], int], checkpoint: int | None = checkpoint,
                papers: tuple[Path, str] | None = papers, k: int = k) -> None:  # fmt: skip
            g, probe, rep = item
            record = answer(config, run, group, probe, rep, g, reader, evidence, checkpoint, papers)
            append_jsonl(answers_file(run, group, g, k), record)
            emit("READER", group, k=checkpoint or "-", probe=probe["id"], rep=rep, exit=record["exit"],
                 seconds=record["seconds"], chars=len(record["answer"]))  # fmt: skip

        with ThreadPoolExecutor(max_workers=workers_of(config, group)) as pool:
            list(pool.map(ask, todo))
        if checkpoint:
            emit("CHECKPOINT", group, k=checkpoint, answered=len(todo))


def reachable(url: str) -> str | None:
    parts = urlsplit(url)
    try:
        socket.create_connection((parts.hostname, parts.port or 80), timeout=5).close()
    except OSError as exc:
        return f"{url}: {exc}"
    return None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("name", help="运行名，例如 ref1")
    parser.add_argument("--groups", default="C", help="C、D、P 的任意组合，按 C → D → P 运行")
    parser.add_argument("--config", default=str(CONFIG))
    parser.add_argument("--reps", type=int, help="每题作答次数（缺省取配置）")
    parser.add_argument("--probes", choices=("main", "aux", "all"), default="all")
    parser.add_argument("--ids", help="只答这些题（逗号分隔，试跑）")
    parser.add_argument("--limit", type=int, help="只答前 N 道（试跑）")
    parser.add_argument("--llm", help="覆盖推理服务地址（所有组）")
    parser.add_argument("--checkpoints", default=",".join(map(str, CHECKPOINTS)),
                        help="P 依次作答的检查点（篇数，逗号分隔；试跑可只给一个）")
    parser.add_argument("--dry-run", action="store_true", help="只打印提示语，不调用模型")
    parser.add_argument("--allow-config-change", action="store_true",
                        help="续跑时允许生效的配置或题库提交与第一次调用不同（改动记入 run.yml）")
    args = parser.parse_args(argv)
    config_path = Path(args.config).resolve()
    config = load_config(config_path)
    if args.llm:
        config["llm"] = args.llm
        config.pop("llm_by_group", None)
    checkpoints = [int(k) for k in args.checkpoints.split(",")]
    if bad := set(checkpoints) - set(CHECKPOINTS):
        raise SystemExit(f"unknown checkpoints: {sorted(bad)}")
    if args.reps:
        config["reps"] = args.reps
    groups = [g for g in GROUPS if g in args.groups.split(",")]
    if unknown := set(args.groups.split(",")) - set(GROUPS):
        raise SystemExit(f"unknown groups: {sorted(unknown)}")
    if pending := [g for g in groups if g not in IMPLEMENTED]:
        raise SystemExit(f"groups not implemented yet: {pending}")
    timeline = load_timeline(config["probes_repo"])
    ids = set(args.ids.split(",")) if args.ids else None
    chosen = select(timeline, args.probes, ids, args.limit)
    if args.dry_run:
        for group in groups:
            evidence = evidence_of(config) if group == "D" else None
            rounds = [(k, at_checkpoint(timeline, chosen, k)) for k in checkpoints] if group == "P" else [("-", chosen)]
            for k, probes in rounds:
                for _, probe in probes:
                    text = reader_prompt(group, probe, evidence)
                    print(f"===== {group} k={k} {probe['id']} ({probe['template']})\n{text}")
        return 0
    for url in {llm_of(config, g) for g in groups}:
        if problem := reachable(url):
            raise SystemExit(f"inference service is not reachable: {problem}")
    run = config["workdir_root"] / args.name
    run.mkdir(parents=True, exist_ok=True)
    _record_run(run, config_path, config, list(argv) if argv is not None else sys.argv[1:],
                allow_change=args.allow_config_change)
    emit("RUN", "-", name=args.name, groups=",".join(groups), probes=len(chosen), reps=config["reps"], pid=os.getpid())
    failed = []
    for group in groups:
        try:
            run_group(config, run, group, chosen, config["reps"], timeline, checkpoints)
            emit("DONE", group)
        except BaseException as exc:
            emit("ERROR", group, error=f"{type(exc).__name__}: {exc}"[:500])
            traceback.print_exc()
            sys.stdout.flush()
            failed.append(group)
            break  # 按顺序运行：前一组失败就不继续
    emit("EXIT", "-", failed=",".join(failed) or "none")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "reader_prompt", "select"]
