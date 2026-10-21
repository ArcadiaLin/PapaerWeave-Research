"""V3 参照组的读者：C 闭卷、D 段落、P 原文（docs/designs/v3/evaluation.md §7 第 2 条、§10）。参照组没有写者，只依赖
冻结的题库、语料与模型，先于写者组运行。

    python -m pweval.harness.refs <运行名> --groups C [--reps 2] [--probes main|aux|all] [--ids <题号,…>]
        [--limit N] [--llm <服务地址>] [--config eval/config/refs-ltsf.yml] [--dry-run] [--allow-config-change]

目前实现 C 闭卷组：只给题目，不给库、原文与工具（pi ``--no-tools``）。提示语为题面、C 的说明句与题型的 Final answer
段（:mod:`pweval.protocol.final_answer`；要点题没有这一段）。D、P 待实现。

C 与库、检查点都无关，所以每题每次只答一次，第 10、20 篇检查点取其中的有效子集（严格规则，D31）。回答存在
``<运行目录>/answers/<组>/k30.jsonl``（主检验）与 ``k30-aux.jsonl``（辅助组），一题一次一行，字段与正式时间线的读者
相同（:func:`pweval.harness.timeline.answer`），另记 ``rep`` 与 ``group``。运行时不判分。

中断后用同一条命令续跑：已存的（题，次）跳过。``run.yml`` 每次调用追加一条记录（参数、生效的配置、仓库与题库的
提交、pi 版本），续跑时配置或题库的提交变了即拒绝，除非 ``--allow-config-change``。``--dry-run`` 只打印提示语，
不调用模型、不写运行目录。
"""

from __future__ import annotations

import argparse
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
from ..protocol.final_answer import format_for
from .sandbox import Arm, Paths, Writer, prepare, run_session
from .timeline import (
    Timeline,
    _record_run,
    append_jsonl,
    emit,
    final_text,
    load_timeline,
    network_calls,
    read_jsonl,
    stop_reason,
    tool_counts,
    usage,
)

CONFIG = EVAL / "config/refs-ltsf.yml"
GROUPS = ("C", "D", "P")  # 运行顺序：C → D → P
IMPLEMENTED = ("C",)
CHECKPOINT = 30  # 参照组与检查点无关；回答按主检查点存放，前两个检查点取有效子集

# §10.3：题面中的 “store” 指库；C 没有库，按“所知的已发表论文”理解。说明是中性的，不鼓励也不劝阻“不知道”。
C_NOTE = (
    "No papers, store or tools are available. Answer from what you know.\n"
    'Where the question refers to "the store" or "the papers in the store", take it to\n'
    "mean the published papers on this topic that you know of."
)
NO_TOOLS = ("--no-tools", "--no-mcp", "--no-skills", "--no-extensions", "--no-context-files", "--no-prompt-templates")


def load_config(path: Path) -> dict[str, Any]:
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    for key in ("probes_repo", "corpus_papers", "workdir_root"):
        config[key] = Path(config[key]).expanduser()
    return config


def reader_prompt(group: str, probe: dict[str, Any]) -> str:
    """题面原文、组的说明句，以及题型的 Final answer 段（要点题没有）。"""
    if group != "C":
        raise NotImplementedError(f"group {group} is not implemented yet")
    parts = [probe["question"].strip(), C_NOTE]
    if fmt := format_for(probe):
        parts.append(fmt)
    return "\n\n".join(parts) + "\n"


def select(timeline: Timeline, which: str, ids: set[str] | None, limit: int | None) -> list[tuple[str, dict[str, Any]]]:
    """（组别，题）：``main`` 为 200 道主题，``aux`` 为辅助组的代码题。"""
    groups = ("main", "aux") if which == "all" else (which,)
    chosen = [(g, p) for g in groups for p in timeline.group(g) if ids is None or p["id"] in ids]
    if ids is not None and (missing := ids - {p["id"] for _, p in chosen}):
        raise SystemExit(f"unknown probes: {sorted(missing)}")
    return chosen[:limit] if limit else chosen


def answers_file(run: Path, group: str, probe_group: str) -> Path:
    name = f"k{CHECKPOINT}.jsonl" if probe_group == "main" else f"k{CHECKPOINT}-{probe_group}.jsonl"
    return run / "answers" / group / name


def answered(run: Path, group: str, probe_group: str) -> set[tuple[str, int]]:
    return {(r["probe"], r["rep"]) for r in read_jsonl(answers_file(run, group, probe_group))}


def answer(config: dict[str, Any], run: Path, group: str, probe: dict[str, Any], rep: int, probe_group: str,
           reader: Writer) -> dict[str, Any]:  # fmt: skip
    """一题一次读者会话；C 不带任何工具。"""
    paths = Paths(run / group / f"rep{rep}" / probe["id"])
    if paths.root.exists():  # 中断后重跑：上次没存下回答的会话目录不留
        shutil.rmtree(paths.root)
    box = Arm(group, None, read_only=True, pi_args=NO_TOOLS)
    runner = config["runner"]
    prepare(
        paths,
        box,
        model=runner["model"],
        llm=config["llm"],
        thinking=runner["thinking"],
        context_window=runner["context_window"],
        idle_timeout_ms=runner.get("http_idle_timeout_ms"),
        reserve_tokens=runner["reserve_tokens"],
        max_tokens=runner.get("max_output_tokens"),
    )
    text = reader_prompt(group, probe)
    started = datetime.now(UTC).isoformat(timespec="seconds")
    result = run_session(paths, box, reader, text, timeout_s=runner["probe_timeout_min"] * 60)
    events = paths.root / result["events"]
    return {
        "arm": group,
        "checkpoint": None,
        "rep": rep,
        "group": probe_group,
        "probe": probe["id"],
        "template": probe["template"],
        "started": started,
        **result,
        "events": str(events.relative_to(run)),
        "session": [str((paths.root / s).relative_to(run)) for s in result["session"]],
        "llm": config["llm"],
        "prompt": text,
        "answer": final_text(events),
        "stop": stop_reason(events),
        "usage": usage(events),
        "tools": tool_counts(events),
        "network": network_calls(events),
    }


def run_group(config: dict[str, Any], run: Path, group: str, chosen: list[tuple[str, dict[str, Any]]],
              reps: int, user: str) -> None:  # fmt: skip
    reader = Writer("reader", user, f"{config['runner']['agent']}/{config['runner']['model']}")
    done = {g: answered(run, group, g) for g in {g for g, _ in chosen}}
    todo = [(g, p, r) for r in range(1, reps + 1) for g, p in chosen if (p["id"], r) not in done[g]]
    for g in {g for g, _, _ in todo}:
        answers_file(run, group, g).parent.mkdir(parents=True, exist_ok=True)

    def ask(item: tuple[str, dict[str, Any], int]) -> None:
        g, probe, rep = item
        record = answer(config, run, group, probe, rep, g, reader)
        append_jsonl(answers_file(run, group, g), record)
        emit("READER", group, probe=probe["id"], rep=rep, exit=record["exit"], seconds=record["seconds"],
             chars=len(record["answer"]))  # fmt: skip

    with ThreadPoolExecutor(max_workers=config["runner"].get("reader_workers", 1)) as pool:
        list(pool.map(ask, todo))


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
    parser.add_argument("--llm", help="覆盖推理服务地址")
    parser.add_argument("--dry-run", action="store_true", help="只打印提示语，不调用模型")
    parser.add_argument("--allow-config-change", action="store_true",
                        help="续跑时允许生效的配置或题库提交与第一次调用不同（改动记入 run.yml）")
    args = parser.parse_args(argv)
    config_path = Path(args.config).resolve()
    config = load_config(config_path)
    if args.llm:
        config["llm"] = args.llm
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
            for _, probe in chosen:
                print(f"===== {group} {probe['id']} ({probe['template']})\n{reader_prompt(group, probe)}")
        return 0
    if problem := reachable(config["llm"]):
        raise SystemExit(f"inference service is not reachable: {problem}")
    run = config["workdir_root"] / args.name
    run.mkdir(parents=True, exist_ok=True)
    _record_run(run, config_path, config, list(argv) if argv is not None else sys.argv[1:],
                allow_change=args.allow_config_change)
    emit("RUN", "-", name=args.name, groups=",".join(groups), probes=len(chosen), reps=config["reps"], pid=os.getpid())
    failed = []
    for group in groups:
        try:
            run_group(config, run, group, chosen, config["reps"], timeline.reader["user"])
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
