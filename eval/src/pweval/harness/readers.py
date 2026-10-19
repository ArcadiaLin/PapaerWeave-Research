"""读者探针：在检查点上，由固定的读者 Agent 回答探针，记录回答与轨迹（探针与金标准见 ``config/probes-ltsf.yml``）。

    python -m pweval.harness.readers <运行名> --checkpoint K [--arms A3,A0] [--conditions store_only] [--probes A1,C1]
        [--at-head]
    python -m pweval.harness.readers <运行名> --baselines [--probes …]        # 闭卷与神谕参照线，各探针一次，与组无关

读者是一次 pi 会话（与写者同一模型与设置），每个探针一次，彼此没有记忆。库只读：A3 的 MCP 服务只列出不写入的工具；
A0 读检查点标签处的笔记库副本（只读挂载）。两种读者条件（配置 ``probe_conditions``）：

- ``store_only``（T1 主测量）：没有论文；A3 的 ReadEvidence 只读产物文档、不读论文原文（产物文档是库的内容）。测库本身能支撑多少回答。
- ``with_papers``（辅助）：另能读论文。读者绕开库直接读论文的行为不阻止，从轨迹统计（``audit``）。

参照线没有库也没有论文：闭卷只给问题，神谕另给金标准所在的原文行，表格行前带上表的标题与表头（:func:`excerpt`）。

探针的有效范围与金标准见 :mod:`pweval.protocol.probes`。回答记入 ``<运行目录>/probes.jsonl``，判分见
:mod:`pweval.measure.grade`。

A3 的库是正在运行的图库，没有按检查点的快照：在运行中由 :mod:`pweval.harness.run` 在每个检查点、下一个写者开始之前调用，
库的状态就是检查点的状态。事后单独调用时（``--at-head``）读到的是库的当前状态，只用于试跑。
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import threading
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from ..paths import REPO
from ..protocol import source_tables
from ..protocol.config import run_config
from ..protocol.probes import CONDITIONS, PROBES, check_anchors, condition_of, eligible, load
from .sandbox import Arm, Paths, Writer, prepare, run_session

MATERIAL_PATH = re.compile(r"papers/\d{4}\.\d{4,5}")  # 原文材料的路径
_LOCK = threading.Lock()  # 各组并行时 probes.jsonl 的写入


# ---------------------------------------------------------------- 任务文本


def reader_prompt(probes: dict[str, Any], arm: str, probe: dict[str, Any], condition: str) -> str:
    reader = probes["reader"]
    store = reader["store"][condition][arm].strip()
    return reader["task"].format(store=store, question=probe["text"].strip(), claims=reader["claims"].strip())


def baseline_prompt(probes: dict[str, Any], kind: str, probe: dict[str, Any], material_root: Path) -> str:
    reader = probes["reader"]
    claims = reader["claims"].strip()
    if kind == "closed_book":
        return reader["closed_book"].format(question=probe["text"].strip(), claims=claims)
    quoted = []
    for span in probe.get("oracle", []):
        arxiv, lines_ = span.split(":")
        first, last = map(int, lines_.split("-"))
        text = (material_root / "papers" / arxiv / "paper.md").read_text(encoding="utf-8").splitlines()
        quoted.append(f"[{arxiv}, lines {first}-{last}]\n" + excerpt(text, first, last))
    return reader["oracle"].format(lines="\n\n".join(quoted), question=probe["text"].strip(), claims=claims)


def excerpt(lines: list[str], first: int, last: int) -> str:
    """原文第 ``first``–``last`` 行；落在表格中时，前面带上表的标题行与表头（到第一行数据为止），中间以 … 隔开。
    只给数据行，读者对不上列。"""
    if not lines[first - 1].startswith("|"):
        return "\n".join(lines[first - 1 : last])
    start = first - 1
    while start > 0 and lines[start - 1].startswith("|"):
        start -= 1
    head = []
    for i in range(start, first - 1):
        if any(source_tables.FLOAT.search(c) for c in lines[i].strip("|").split("|")[1:]):
            break
        head.append(lines[i])
    caption = [lines[start - 1]] if start > 0 and lines[start - 1].strip() else []
    gap = ["…"] if start + len(head) < first - 1 else []
    return "\n".join([*caption, *head, *gap, *lines[first - 1 : last]])


# ---------------------------------------------------------------- 运行


def run_probes(
    run: Path,
    config: dict[str, Any],
    probes: dict[str, Any],
    arm: str,
    k: int,
    llm: str,
    *,
    conditions: Sequence[str] | None = None,
    only: set[str] | None = None,
    at_head: bool = False,
) -> list[dict[str, Any]]:
    """检查点 ``k`` 上，组 ``arm`` 的读者在各条件下回答有效的探针。已记录的（组, 条件, 检查点, 探针）跳过。
    读者只读、互不相干，``runner.probe_workers`` 个同时进行（只缩短时间）。"""
    done = _done(run)
    jobs = []
    for condition in conditions or config.get("probe_conditions", CONDITIONS):
        sandbox_arm = _reader_arm(run, config, arm, k, condition, at_head=at_head)
        for probe in eligible(probes["probes"], config, k):
            if (only and probe["id"] not in only) or (arm, condition, k, probe["id"]) in done:
                continue
            jobs.append((condition, sandbox_arm, probe))

    def ask(condition: str, sandbox_arm: Arm, probe: dict[str, Any]) -> dict[str, Any]:
        paths = Paths(run / arm / "readers" / condition / f"cp{k}" / probe["id"])
        text = reader_prompt(probes, arm, probe, condition)
        record = _ask(paths, sandbox_arm, config, probes, text, llm)
        record = {"arm": arm, "condition": condition, "checkpoint": k, "probe": probe["id"], **record, "at_head": at_head}
        record["events"] = str((paths.root / record["events"]).relative_to(run))
        _append(run, record)
        print(f"[{arm} {condition} cp{k} {probe['id']}] {record['seconds']}s, {len(record['answer'])} chars", flush=True)
        return record

    with ThreadPoolExecutor(max_workers=config["runner"].get("probe_workers", 1)) as pool:
        return list(pool.map(lambda job: ask(*job), jobs))


def run_baselines(run: Path, config: dict[str, Any], probes: dict[str, Any], llm: str, *, only: set[str] | None = None) -> None:
    """闭卷与神谕参照线：各探针一次，金标准取完整的（最后一个检查点）。"""
    material = REPO / config["corpus"]["material_root"]
    done = _done(run)
    for kind in ("closed_book", "oracle"):
        for probe in probes["probes"]:
            if (only and probe["id"] not in only) or (kind, "none", 0, probe["id"]) in done:
                continue
            if kind == "oracle" and not probe.get("oracle"):
                continue
            paths = Paths(run / "baselines" / kind / probe["id"])
            text = baseline_prompt(probes, kind, probe, material)
            record = _ask(paths, Arm("none", None), config, probes, text, llm)
            record = {"arm": kind, "condition": "none", "checkpoint": 0, "probe": probe["id"], **record}
            record["events"] = str((paths.root / record["events"]).relative_to(run))
            _append(run, record)
            print(f"[{kind} {probe['id']}] {record['seconds']}s", flush=True)


def _reader_arm(run: Path, config: dict[str, Any], arm: str, k: int, condition: str, *, at_head: bool) -> Arm:
    with_papers = condition == "with_papers"
    if arm == "A3":
        spec = config["arms"]["A3"]
        data = run / "A3/data"
        return Arm(
            "A3",
            data / "papers" if with_papers else None,
            neo4j=spec["neo4j"],
            data=data,
            embeddings=spec.get("embeddings", True),
            read_only=True,
            # 只读库：产物文档在库中、经 ReadEvidence 读，所以不隐藏它，只不许读论文原文（2026-10-12 起；
            # 此前整个隐藏了 ReadEvidence，读者读不到产物文档）
            evidence_scope=None if with_papers else "artifacts",
        )
    # A0：检查点标签处的副本，读者改不到写者的库
    copy = run / "A0/readers" / f"cp{k}" / "store"
    if not copy.exists():
        ref = "HEAD" if at_head else f"checkpoint-{k}"
        copy.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "-q", "--no-hardlinks", str(run / "A0/store"), str(copy)], check=True)
        subprocess.run(["git", "-C", str(copy), "checkout", "-q", ref], check=True)
    from .run import papers_dir

    return Arm("A0", papers_dir(run, config, "A0") if with_papers else None, store=copy, read_only=True)


def _ask(paths: Paths, arm: Arm, config: dict[str, Any], probes: dict[str, Any], text: str, llm: str) -> dict[str, Any]:
    runner = config["runner"]
    if paths.work.exists():  # 中断后重跑：上次的会话目录不留给这一次
        shutil.rmtree(paths.root)
    from .run import pi_settings

    prepare(paths, arm, **pi_settings(config, llm))
    reader = Writer("reader", probes["reader"]["user"], f"{runner['agent']}/{runner['model']}")
    started = datetime.now(UTC).isoformat(timespec="seconds")
    result = run_session(paths, arm, reader, text, timeout_s=runner.get("probe_timeout_min", 20) * 60)
    events = paths.root / result["events"]
    return {
        "started": started,
        "exit": result["exit"],
        "seconds": result["seconds"],
        "events": result["events"],
        "llm": llm,
        "answer": answer_of(events),
        "audit": audit(events),
        "prompt": text,
    }


def answer_of(events: Path) -> str:
    """最后一条助手消息的文字。"""
    answer = ""
    if not events.exists():
        return answer
    for line in events.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = event.get("message") or {}
        if event.get("type") == "message_end" and message.get("role") == "assistant":
            text = "".join(c.get("text", "") for c in message.get("content", []) if c.get("type") == "text")
            if text.strip():
                answer = text.strip()
    return answer


def audit(events: Path) -> dict[str, Any]:
    """读者的工具调用：按工具计数；直接读原文（参数中出现 ``papers/<arXiv id>``，即材料目录；A0 笔记库中的
    ``store/papers/*.md`` 是笔记，不算）的调用另计，即绕开库的读取。被拒绝的调用（如只读库条件下隐藏的工具）也计入。"""
    tools: dict[str, int] = {}
    papers = 0
    if not events.exists():
        return {"tools": tools, "paper_reads": papers}
    for line in events.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = event.get("message") or {}
        if event.get("type") != "message_end" or message.get("role") != "assistant":
            continue
        for call in message.get("content", []):
            if call.get("type") != "toolCall":
                continue
            name = call["name"].removeprefix("mcp__PaperWeave__")
            tools[name] = tools.get(name, 0) + 1
            if not name[:1].isupper() and MATERIAL_PATH.search(json.dumps(call.get("arguments", {}))):
                papers += 1  # 内置工具（read、bash 等）读论文；MCP 工具名大写开头，经库读取
    return {"tools": tools, "paper_reads": papers}


def _append(run: Path, record: dict[str, Any]) -> None:
    with _LOCK, open(run / "probes.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _done(run: Path) -> set[tuple[str, str, int, str]]:
    path = run / "probes.jsonl"
    if not path.exists():
        return set()
    records = map(json.loads, path.read_text(encoding="utf-8").splitlines())
    return {(r["arm"], condition_of(r), r["checkpoint"], r["probe"]) for r in records}


def main(argv: Sequence[str] | None = None) -> int:
    from .run import _llm_url

    parser = argparse.ArgumentParser(prog="python -m pweval.harness.readers", description=__doc__.split("\n\n")[0])
    parser.add_argument("name", help="运行名（<workdir_root>/<运行名>/）")
    parser.add_argument("--config", default=str(REPO / "eval/config/pilot-ltsf.yml"))
    parser.add_argument("--probes-file", default=str(PROBES))
    parser.add_argument("--arms", default="A3,A0")
    parser.add_argument("--checkpoint", type=int)
    parser.add_argument("--conditions", help=f"读者条件，逗号分隔；缺省取配置的 probe_conditions，或 {','.join(CONDITIONS)}")
    parser.add_argument("--probes", help="只跑这些探针，逗号分隔")
    parser.add_argument("--baselines", action="store_true", help="闭卷与神谕参照线")
    parser.add_argument("--at-head", action="store_true", help="读库的当前状态而不是检查点（试跑用）")
    args = parser.parse_args(argv)
    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    probes = load(Path(args.probes_file))
    problems = check_anchors(probes, REPO / config["corpus"]["material_root"])
    if problems:
        raise SystemExit("probe gold does not match the papers:\n" + "\n".join(problems))
    run = Path(config["runner"]["workdir_root"]).expanduser() / args.name
    config = run_config(run, config)
    only = set(args.probes.split(",")) if args.probes else None
    llm = _llm_url(config["runner"]["model"])
    if args.baselines:
        run_baselines(run, config, probes, llm, only=only)
        return 0
    if args.checkpoint is None:
        parser.error("give --checkpoint or --baselines")
    for arm in args.arms.split(","):
        conditions = args.conditions.split(",") if args.conditions else None
        arm_llm = (config["runner"].get("endpoints") or {}).get(arm, llm)
        run_probes(run, config, probes, arm, args.checkpoint, arm_llm, conditions=conditions, only=only, at_head=args.at_head)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
