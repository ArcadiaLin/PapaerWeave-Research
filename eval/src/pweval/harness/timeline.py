"""V3 正式时间线的一次运行：建立四组的起点（种子），按题库的会话序列逐个运行写者会话，在检查点记下库的版本。

    python -m pweval.harness.timeline <运行名> [--config eval/config/formal-ltsf.yml] [--arms A3,A2,A0,A4]
        [--until <序号>] [--neo4j A3=bolt://…,A2=…] [--reset]

会话序列、身份与任务文字由题库仓库（``probes_repo``）给出，各组相同（tmps/probes/writer-tasks.md）：

- ``tasks/plan.yml``：70 个会话与三个检查点，按顺序；每个会话有身份、类型与任务文字；
- ``tasks/identities.yml``：10 个写者身份（登录身份与背景，背景接在任务之前）；
- ``tasks/hints.yml``：任务文字中 ``{WRITE}`` 与 ``{TOOLS}`` 的逐组原文；
- ``tasks/reader.yml``、``probes/sample.yml``：检查点上的读者与 200 道题（严格规则：金标准依赖的论文全部入库才作答）；
- ``seed/``：起点。A3、A2 由系统的命令行重放两次提交（锚点与种子论文；三张排行榜），A0 是 ``seed/a0/store``
  的文件分两次 git 提交，A4 是 ``seed/a4/episodes.yaml`` 的 30 条记忆，经 Graphiti 的 MCP 服务逐条写入。

运行目录 ``<workdir_root>/<运行名>/``：

- ``run.yml``：配置，以及每次调用的时间、参数、仓库与题库的提交、pi 的版本；
- ``sessions.jsonl``：每个会话一行（组、序号、类型、身份、退出码、用时、事件流与会话记录、会话前后的库版本、
  联网的命令；A0 另记会话结束时没有提交的改动——留在工作区，下一位写者会看到，不替它提交）；
- ``checkpoints.yml``：各组每个检查点（0、10、20、30 篇）的库版本；
- ``answers/<组>/k<篇数>.jsonl``：检查点上读者的回答，一题一行（题号、题面原文、回答原文、库版本、事件流与会话记录、
  用时、token、工具调用、联网命令）。运行时不判分，全部运行结束后按题号对回冻结的金标准统一判分；
- ``<组>/``：A3、A2 的材料根目录 ``data/``（论文副本与产物文档）；A0 的共享仓库 ``repo/``；各组的论文副本与
  代码副本；``writers/<身份>/``：写者的沙箱目录（:mod:`pweval.harness.sandbox`）。

论文副本起初没有三篇论文的新版本，版本更新的会话开始前才放进去；代码副本同样（新版本对应的固定 commit）。

各组的存储互不相干，组内按序号逐个运行（写者轮流写；到检查点时写者暂停，读者答完再继续），各组同时运行。中断后用同一个运行名重跑，已记录的会话
跳过。评测代码不导入被测系统：A3、A2 的库只经命令行、MCP 与 Cypher 读取接触。
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

from ..paths import EVAL, REPO
from . import export
from .mcp_client import HttpClient
from .sandbox import GRAPH, Arm, Paths, Writer, pi_version, prepare, run_session

CONFIG = EVAL / "config/formal-ltsf.yml"
A0_KIT = EVAL / "baselines/a0"  # A0 的约定（AGENTS.md）与模板，内容与 A3 的工具说明、空白模板对等
ARMS = ("A3", "A2", "A0", "A4")
PROTECTED = {7687, 7688}  # 不清空的图库端口
SEED_USER = "seed"
SEED_MESSAGES = (  # 与 seed/README.md 相同，各组一致
    "seed: identity anchors (tasks, datasets) and the seed papers Informer and SCINet",
    "seed: leaderboards for ETTh1, Electricity and ETTh2 with the seed papers rows",
)
A4_WRITE_TOOLS = tuple(f"mcp__Graphiti__{t}" for t in  # A4 读者看不到的 Graphiti 工具（写入与删除）
                       ("add_memory", "add_triplet", "delete_episode", "delete_entity_edge", "build_communities"))
SEED_BOARDS = ("02-lb-etth1.md", "03-lb-electricity.md", "04-lb-etth2.md")
NETWORK = re.compile(r"\b(curl|wget|git\s+(clone|fetch|pull|ls-remote)|pip3?\s+install|uv\s+(pip|add)|https?://)")
_LOCK = threading.Lock()


# ---------------------------------------------------------------- 配置与会话序列


@dataclass(frozen=True)
class Timeline:
    steps: list[dict[str, Any]]  # plan.yml：会话（有 seq）与检查点（type: checkpoint）
    identities: dict[str, dict[str, Any]]
    hints: dict[str, dict[str, str]]  # 组（小写）→ {WRITE, TOOLS}
    reader: dict[str, Any]  # tasks/reader.yml：读者的登录身份、提示语、种子中的论文
    probes: list[dict[str, Any]]  # probes/sample.yml 的 200 题，题面与金标准取自 auto.yml、manual-rendered.yml

    @property
    def later_versions(self) -> dict[str, str]:
        """版本更新会话带来的新版本 → 它所替换的早期版本。"""
        return {s["paper"]: s["from"] for s in self.steps if s.get("type") == "update"}


def load_config(path: Path) -> dict[str, Any]:
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    for key in ("probes_repo", "corpus_papers", "code", "workdir_root"):
        config[key] = Path(config[key]).expanduser()
    if log := config["arms"].get("A4", {}).get("graphiti_log"):
        config["arms"]["A4"]["graphiti_log"] = Path(log).expanduser()
    return config


def load_timeline(probes: Path) -> Timeline:
    steps = yaml.safe_load((probes / "tasks/plan.yml").read_text(encoding="utf-8"))
    identities = {i["id"]: i for i in yaml.safe_load((probes / "tasks/identities.yml").read_text(encoding="utf-8"))}
    hints = yaml.safe_load((probes / "tasks/hints.yml").read_text(encoding="utf-8"))
    reader = yaml.safe_load((probes / "tasks/reader.yml").read_text(encoding="utf-8"))
    pool = {}
    for name in ("auto.yml", "manual-rendered.yml"):
        pool |= {p["id"]: p for p in yaml.safe_load((probes / "probes" / name).read_text(encoding="utf-8"))}
    sample = yaml.safe_load((probes / "probes/sample.yml").read_text(encoding="utf-8"))
    return Timeline(steps, identities, hints, reader, [pool[p["id"]] for p in sample])


def papers_at(timeline: Timeline, papers: int) -> set[str]:
    """检查点 ``papers`` 时库中应有的论文版本：种子，加上这个检查点之前各会话建库与更新的论文。"""
    present = set(timeline.reader["seed_papers"])
    for step in timeline.steps:
        if step["type"] == "checkpoint" and step["papers"] == papers:
            return present
        if step["type"] in ("build", "update"):
            present.add(step["paper"])
    raise KeyError(f"no checkpoint at {papers} papers")


def eligible(timeline: Timeline, papers: int) -> list[dict[str, Any]]:
    """严格规则（D31）：金标准依赖的论文（``requires``）全部入库的题，金标准不按检查点重算。"""
    present = papers_at(timeline, papers)
    return [p for p in timeline.probes if set(p["requires"]) <= present]


def reader_prompt(timeline: Timeline, arm: str, probe: dict[str, Any]) -> str:
    return timeline.reader["prompt"].format(question=probe["question"].strip(), TOOLS=timeline.hints[arm.lower()]["TOOLS"])


def prompt(timeline: Timeline, arm: str, step: dict[str, Any]) -> str:
    """身份背景 + 任务文字（``{WRITE}`` 按会话的产物类型、``{TOOLS}`` 按组替换）。"""
    hint = timeline.hints[arm.lower()]
    task = step["task"].replace("{WRITE}", hint["WRITE"].format(type=step.get("writes", "")))
    task = task.replace("{TOOLS}", hint["TOOLS"])
    if "{" in task:
        raise ValueError(f"unfilled placeholder in session {step['seq']}: {task}")
    return f"{timeline.identities[step['identity']]['background'].strip()}\n\n{task.strip()}\n"


def writer_of(config: dict[str, Any], identity: dict[str, Any]) -> Writer:
    runner = config["runner"]
    return Writer(identity["id"], identity["user"], f"{runner['agent']}/{runner['model']}")


# ---------------------------------------------------------------- 各组的目录与材料


def arm_dir(run: Path, arm: str) -> Path:
    return run / arm


def papers_of(run: Path, arm: str) -> Path:
    """组的论文副本：A3、A2 在材料根目录下（MCP 服务与写者看到同一份），其余组单独一份。"""
    return arm_dir(run, arm) / ("data/papers" if arm in GRAPH else "papers")


def copy_papers(config: dict[str, Any], target: Path, arxivs: list[str]) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for arxiv in arxivs:
        if not (target / arxiv).exists():
            shutil.copytree(config["corpus_papers"] / arxiv, target / arxiv)


def code_rows(source: Path) -> tuple[str, list[tuple[str, set[str], str]]]:
    """code/README.md 拆成表头与各行：(目录名, 对应的论文版本, 原行)。"""
    head, rows = [], []
    for line in (source / "README.md").read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip("|").split("|")]
        if line.startswith("| ") and cells[0].endswith("/") and "@" in cells[0]:
            rows.append((cells[0].rstrip("/"), {v.strip() for v in cells[-1].split(",")}, line))
        else:
            head.append(line)
    return "\n".join(head) + "\n", rows


def sync_code(config: dict[str, Any], target: Path, hidden: set[str]) -> None:
    """组的代码副本：只对应 ``hidden`` 中论文版本的仓库先不放（版本更新时再放），README 只列放进来的。"""
    head, rows = code_rows(config["code"])
    shown = [(name, line) for name, versions, line in rows if not versions <= hidden]
    target.mkdir(parents=True, exist_ok=True)
    for name, _ in shown:
        if not (target / name).exists():
            shutil.copytree(config["code"] / name, target / name)
    (target / "README.md").write_text(head + "\n".join(line for _, line in shown) + "\n", encoding="utf-8")


def bring_version(config: dict[str, Any], timeline: Timeline, run: Path, arm: str, new: str) -> None:
    """版本更新会话之前：新版本的论文与代码此刻才出现在组的副本中。"""
    copy_papers(config, papers_of(run, arm), [new])
    done = {s["paper"] for s in timeline.steps if s.get("type") == "update" and _recorded(run, arm, s["seq"])}
    sync_code(config, arm_dir(run, arm) / "code", set(timeline.later_versions) - done - {new})


# ---------------------------------------------------------------- 起点


def setup(config: dict[str, Any], timeline: Timeline, run: Path, arm: str, *, reset: bool) -> None:
    """组的起点：论文与代码副本，以及种子。已记录检查点 0 的组不再建立。"""
    later = set(timeline.later_versions)
    initial = sorted(p.name for p in config["corpus_papers"].iterdir() if p.is_dir() and p.name not in later)
    copy_papers(config, papers_of(run, arm), initial)
    sync_code(config, arm_dir(run, arm) / "code", later)
    seed = config["probes_repo"] / "seed"
    if arm in GRAPH:
        _seed_graph(config, run, arm, seed, reset=reset)
    elif arm == "A0":
        _seed_a0(run, seed)
    else:
        _seed_a4(config, seed)


def _system_env(config: dict[str, Any], run: Path, arm: str) -> dict[str, str]:
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": str(Path.home()),
        "PAPERWEAVE_NEO4J_URI": config["arms"][arm]["neo4j"],
        "PAPERWEAVE_DATA": str(arm_dir(run, arm) / "data"),
    }


def _seed_graph(config: dict[str, Any], run: Path, arm: str, seed: Path, *, reset: bool) -> None:
    uri = config["arms"][arm]["neo4j"]
    with export.driver(uri) as d:
        nodes = d.execute_query("MATCH (n) RETURN count(n) AS n").records[0]["n"]
        if nodes:
            if not reset:
                raise SystemExit(f"{arm}: {uri} holds {nodes} nodes; pass --reset to clear it for this run")
            if urlsplit(uri).port in PROTECTED:
                raise SystemExit(f"refusing to clear {uri}")
            while d.execute_query("MATCH (n) WITH n LIMIT 5000 DETACH DELETE n RETURN count(*) AS c").records[0]["c"]:
                pass
    work = arm_dir(run, arm) / "seed-work"  # 草稿不能放在材料根目录下
    work.mkdir(parents=True, exist_ok=True)
    for name in SEED_BOARDS:
        shutil.copy(seed / name, work / name)
    python = [str(REPO / ".venv/bin/python"), "-m", "paperweave", "--user", SEED_USER]
    env = _system_env(config, run, arm)
    files = ", ".join(SEED_BOARDS)
    for args in (
        ["--apply", "--message", SEED_MESSAGES[0], str(seed / "01-seed.yaml")],
        ["-e", f'{{op: commit, files: [{files}], message: "{SEED_MESSAGES[1]}"}}'],
    ):
        done = subprocess.run([*python, *args], cwd=work, env=env, capture_output=True, text=True)
        if done.returncode != 0 or "status: committed" not in done.stdout:
            raise SystemExit(f"{arm}: seeding failed:\n{done.stdout[-2000:]}\n{done.stderr[-2000:]}")
    if (head := export.head(uri)) != "commit_000002":
        raise SystemExit(f"{arm}: the seed should end at commit_000002, the store is at {head}")


def _git(repo: Path, *args: str, user: str | None = None) -> str:
    env = {"PATH": "/usr/bin:/bin", "HOME": str(repo)}
    if user:
        env |= {"GIT_AUTHOR_NAME": user, "GIT_AUTHOR_EMAIL": user, "GIT_COMMITTER_NAME": user,
                "GIT_COMMITTER_EMAIL": user}  # fmt: skip
    return subprocess.run(["git", "-C", str(repo), *args], env=env, check=True, capture_output=True, text=True).stdout


def _seed_a0(run: Path, seed: Path) -> None:
    """共享仓库：约定与模板（setup 提交），种子的节点文件与排行榜各一次提交（作者 seed，说明与 A3 相同）。"""
    repo = arm_dir(run, "A0") / "repo"
    if repo.exists():
        shutil.rmtree(repo)  # 没有记录检查点 0：上次建到一半
    repo.mkdir(parents=True)
    shutil.copy(A0_KIT / "AGENTS.md", repo / "AGENTS.md")
    shutil.copytree(A0_KIT / "templates", repo / "templates")
    (repo / ".gitignore").write_text("papers/\ncode/\n", encoding="utf-8")  # 论文与代码是挂载进来的副本
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "Set up the shared repository", user="setup")
    store = seed / "a0/store"
    for part, message in zip(("nodes", "artifacts"), SEED_MESSAGES, strict=True):
        shutil.copytree(store / part, repo / "store" / part)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", message, user=SEED_USER)


def _seed_a4(config: dict[str, Any], seed: Path) -> None:
    """30 条种子记忆逐条写入 Graphiti，每条之后等它处理完（服务按 group 串行处理排队的记忆）。"""
    spec = config["arms"]["A4"]
    episodes = yaml.safe_load((seed / "a4/episodes.yaml").read_text(encoding="utf-8"))
    with HttpClient(spec["graphiti"]) as client:
        for e in episodes:
            reply = client.call("add_memory", {**e, "group_id": spec["group_id"]})
            if "error" in reply.lower():
                raise SystemExit(f"A4: add_memory failed for {e['name']!r}: {reply}")
            settle(config)


def settle(config: dict[str, Any], limit_s: int = 3600) -> None:
    """等 Graphiti 处理完排队的记忆：服务日志 ``settle_quiet_s`` 秒没有新内容。"""
    log, quiet = config["arms"]["A4"]["graphiti_log"], config["runner"]["settle_quiet_s"]
    time.sleep(5)
    start = time.time()
    while time.time() - start < limit_s:
        if time.time() - log.stat().st_mtime >= quiet:
            return
        time.sleep(5)
    raise RuntimeError(f"Graphiti did not settle within {limit_s}s")


# ---------------------------------------------------------------- 会话


def sandbox_arm(config: dict[str, Any], run: Path, arm: str) -> Arm:
    spec = config["arms"][arm]
    papers, code = papers_of(run, arm), arm_dir(run, arm) / "code"
    if arm in GRAPH:
        data = arm_dir(run, arm) / "data"
        return Arm(arm, papers, code=code, neo4j=spec["neo4j"], data=data, ablate=tuple(spec.get("ablate") or ()))
    if arm == "A0":
        return Arm("A0", papers, code=code, store=arm_dir(run, "A0") / "repo")
    return Arm("A4", papers, code=code, graphiti=spec["graphiti"])


def version(config: dict[str, Any], run: Path, arm: str) -> str | None:
    """库的版本：A3、A2 为分支头的提交 id，A0 为仓库的 HEAD；A4 没有版本，记时刻。"""
    if arm in GRAPH:
        return export.head(config["arms"][arm]["neo4j"])
    if arm == "A0":
        return _git(arm_dir(run, "A0") / "repo", "rev-parse", "HEAD").strip()
    return datetime.now(UTC).isoformat(timespec="seconds")


def session(config: dict[str, Any], timeline: Timeline, run: Path, arm: str, step: dict[str, Any]) -> dict[str, Any]:
    writer = writer_of(config, timeline.identities[step["identity"]])
    box = sandbox_arm(config, run, arm)
    paths = Paths(arm_dir(run, arm) / "writers" / writer.id)
    runner = config["runner"]
    prepare(
        paths,
        box,
        model=runner["model"],
        llm=config["arms"][arm]["llm"],
        thinking=runner["thinking"],
        context_window=runner["context_window"],
        idle_timeout_ms=runner.get("http_idle_timeout_ms"),
        reserve_tokens=runner["reserve_tokens"],
    )
    if arm == "A4":
        settle(config)  # 前一个会话写入的记忆处理完，这个写者才开始
    before = version(config, run, arm)
    started = datetime.now(UTC).isoformat(timespec="seconds")
    result = run_session(paths, box, writer, prompt(timeline, arm, step), timeout_s=runner["session_timeout_min"] * 60)
    record = {
        "arm": arm,
        "seq": step["seq"],
        "type": step["type"],
        "identity": writer.id,
        "started": started,
        **result,
        "events": str((paths.root / result["events"]).relative_to(run)),
        "session": [str((paths.root / s).relative_to(run)) for s in result["session"]],
        "llm": config["arms"][arm]["llm"],
        "version_before": before,
        "version_after": version(config, run, arm),
        "network": network_calls(paths.root / result["events"]),
    }
    if arm == "A0":
        status = _git(arm_dir(run, "A0") / "repo", "status", "--porcelain")
        record["uncommitted"] = status.splitlines()
    return record


def network_calls(events: Path) -> list[str]:
    """会话中联网的 shell 命令（curl、wget、git clone、pip install、带网址的命令）：沙箱不断网，联网只记下。"""
    found = []
    if not events.exists():
        return found
    for line in events.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = event.get("message") or {}
        if event.get("type") != "message_end" or message.get("role") != "assistant":
            continue
        for call in message.get("content", []):
            if call.get("type") == "toolCall" and call.get("name") == "bash":
                command = str((call.get("arguments") or {}).get("command", ""))
                if NETWORK.search(command):
                    found.append(command[:500])
    return found


# ---------------------------------------------------------------- 检查点上的读者


def reader_arm(config: dict[str, Any], run: Path, arm: str, papers: int) -> Arm:
    """读者看到的库，只读，没有论文与代码。A3、A2：MCP 服务只列不写入的工具，read_evidence 只读产物文档；
    A0：检查点标签处的仓库副本（只读挂载）；A4：pi 不列出 Graphiti 的写入工具。"""
    spec = config["arms"][arm]
    if arm in GRAPH:
        data = arm_dir(run, arm) / "data"
        ablate = tuple(spec.get("ablate") or ())
        return Arm(arm, None, neo4j=spec["neo4j"], data=data, read_only=True, evidence_scope="artifacts", ablate=ablate)
    if arm == "A0":
        copy = arm_dir(run, "A0") / "readers" / f"k{papers}" / "repo"
        if not copy.exists():
            copy.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "clone", "-q", "--no-hardlinks", str(arm_dir(run, "A0") / "repo"), str(copy)], check=True)
            _git(copy, "checkout", "-q", f"checkpoint-{papers}")
        return Arm("A0", None, store=copy, read_only=True)
    return Arm("A4", None, graphiti=spec["graphiti"], hide_tools=A4_WRITE_TOOLS)


def answers_file(run: Path, arm: str, papers: int) -> Path:
    return run / "answers" / arm / f"k{papers}.jsonl"


def answered(run: Path, arm: str, papers: int) -> set[str]:
    path = answers_file(run, arm, papers)
    if not path.exists():
        return set()
    return {json.loads(line)["probe"] for line in path.read_text(encoding="utf-8").splitlines()}


def readers(config: dict[str, Any], timeline: Timeline, run: Path, arm: str, papers: int,
            only: set[str] | None = None) -> None:  # fmt: skip
    """检查点上，组 ``arm`` 的读者逐题作答，写者在此期间暂停。只存回答与记录，不判分（判分在全部运行结束后统一进行，
    按题号对回冻结的金标准）。已存的题跳过；``only`` 只答这些题（试跑，不按有效性筛选）。"""
    expected = checkpoints(run)[arm][papers]
    if arm != "A4" and version(config, run, arm) != expected:  # 续跑时库必须仍在检查点上
        raise RuntimeError(f"{arm}: the store moved past checkpoint {papers} ({expected}) before its readers finished")
    probes = [p for p in timeline.probes if p["id"] in only] if only else eligible(timeline, papers)
    todo = [p for p in probes if p["id"] not in answered(run, arm, papers)]
    if not todo:
        return
    if arm == "A4":
        settle(config)
    box = reader_arm(config, run, arm, papers)
    reader = Writer("reader", timeline.reader["user"], f"{config['runner']['agent']}/{config['runner']['model']}")
    path = answers_file(run, arm, papers)
    path.parent.mkdir(parents=True, exist_ok=True)

    def ask(probe: dict[str, Any]) -> None:
        record = answer(config, timeline, run, arm, papers, probe, box, reader)
        record["version"] = expected
        with _LOCK, open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"[{arm} k{papers} {probe['id']}] exit {record['exit']}, {record['seconds']}s, "
              f"{len(record['answer'])} chars", flush=True)  # fmt: skip

    with ThreadPoolExecutor(max_workers=config["runner"].get("reader_workers", 1)) as pool:
        list(pool.map(ask, todo))


def answer(config: dict[str, Any], timeline: Timeline, run: Path, arm: str, papers: int, probe: dict[str, Any],
           box: Arm, reader: Writer) -> dict[str, Any]:  # fmt: skip
    """一题一次读者会话：回答原文、事件流与会话记录、用时、token、工具调用与联网命令。"""
    paths = Paths(arm_dir(run, arm) / "readers" / f"k{papers}" / probe["id"])
    if paths.root.exists():  # 中断后重跑：上次没存下回答的会话目录不留
        shutil.rmtree(paths.root)
    runner = config["runner"]
    prepare(
        paths,
        box,
        model=runner["model"],
        llm=config["arms"][arm]["llm"],
        thinking=runner["thinking"],
        context_window=runner["context_window"],
        idle_timeout_ms=runner.get("http_idle_timeout_ms"),
        reserve_tokens=runner["reserve_tokens"],
    )
    text = reader_prompt(timeline, arm, probe)
    started = datetime.now(UTC).isoformat(timespec="seconds")
    result = run_session(paths, box, reader, text, timeout_s=runner["probe_timeout_min"] * 60)
    events = paths.root / result["events"]
    return {
        "arm": arm,
        "checkpoint": papers,
        "probe": probe["id"],
        "started": started,
        **result,
        "events": str(events.relative_to(run)),
        "session": [str((paths.root / s).relative_to(run)) for s in result["session"]],
        "llm": config["arms"][arm]["llm"],
        "prompt": text,
        "answer": final_text(events),
        "usage": usage(events),
        "tools": tool_counts(events),
        "network": network_calls(events),
    }


def _assistant_messages(events: Path) -> list[dict[str, Any]]:
    messages = []
    if not events.exists():
        return messages
    for line in events.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = event.get("message") or {}
        if event.get("type") == "message_end" and message.get("role") == "assistant":
            messages.append(message)
    return messages


def final_text(events: Path) -> str:
    """回答：最后一条有文字的助手消息。"""
    texts = ["".join(c.get("text", "") for c in m.get("content", []) if c.get("type") == "text").strip()
             for m in _assistant_messages(events)]  # fmt: skip
    return next((t for t in reversed(texts) if t), "")


def usage(events: Path) -> dict[str, int]:
    """各次模型调用的 token 之和（pi 的 input 不含命中缓存的部分，cacheRead 另计）。"""
    total = {"calls": 0, "input": 0, "cacheRead": 0, "output": 0}
    for message in _assistant_messages(events):
        total["calls"] += 1
        for key in ("input", "cacheRead", "output"):
            total[key] += int((message.get("usage") or {}).get(key) or 0)
    return total


def tool_counts(events: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for message in _assistant_messages(events):
        for call in message.get("content", []):
            if call.get("type") == "toolCall":
                counts[call["name"]] = counts.get(call["name"], 0) + 1
    return counts


# ---------------------------------------------------------------- 记录与续跑


def _recorded(run: Path, arm: str, seq: int) -> bool:
    return (arm, seq) in _done(run)


def _done(run: Path) -> set[tuple[str, int]]:
    path = run / "sessions.jsonl"
    if not path.exists():
        return set()
    return {(r["arm"], r["seq"]) for r in map(json.loads, path.read_text(encoding="utf-8").splitlines())}


def _append(run: Path, record: dict[str, Any]) -> None:
    with _LOCK, open(run / "sessions.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def checkpoints(run: Path) -> dict[str, dict[int, Any]]:
    path = run / "checkpoints.yml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {} if path.exists() else {}


def checkpoint(config: dict[str, Any], run: Path, arm: str, papers: int) -> None:
    """记下检查点的库版本；A0 另打 git 标签 ``checkpoint-<篇数>``（读者读这个标签处的副本）。"""
    if arm == "A0":
        _git(arm_dir(run, "A0") / "repo", "tag", "-f", f"checkpoint-{papers}", user="t1")
    head = version(config, run, arm)
    with _LOCK:
        data = checkpoints(run)
        data.setdefault(arm, {})[papers] = head
        (run / "checkpoints.yml").write_text(yaml.safe_dump(data, sort_keys=True), encoding="utf-8")


def _record_run(run: Path, config_path: Path, config: dict[str, Any], argv: list[str]) -> None:
    """``run.yml``：配置（第一次调用时），以及每次调用的时间、参数、仓库与题库的提交、pi 的版本。种子与会话
    可以分几次调用完成，期间运行框架若有改动，各次调用的提交都留在记录中。"""
    path = run / "run.yml"
    record = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {
        "config": str(config_path), "config_text": config_path.read_text(encoding="utf-8"), "invocations": []}  # fmt: skip

    def commit(repo: Path) -> dict[str, Any]:
        head = _git(repo, "rev-parse", "HEAD").strip()
        return {"commit": head, "dirty": bool(_git(repo, "status", "--porcelain", "--untracked-files=no").strip())}

    record["invocations"].append({
        "started": datetime.now(UTC).isoformat(timespec="seconds"),
        "argv": argv,
        "repo": commit(REPO),
        "probes": commit(config["probes_repo"]),
        "pi": pi_version(),
    })  # fmt: skip
    path.write_text(yaml.safe_dump(record, allow_unicode=True, sort_keys=False), encoding="utf-8")


def preflight(config: dict[str, Any], arms: list[str]) -> list[str]:
    """各组要用的服务是否连得上（TCP）：大模型、图库、Graphiti。"""
    problems = []
    for arm in arms:
        spec = config["arms"][arm]
        for key in ("llm", "neo4j", "graphiti"):
            if key in spec:
                url = urlsplit(spec[key])
                try:
                    socket.create_connection((url.hostname, url.port or 80), timeout=5).close()
                except OSError as exc:
                    problems.append(f"{arm} {key} {spec[key]}: {exc}")
    return problems


# ---------------------------------------------------------------- 运行


def run_arm(config: dict[str, Any], timeline: Timeline, run: Path, arm: str, until: int | None, reset: bool,
            with_readers: bool = True) -> None:  # fmt: skip
    if 0 not in (checkpoints(run).get(arm) or {}):
        setup(config, timeline, run, arm, reset=reset)
        checkpoint(config, run, arm, 0)
    done = _done(run)
    last_seq = 0
    for step in timeline.steps:
        if step["type"] == "checkpoint":
            if all((arm, s["seq"]) in done for s in timeline.steps if "seq" in s and s["seq"] <= last_seq):
                if step["papers"] not in (checkpoints(run).get(arm) or {}):
                    checkpoint(config, run, arm, step["papers"])
                if with_readers:
                    readers(config, timeline, run, arm, step["papers"])  # 读者答完，下一位写者才开始
            continue
        last_seq = step["seq"]
        if until is not None and step["seq"] > until:
            return
        if (arm, step["seq"]) in done:
            continue
        if step["type"] == "update":
            bring_version(config, timeline, run, arm, step["paper"])
        record = session(config, timeline, run, arm, step)
        _append(run, record)
        done.add((arm, step["seq"]))
        net = f", network {len(record['network'])}" if record["network"] else ""
        print(f"[{arm} {step['seq']:02d}] {step['identity']} {step['type']}: exit {record['exit']}, "
              f"{record['seconds']}s{net}", flush=True)  # fmt: skip


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("name", help="运行名")
    parser.add_argument("--config", default=str(CONFIG))
    parser.add_argument("--arms", default=",".join(ARMS))
    parser.add_argument("--until", type=int, help="只跑到这个序号（试跑）")
    parser.add_argument("--neo4j", help="覆盖图库地址，如 A3=bolt://localhost:7695")
    parser.add_argument("--reset", action="store_true", help="图库不空时清空（只清配置中这一组的图库）")
    parser.add_argument("--no-readers", action="store_true", help="检查点上不运行读者（试跑）")
    args = parser.parse_args(argv)
    config_path = Path(args.config).resolve()
    config = load_config(config_path)
    for item in filter(None, (args.neo4j or "").split(",")):
        arm, uri = item.split("=", 1)
        config["arms"][arm]["neo4j"] = uri
    arms = args.arms.split(",")
    if unknown := set(arms) - set(ARMS):
        raise SystemExit(f"unknown arms: {sorted(unknown)}")
    if problems := preflight(config, arms):
        raise SystemExit("services are not reachable:\n" + "\n".join(problems))
    run = config["workdir_root"] / args.name
    run.mkdir(parents=True, exist_ok=True)
    _record_run(run, config_path, config, list(argv) if argv is not None else sys.argv[1:])
    timeline = load_timeline(config["probes_repo"])
    with ThreadPoolExecutor(max_workers=len(arms)) as pool:
        futures = [pool.submit(run_arm, config, timeline, run, a, args.until, args.reset, not args.no_readers) for a in arms]
        for future in futures:
            future.result()  # 一组出错时报出，其他组照常跑完
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["Timeline", "load_config", "load_timeline", "main", "network_calls", "prompt", "setup"]
