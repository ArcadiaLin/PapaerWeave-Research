"""一次正式运行的状态，只读（监视者每次醒来先看它，不必翻日志）。

    python -m pweval.harness.status <运行名> [--config eval/config/formal-ltsf.yml] [--log <日志>]

运行进程是否还在、日志多久没有新内容、各服务是否连得上；每组的会话进度、最近一个会话、非正常退出的会话、联网的
会话、正在运行的会话（inflight）与它已运行的时长；各检查点的库版本、快照是否完整、读者答了多少。不改任何文件：
记录文件末尾正在写的半行不计入，也不截掉（与运行进程的 :func:`pweval.harness.timeline.read_jsonl` 不同）。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from . import timeline as tl


def _age(seconds: float) -> str:
    return f"{seconds / 60:.0f} min" if seconds < 7200 else f"{seconds / 3600:.1f} h"


THREAD_LIMIT = 8012  # LXC 容器的线程（pid）上限，设在容器外层，容器内看不到（用户告知）


def threads() -> str:
    """容器内当前与峰值的线程数（cgroup 的 pids.current、pids.peak），对照容器的上限。"""
    def read(name: str) -> str:
        try:
            return Path("/sys/fs/cgroup", name).read_text().strip()
        except OSError:
            return "?"

    current, peak = read("pids.current"), read("pids.peak")
    warn = " — HIGH" if current.isdigit() and int(current) > 6500 else ""
    return f"threads: {current} now, {peak} peak (container limit ~{THREAD_LIMIT}){warn}"


def report(config: dict, timeline: tl.Timeline, run: Path, log: Path) -> list[str]:
    out = [f"run {run}"]
    pids = subprocess.run(["pgrep", "-f", f"pweval.harness.timeline {run.name}( |$)"], capture_output=True, text=True)
    out.append(f"process: {'running, pid ' + ' '.join(pids.stdout.split()) if pids.stdout.strip() else 'not running'}")
    if log.exists():
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
        errors = sum(line.startswith("ERROR ") for line in lines)
        out.append(f"log {log.name}: last write {_age(time.time() - log.stat().st_mtime)} ago, {errors} ERROR lines")
        out += [f"  {line}" for line in [x for x in lines if x.split(" ", 1)[0].isupper()][-3:]]
    out.append(threads())
    arms = [a for a in tl.ARMS if a in config["arms"]]
    problems = tl.preflight(config, arms)
    out.append("services: " + ("all reachable" if not problems else "; ".join(problems)))
    sessions = tl.read_jsonl(run / "sessions.jsonl", repair=False)
    total = sum(1 for s in timeline.steps if "seq" in s)
    checkpoints = tl.checkpoints(run)
    for arm in arms:
        mine = [r for r in sessions if r["arm"] == arm]
        if not mine and arm not in checkpoints:
            out.append(f"{arm}: not started")
            continue
        line = f"{arm}: sessions {len(mine)}/{total}"
        if mine:
            last = mine[-1]
            line += f"; last seq {last['seq']} {last['type']} exit={last['exit']} {last['seconds']}s"
        out.append(line)
        odd = [f"{r['seq']}:{r['exit']}" for r in mine if r["exit"] != 0]
        if odd:
            out.append(f"  abnormal exits: {', '.join(odd)}")
        if net := [str(r["seq"]) for r in mine if r.get("network")]:
            out.append(f"  network calls in sessions: {', '.join(net)}")
        if arm == "A0" and mine and (a0 := mine[-1].get("a0")):
            out.append(f"  last session: published {a0['published']} commits"
                       + (f", not published: {a0['refused']}" if a0.get("refused") else "")
                       + (f", {len(a0['uncommitted'])} uncommitted paths" if a0.get("uncommitted") else ""))
        inflight = tl._inflight(run, arm)
        if inflight.exists():
            data = json.loads(inflight.read_text(encoding="utf-8"))
            out.append(f"  in flight: seq {data['seq']} since {data['started']} ({_age(time.time() - data['started_epoch'])})")
        for k, head in sorted((checkpoints.get(arm) or {}).items()):
            snap = run / "snapshots" / arm / f"k{k}"
            parts = [f"version {head}", f"snapshot {'ok' if tl.snapshot_complete(snap, arm) else 'missing'}"]
            for group in tl.GROUPS if k else ():
                answers = tl.read_jsonl(tl.answers_file(run, arm, k, group), repair=False)
                label = "answers" if group == "main" else group
                try:
                    parts.append(f"{label} {len(answers)}/{len(tl.eligible(timeline, k, group))}")
                except KeyError:  # 不在 plan 中的检查点（试跑时手动记的）
                    parts.append(f"{label} {len(answers)} (not a plan checkpoint)")
            out.append(f"  k{k}: " + ", ".join(parts))
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pweval.harness.status", description=__doc__.split("\n")[0])
    parser.add_argument("name", help="运行名")
    parser.add_argument("--config", default=str(tl.CONFIG))
    parser.add_argument("--log", help="运行的日志（缺省 <运行目录>/timeline.log）")
    args = parser.parse_args(argv)
    config = tl.load_config(Path(args.config))
    run = config["workdir_root"] / args.name
    if not run.exists():
        raise SystemExit(f"no run at {run}")
    timeline = tl.timeline_of(config)
    print(f"status at {datetime.now(UTC).isoformat(timespec='seconds')}")
    print("\n".join(report(config, timeline, run, Path(args.log) if args.log else run / "timeline.log")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
