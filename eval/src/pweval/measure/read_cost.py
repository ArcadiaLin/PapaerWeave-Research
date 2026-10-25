"""读取成本的拆解（f4 设计第 3 节，F4-0）：从读者的事件流逐题抽出模型调用与工具调用，写成三张表。

    python -m pweval.measure.read_cost f3:A3 f3:A0 ref1:P [--checkpoints 10,20,30] [--out 目录]

只读已有的回答记录（``<运行>/answers/<组>/k<K>.jsonl``，不含辅助题）与其中登记的事件流，不连库、不调用推理服务。
默认写到 ``~/pw-lab/runs/f3/analysis/f4-0/``：

- ``calls.csv``：每次模型调用一行，usage 原样（pi 的 input 不含命中缓存的部分，cacheRead 另计；提示 token 为两者
  之和），``later`` 为它的输出在之后多少次调用中仍在上下文里（到下一次成功的压缩为止）。
- ``tools.csv``：每次工具调用一行：规范化的工具名（去掉 MCP 服务前缀）、bash 命令的归类、返回的字符数、是否出错、
  ``later``（返回在之后多少次调用中仍在上下文里）、估计的 token 数及其来源（``token_source``）。
- ``sessions.csv``：每题一行：用时、结束原因、调用与 token 合计、第一次调用的提示 token、题面字符数、定位成本
  （第一次成功的 read_evidence 之前的模型调用次数，没有调用过为空）、压缩次数，以及驻留成本的拆分。
- ``meta.yml``：输入文件的哈希、代码版本、各组的字符/token 比例、行数。

驻留成本：一段内容进入上下文后，之后每次模型调用都把它算进提示 token。每题的提示 token 总和拆为

- ``occ_prefix``：第一次调用的提示（系统提示、工具定义、题面）乘以调用次数；
- ``occ_output``：每次助手输出（usage 的 output，含思考；读者会话只有一条用户消息，按模型的 chat template
  思考内容留在上下文中）乘以它的 ``later``；
- ``occ_tools``：每次工具返回的估计 token 乘以它的 ``later``，tools.csv 中逐条可按工具汇总；
- ``occ_residual``：其余（模板标记、压缩摘要、估计误差）。

工具返回的 token 数逐步分摊：相邻两次调用之间提示 token 的增量减去上一次的输出，是这一步新加入的工具返回的
token 数，按字符数分给这一步的各次返回（只有一次返回的步骤即为它的 token 数；``token_source`` 为 ``step``）。
算不出增量的步骤（跨压缩、增量不为正、其后没有调用）按字符数除以该组的比例估计（``ratio``）；比例在该组全部
可分摊的步骤上校准：返回字符数之和除以 token 数之和。表格中的数字切成的 token 多，统一的比例会在工具之间错配，
所以只作后备。

核对（不通过即报错）：每题的调用数与 token 合计、各工具的调用次数与回答记录相同；同一检查点各组的题号集合相同。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from ..paths import REPO

RUNS = Path.home() / "pw-lab/runs"
OUT = RUNS / "f3/analysis/f4-0"

# bash 命令的归类：管道（|、&&、;、换行）中第一个认得的命令决定类别，记为 bash:<类别>，与工具名（search、read 等）分开
CATEGORIES = {
    "search": {"grep", "egrep", "fgrep", "rg", "ag"},
    "read": {"cat", "head", "tail", "sed", "less", "more", "nl"},
    "list": {"ls", "find", "tree", "wc", "du", "stat"},
    "script": {"python", "python3", "awk", "jq", "perl", "yq"},
    "git": {"git"},
}
CATEGORY = {word: cat for cat, words in CATEGORIES.items() for word in words}
SEGMENT = re.compile(r"\|\||&&|[|;\n]")
LEAD = {"do", "then", "else", "{", "(", "time", "sudo", "xargs", "!"}
EVIDENCE = "read_evidence"


def bash_category(command: str) -> str:
    for segment in SEGMENT.split(command):
        words = segment.strip().split()
        while words and (words[0] in LEAD or "=" in words[0] and not words[0].startswith("-")):
            words = words[1:]
        if words:
            word = words[0].rsplit("/", 1)[-1]
            if word in CATEGORY:
                return f"bash:{CATEGORY[word]}"
    return "bash:other"


def tool_name(name: str) -> str:
    """``mcp__PaperWeave__search`` → ``search``；pi 的内置工具名不变。"""
    return name.rsplit("__", 1)[-1]


def _text(content: Any) -> str:
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except json.JSONDecodeError:
            return content
    if isinstance(content, list):
        return "".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text")
    return ""


# ---------------------------------------------------------------- 一题的轨迹


@dataclass
class Tool:
    call: int  # 发出它的模型调用（从 1 起）
    seq: int  # 会话中的第几次工具调用（从 1 起）
    name: str
    raw_name: str
    category: str
    command: str
    chars: int = 0
    error: bool = False
    answered: bool = False
    later: int = 0
    step_tokens: float | None = None  # 逐步分摊得到的 token 数；算不出时为 None


@dataclass
class Call:
    n: int
    input: int
    cache_read: int
    output: int
    stop: str | None
    tools: int
    compacted_before: bool
    later: int = 0

    @property
    def prompt(self) -> int:
        return self.input + self.cache_read


@dataclass
class Trace:
    question_chars: int = 0
    calls: list[Call] = field(default_factory=list)
    tools: list[Tool] = field(default_factory=list)
    compactions: int = 0
    raw_tools: Counter = field(default_factory=Counter)


def parse(events: Path) -> Trace:
    trace = Trace()
    by_id: dict[str, Tool] = {}
    compacted = False
    for line in events.open(encoding="utf-8"):
        event = json.loads(line)
        kind = event.get("type")
        if kind == "compaction_end":
            if not event.get("aborted") and not event.get("errorMessage"):
                compacted = True
                trace.compactions += 1
            continue
        if kind != "message_end":
            continue
        message = event.get("message") or {}
        role = message.get("role")
        if role == "user" and not trace.question_chars:
            trace.question_chars = len(_text(message.get("content")))
        elif role == "assistant":
            usage = message.get("usage") or {}
            issued = [c for c in message.get("content", []) if c.get("type") == "toolCall"]
            call = Call(len(trace.calls) + 1, int(usage.get("input") or 0), int(usage.get("cacheRead") or 0),
                        int(usage.get("output") or 0), message.get("stopReason"), len(issued), compacted)  # fmt: skip
            compacted = False
            trace.calls.append(call)
            for c in issued:
                name = tool_name(c["name"])
                args = c.get("arguments") or {}
                command = args.get("command", "") if name == "bash" else json.dumps(args, ensure_ascii=False)
                tool = Tool(call.n, len(trace.tools) + 1, name, c["name"],
                            bash_category(command) if name == "bash" else name, command[:300])  # fmt: skip
                trace.tools.append(tool)
                trace.raw_tools[c["name"]] += 1
                by_id[c["id"]] = tool
        elif role == "toolResult":
            tool = by_id.get(message.get("toolCallId"))
            if tool is not None:
                tool.chars = len(_text(message.get("content")))
                tool.error = bool(message.get("isError"))
                tool.answered = True
    # later：内容在之后多少次调用中仍在上下文里，到下一次成功的压缩为止
    for i, call in enumerate(trace.calls):
        later = 0
        for nxt in trace.calls[i + 1 :]:
            if nxt.compacted_before:
                break
            later += 1
        call.later = later
    for tool in trace.tools:
        tool.later = trace.calls[tool.call - 1].later
    return trace


def allocate(trace: Trace) -> tuple[int, int]:
    """逐步分摊工具返回的 token（写进 ``Tool.step_tokens``）；返回可分摊步骤的（返回字符数, token 数），用于校准比例。"""
    chars = tokens = 0
    for prev, nxt in zip(trace.calls, trace.calls[1:]):
        if nxt.compacted_before:
            continue
        step = [t for t in trace.tools if t.call == prev.n]
        added = sum(t.chars for t in step)
        delta = nxt.prompt - prev.prompt - prev.output
        if added > 0 and delta > 0:
            chars += added
            tokens += delta
            for t in step:
                t.step_tokens = delta * t.chars / added
    return chars, tokens


# ---------------------------------------------------------------- 各组


@dataclass
class Session:
    run: str
    arm: str
    k: int
    record: dict[str, Any]
    trace: Trace


def load(run: str, arm: str, k: int) -> tuple[list[Session], Path]:
    path = RUNS / run / "answers" / arm / f"k{k}.jsonl"
    sessions = []
    for line in path.open(encoding="utf-8"):
        record = json.loads(line)
        if record.get("group") != "main":
            raise ValueError(f"{path}: {record['probe']} is in group {record.get('group')}")
        trace = parse(RUNS / run / record["events"])
        check(record, trace, path)
        sessions.append(Session(run, arm, k, record, trace))
    return sessions, path


def check(record: dict[str, Any], trace: Trace, path: Path) -> None:
    got = {"calls": len(trace.calls), "input": sum(c.input for c in trace.calls),
           "cacheRead": sum(c.cache_read for c in trace.calls), "output": sum(c.output for c in trace.calls)}  # fmt: skip
    want = {key: record["usage"][key] for key in got}
    if got != want:
        raise ValueError(f"{path}: {record['probe']}: usage {got} != answer record {want}")
    if dict(trace.raw_tools) != record["tools"]:
        raise ValueError(f"{path}: {record['probe']}: tools {dict(trace.raw_tools)} != answer record {record['tools']}")


def rows(session: Session, ratio: float) -> tuple[list[dict], list[dict], dict]:
    r, t = session.record, session.trace
    key = {"arm": session.arm, "k": session.k, "probe": r["probe"], "template": r["template"]}
    calls = [key | {"call": c.n, "input": c.input, "cache_read": c.cache_read, "prompt": c.prompt, "output": c.output,
                    "later": c.later, "tools": c.tools, "compacted_before": int(c.compacted_before), "stop": c.stop}
             for c in t.calls]  # fmt: skip
    tools = []
    for tool in t.tools:
        source = "ratio" if tool.step_tokens is None else "step"
        tokens = round(tool.chars / ratio if tool.step_tokens is None else tool.step_tokens)
        tools.append(key | {"call": tool.call, "seq": tool.seq, "tool": tool.name, "raw_tool": tool.raw_name,
                            "category": tool.category, "chars": tool.chars, "error": int(tool.error),
                            "answered": int(tool.answered), "later": tool.later, "est_tokens": tokens, "token_source": source,
                            "occupancy": tokens * tool.later, "command": tool.command})  # fmt: skip
    evidence = next((tool.call for tool in t.tools if tool.name == EVIDENCE and tool.answered and not tool.error), None)
    total = sum(c.prompt for c in t.calls)
    prefix = t.calls[0].prompt if t.calls else 0
    occ_prefix = prefix * len(t.calls)
    occ_output = sum(c.output * c.later for c in t.calls)
    occ_tools = sum(row["occupancy"] for row in tools)
    session_row = key | {
        "run": session.run, "seconds": r["seconds"], "stop": r.get("stop"), "calls": len(t.calls),
        "tool_calls": len(t.tools), "input": sum(c.input for c in t.calls),
        "cache_read": sum(c.cache_read for c in t.calls), "output": sum(c.output for c in t.calls),
        "prompt_total": total, "prompt_first": prefix, "question_chars": t.question_chars,
        "calls_before_evidence": None if evidence is None else evidence - 1, "compactions": t.compactions,
        "occ_prefix": occ_prefix, "occ_output": occ_output, "occ_tools": occ_tools,
        "occ_residual": total - occ_prefix - occ_output - occ_tools,
    }  # fmt: skip
    return calls, tools, session_row


def write_csv(path: Path, table: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(table[0]))
        writer.writeheader()
        writer.writerows(table)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _code() -> dict[str, Any]:
    head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "--", "eval/src/pweval/measure/read_cost.py"],
                           capture_output=True, text=True).stdout.strip()  # fmt: skip
    return {"commit": head, "read_cost_dirty": bool(dirty), "read_cost_sha256": _sha256(Path(__file__))}


def measure(arms: list[tuple[str, str]], checkpoints: list[int], out: Path) -> dict[str, Any]:
    loaded: dict[str, list[Session]] = {}
    inputs: dict[str, str] = {}
    for run, arm in arms:
        for k in checkpoints:
            sessions, path = load(run, arm, k)
            loaded.setdefault(arm, []).extend(sessions)
            inputs[str(path)] = _sha256(path)
    for k in checkpoints:
        sets = {arm: sorted(s.record["probe"] for s in ss if s.k == k) for arm, ss in loaded.items()}
        if len({tuple(v) for v in sets.values()}) != 1:
            raise ValueError(f"k{k}: probe sets differ across arms: { {a: len(v) for a, v in sets.items()} }")
    ratios = {}
    for arm, sessions in loaded.items():
        chars = tokens = 0
        for s in sessions:
            c, t = allocate(s.trace)
            chars, tokens = chars + c, tokens + t
        ratios[arm] = round(chars / tokens, 4)
    calls, tools, sessions_rows = [], [], []
    for arm, sessions in loaded.items():
        for s in sorted(sessions, key=lambda s: (s.k, s.record["probe"])):
            c, t, row = rows(s, ratios[arm])
            calls += c
            tools += t
            sessions_rows.append(row)
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "calls.csv", calls)
    write_csv(out / "tools.csv", tools)
    write_csv(out / "sessions.csv", sessions_rows)
    meta = {
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "arms": [f"{run}:{arm}" for run, arm in arms], "checkpoints": checkpoints,
        "code": _code(), "inputs": inputs, "chars_per_token": ratios,
        "rows": {"calls": len(calls), "tools": len(tools), "sessions": len(sessions_rows)},
    }  # fmt: skip
    (out / "meta.yml").write_text(yaml.safe_dump(meta, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return meta


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pweval.measure.read_cost", description=__doc__.split("\n\n")[0])
    parser.add_argument("arms", nargs="+", help="<运行名>:<组>，如 f3:A3 f3:A0 ref1:P")
    parser.add_argument("--checkpoints", default="10,20,30")
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)
    arms = [tuple(a.split(":", 1)) for a in args.arms]
    meta = measure(arms, [int(k) for k in args.checkpoints.split(",")], Path(args.out).expanduser())  # type: ignore[arg-type]
    print(f"{meta['rows']} chars/token {meta['chars_per_token']} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
