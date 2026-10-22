"""正式时间线的一次运行（f3，docs/experiments/f3/2026-10-22-f3-design.md）：建立各组的起点（种子），按题库的会话
序列逐个运行写者会话，在检查点记下库的版本、导出快照与备份。读者不在写者时间线中作答，事后在检查点备份上离线作答
（写读分离，V3 §7 第 9 条；f3 的 M2）。

    python -m pweval.harness.timeline <运行名> [--config eval/config/f3-ltsf.yml] [--arms A3,A2]
        [--until <序号>] [--neo4j A3=bolt://…,A2=…] [--reset] [--allow-config-change] [--allow-code-change]

f3 只接通了 A3、A2（M1）；A0、A4 的写者条件属 M3、M4，在此之前拒绝运行。

会话序列、身份与任务文字由题库仓库（``probes_repo``）给出，各组相同（tmps/probes/writer-tasks.md）：

- ``tasks/plan-f3.yml``（配置项 ``plan``）：70 个会话与三个检查点，按顺序；每个会话有身份、类型与任务文字；
- ``tasks/materials.yml``（配置项 ``materials``，f3 工程记录 B1）：种子来源、每个会话点出与新开放的来源、各来源的
  内容哈希；
- ``tasks/identities.yml``：10 个写者身份（登录身份与背景，背景接在任务之前）；
- ``tasks/hints.yml``：任务文字中 ``{WRITE}`` 与 ``{TOOLS}`` 的逐组原文；
- ``tasks/reader.yml``、``probes/sample.yml``：检查点上的读者与 200 道题（严格规则：金标准依赖的论文全部入库才作答）；
  另有辅助组的代码题（``manual-rendered.yml`` 中 ``group: auxiliary``），同样作答，单独存放、不进主检验；
- ``seed/f3/``（配置项 ``seed``，B7）：起点。A3、A2 由系统的命令行重放两次提交（锚点与种子论文；三张排行榜），A0 是
  ``a0/store`` 的文件分两次 git 提交，A4 是 ``a4/episodes.yaml`` 的 30 条记忆，经 Graphiti 的 MCP 服务逐条写入。

运行目录 ``<workdir_root>/<运行名>/``：

- ``run.yml``：每次调用的时间、参数、实际生效的配置、仓库与题库的提交、pi 的版本（续跑时配置或题库变了即拒绝）；
- ``sessions.jsonl``：每个会话一行（组、序号、类型、身份、会话目录、退出码、用时、事件流与会话记录、会话前后的
  库版本、材料清单 ``materials``（点出、新开放的来源与此时可取的来源数）、来源服务的请求统计 ``read_source``、
  会话归档、联网的命令）；
- ``checkpoints.yml``：各组每个检查点（0、10、20、30 篇）的库版本（A4 为 group 的指纹，见 :func:`version`）；
- ``snapshots/<组>/k<篇数>/``：检查点的快照（:func:`snapshot`），供事后的库健康度审计与判分核对；
- ``backups/<组>/k<篇数>/``：A3、A2 在检查点上的库备份（:func:`backup`：Neo4j 的离线 dump 与材料根目录），读者事后
  在检查点的库上作答用；
- ``<组>/inflight.json``：正在运行的写者会话、它的会话目录与开始前的库版本，记账后删除（:func:`recover`）；
- ``<组>/sessions/<序号>-<时刻>/``：每个写者会话（每次尝试）全新的目录：``work/``（沙箱的 ``/work``，含本次取到的
  ``sources/``）、``home/``、事件流 ``runs/``、来源服务的请求记录 ``sources.jsonl``。后续会话不挂载它；
- ``<组>/session-snapshots/<序号>-{after,interrupted}-<时刻>.tar.gz``：会话结束（或被中断）时的 ``work/`` 与
  ``home/``，只供审计（:func:`archive`）；
- ``<组>/sources/``：本组到此为止开放过的来源（论文 ``<ID>/paper.md``，代码 ``<仓库>@<commit>/``），按材料表在会话
  开始时从语料复制并核对哈希，是 A3、A2 的 MCP 服务的只读来源目录（``PAPERWEAVE_SOURCES``）；
- ``answers/<组>/k<篇数>.jsonl``：检查点上读者的回答，一题一行（题号、题面原文、回答原文、库版本、事件流与会话记录、
  用时、token、工具调用、联网命令）。运行时不判分，全部运行结束后按题号对回冻结的金标准统一判分；
- ``<组>/``：A3、A2 的材料根目录 ``data/``（产物文档）；A0 的共享仓库 ``repo/``。

写者的沙箱断网（V3 §7 第 5 条），不挂载论文与代码（f3 §2）：材料只经来源服务 ``read_source`` 按来源 ID 取得，任务
文字末尾接环境说明（``ENV_NOTE``）与写者的来源说明（``WRITER_NOTE``）。

各组的存储互不相干，组内按序号逐个运行（写者轮流写），各组同时运行。

中断（只指运行框架或基础设施退出，B4）后用同一个运行名重跑：已记账的会话、已导出的快照与备份跳过；中断时正在
运行的会话，库没变就在全新目录中重跑（被中断那次归档），变了就按中断记账、不重跑；写者自己的超时、调用上限与报错
照实记账，不重跑。检查点上还有工作（快照、备份）时先核对库仍在检查点版本。评测代码不导入被测系统：A3、A2
的库只经命令行、MCP 与 Cypher 读取接触，A4 的库经 Graphiti 的 MCP 服务与 Cypher 读取接触；检查点备份另经 docker
停启图库的容器、用同一镜像的 ``neo4j-admin`` 离线 dump。
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import traceback
from collections.abc import Iterator, Sequence
from contextlib import contextmanager, nullcontext
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

from ..paths import EVAL, REPO
from . import export
from .mcp_client import HttpClient
from .sandbox import (
    ENV_NOTE,
    GRAPH,
    WRITER_NOTE,
    Arm,
    Paths,
    ReadSource,
    Writer,
    pi_version,
    prepare,
    run_session,
    site_record,
)
from .source_server import tree_sha256

CONFIG = EVAL / "config/f3-ltsf.yml"
A0_KIT = EVAL / "baselines/a0"  # A0 的约定（AGENTS.md）与模板，内容与 A3 的工具说明、空白模板对等
ARMS = ("A3", "A2", "A0", "A4")
F3_ARMS = ("A3", "A2")  # f3 已接通的组；A0、A4 属 M3、M4
PROTECTED = {7687, 7688}  # 不清空的图库端口
SEED_USER = "seed"
SEED_MESSAGES = (  # 与 seed/README.md 相同，各组一致
    "seed: identity anchors (tasks, datasets) and the seed papers Informer and SCINet",
    "seed: leaderboards for ETTh1, Electricity and ETTh2 with the seed papers rows",
)
A4_WRITE_TOOLS = tuple(f"mcp__Graphiti__{t}" for t in  # A4 读者看不到的 Graphiti 工具（写入与删除）；summarize_saga
                       ("add_memory", "add_triplet", "delete_episode", "delete_entity_edge", "build_communities",
                        "summarize_saga"))  # 会把摘要与水位写回 saga 节点（graphiti_core Graphiti.summarize_saga）
SEED_BOARDS = ("02-lb-etth1.md", "03-lb-electricity.md", "04-lb-etth2.md")
NETWORK = re.compile(r"\b(curl|wget|git\s+(clone|fetch|pull|ls-remote)|pip3?\s+install|uv\s+(pip|add)|https?://)")
_LOCK = threading.RLock()  # 进程内：各组线程共用的记录文件（sessions.jsonl、checkpoints.yml、answers）与输出


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    """线程之间与进程之间都互斥地使用记录文件 ``path``（旁边的 ``<文件>.lock`` 上加 flock）。监视者会在一组出错后
    单独续跑那一组（``--arms A3``），这时两个进程同时写同一个运行目录。同一线程不要对同一文件嵌套使用。"""
    with _LOCK, open(path.with_name(path.name + ".lock"), "a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


@contextmanager
def _arm_lock(run: Path, arm: str) -> Iterator[bool]:
    """一组同时只能由一个进程运行：``<组>/.running.lock`` 上的非阻塞 flock，拿不到就是另一个进程正在跑这一组。"""
    arm_dir(run, arm).mkdir(parents=True, exist_ok=True)
    with open(arm_dir(run, arm) / ".running.lock", "a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


# ---------------------------------------------------------------- 配置与会话序列


@dataclass(frozen=True)
class Timeline:
    steps: list[dict[str, Any]]  # plan.yml：会话（有 seq）与检查点（type: checkpoint）
    identities: dict[str, dict[str, Any]]
    hints: dict[str, dict[str, str]]  # 组（小写）→ {WRITE, TOOLS}
    reader: dict[str, Any]  # tasks/reader.yml：读者的登录身份、提示语、种子中的论文
    probes: list[dict[str, Any]]  # probes/sample.yml 的 200 题，题面与金标准取自 auto.yml、manual-rendered.yml
    aux: list[dict[str, Any]] = field(default_factory=list)  # 辅助组的代码题（T16–T18），单独报告
    materials: dict[str, Any] = field(default_factory=dict)  # tasks/materials.yml（f3）：seed、sessions、sources

    def opens(self, seq: int) -> list[str]:
        """会话 ``seq`` 开始时新开放的来源。"""
        return next((list(r.get("opens", [])) for r in self.materials["sessions"] if r["seq"] == seq), [])

    def named(self, seq: int) -> list[str]:
        """会话 ``seq`` 的任务文字点出的来源。"""
        return next((list(r.get("named", [])) for r in self.materials["sessions"] if r["seq"] == seq), [])

    def opened_through(self, seq: int) -> list[str]:
        """会话 ``seq`` 开始时可取的来源：种子，加上序号不大于它的会话新开放的来源（开放后一直可读）。"""
        out = list(self.materials["seed"])
        for row in self.materials["sessions"]:
            if row["seq"] <= seq:
                out += [s for s in row.get("opens", []) if s not in out]
        return out

    def group(self, name: str) -> list[dict[str, Any]]:
        return self.aux if name == "aux" else self.probes


def load_config(path: Path) -> dict[str, Any]:
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    for key in ("probes_repo", "corpus_papers", "code", "workdir_root"):
        config[key] = Path(config[key]).expanduser()
    for key in ("plan", "materials", "seed"):  # 题库中的位置（f3）
        if key not in config:
            raise SystemExit(f"{path}: {key} is not configured (the runner since f3 needs plan, materials and seed)")
    if log := config["arms"].get("A4", {}).get("graphiti_log"):
        config["arms"]["A4"]["graphiti_log"] = Path(log).expanduser()
    return config


def timeline_of(config: dict[str, Any]) -> Timeline:
    """配置所指的会话序列与材料表。"""
    return load_timeline(config["probes_repo"], config["plan"], config["materials"])


def load_timeline(probes: Path, plan: str = "tasks/plan.yml", materials: str | None = None) -> Timeline:
    steps = yaml.safe_load((probes / plan).read_text(encoding="utf-8"))
    identities = {i["id"]: i for i in yaml.safe_load((probes / "tasks/identities.yml").read_text(encoding="utf-8"))}
    hints = yaml.safe_load((probes / "tasks/hints.yml").read_text(encoding="utf-8"))
    reader = yaml.safe_load((probes / "tasks/reader.yml").read_text(encoding="utf-8"))
    pool = {}
    for name in ("auto.yml", "manual-rendered.yml"):
        pool |= {p["id"]: p for p in yaml.safe_load((probes / "probes" / name).read_text(encoding="utf-8"))}
    sample = yaml.safe_load((probes / "probes/sample.yml").read_text(encoding="utf-8"))
    aux = [p for p in pool.values() if p.get("group") == "auxiliary"]
    table = yaml.safe_load((probes / materials).read_text(encoding="utf-8")) if materials else {}
    return Timeline(steps, identities, hints, reader, [pool[p["id"]] for p in sample], aux, table)


def papers_at(timeline: Timeline, papers: int) -> set[str]:
    """检查点 ``papers`` 时库中应有的论文版本：种子，加上这个检查点之前各会话建库与更新的论文。"""
    present = set(timeline.reader["seed_papers"])
    for step in timeline.steps:
        if step["type"] == "checkpoint" and step["papers"] == papers:
            return present
        if step["type"] in ("build", "update"):
            present.add(step["paper"])
    raise KeyError(f"no checkpoint at {papers} papers")


def eligible(timeline: Timeline, papers: int, group: str = "main") -> list[dict[str, Any]]:
    """严格规则（D31）：金标准依赖的论文（``requires``）全部入库的题，金标准不按检查点重算。"""
    present = papers_at(timeline, papers)
    return [p for p in timeline.group(group) if set(p["requires"]) <= present]


def reader_prompt(timeline: Timeline, arm: str, probe: dict[str, Any]) -> str:
    return timeline.reader["prompt"].format(question=probe["question"].strip(), TOOLS=timeline.hints[arm.lower()]["TOOLS"])


def prompt(timeline: Timeline, arm: str, step: dict[str, Any]) -> str:
    """身份背景 + 任务文字（``{WRITE}`` 按会话的产物类型、``{TOOLS}`` 按组替换）+ 环境说明（V3 §7 第 5 条）+ 写者的
    来源说明（f3 B2），后两者各组相同。"""
    hint = timeline.hints[arm.lower()]
    task = step["task"].replace("{WRITE}", hint["WRITE"].format(type=step.get("writes", "")))
    task = task.replace("{TOOLS}", hint["TOOLS"])
    if "{" in task:
        raise ValueError(f"unfilled placeholder in session {step['seq']}: {task}")
    background = timeline.identities[step["identity"]]["background"].strip()
    return f"{background}\n\n{task.strip()}\n\n{ENV_NOTE}\n{WRITER_NOTE}\n"


def writer_of(config: dict[str, Any], identity: dict[str, Any]) -> Writer:
    runner = config["runner"]
    return Writer(identity["id"], identity["user"], f"{runner['agent']}/{runner['model']}")


# ---------------------------------------------------------------- 各组的目录与材料


def arm_dir(run: Path, arm: str) -> Path:
    return run / arm


def sources_dir(run: Path, arm: str) -> Path:
    """组的已开放来源：A3、A2 的 MCP 服务的只读来源目录（``PAPERWEAVE_SOURCES``）。"""
    return arm_dir(run, arm) / "sources"


def source_digest(root: Path, source: str) -> str:
    """来源目录中一个来源的内容哈希，算法与材料表相同：论文为 ``paper.md`` 的 SHA-256，代码为目录哈希。"""
    return tree_sha256(root / source) if "@" in source else _sha256(root / source / "paper.md")


def open_sources(config: dict[str, Any], timeline: Timeline, run: Path, arm: str, ids: list[str]) -> list[str]:
    """组的来源目录中应有来源 ``ids``，每个都与材料表的哈希一致：缺的从语料复制进来（复制前核对语料），已有的
    重新核对，不一致即停。返回这次新放进去的。先复制到 ``<ID>.partial`` 再改名。

    这一份是唯一被读的：来源服务从这里交付，A3、A2 的 MCP 服务从这里读，每个会话开始前全部核对一次。"""
    added = []
    for source in ids:
        target = sources_dir(run, arm) / source
        expected = timeline.materials["sources"][source]["sha256"]
        if target.exists():
            if (actual := source_digest(sources_dir(run, arm), source)) != expected:
                raise RuntimeError(f"{source}: the opened copy in {target.parent} does not match materials.yml "
                                   f"({actual} != {expected})")  # fmt: skip
            continue
        code = "@" in source
        origin = config["code"] / source if code else config["corpus_papers"] / source / "paper.md"
        actual = tree_sha256(origin) if code else _sha256(origin)
        if actual != expected:
            raise RuntimeError(f"{source}: the corpus copy does not match materials.yml ({actual} != {expected})")
        partial = target.with_name(target.name + ".partial")
        shutil.rmtree(partial, ignore_errors=True)
        if code:
            shutil.copytree(origin, partial)
        else:
            partial.mkdir(parents=True)
            shutil.copyfile(origin, partial / "paper.md")
        partial.rename(target)
        added.append(source)
    return added


# ---------------------------------------------------------------- 起点


def setup(config: dict[str, Any], timeline: Timeline, run: Path, arm: str, *, reset: bool) -> None:
    """组的起点：种子来源开放，种子入库。已记录检查点 0 的组不再建立。"""
    if any(a == arm for a, _ in _done(run)):  # 检查点 0 没有记录却已有会话：记录有误，不能重建（--reset 会清库）
        raise SystemExit(f"{arm}: sessions are recorded in {run} but checkpoint 0 is not; refusing to rebuild the start")
    open_sources(config, timeline, run, arm, list(timeline.materials["seed"]))
    seed = config["probes_repo"] / config["seed"]
    if arm in GRAPH:
        _seed_graph(config, run, arm, seed, reset=reset)
    elif arm == "A0":
        _seed_a0(run, seed)
    else:
        _seed_a4(config, seed, reset=reset)


def _system_env(config: dict[str, Any], run: Path, arm: str) -> dict[str, str]:
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": str(Path.home()),
        "PAPERWEAVE_NEO4J_URI": config["arms"][arm]["neo4j"],
        "PAPERWEAVE_DATA": str(arm_dir(run, arm) / "data"),
        "PAPERWEAVE_SOURCES": str(sources_dir(run, arm)),
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


def _git(repo: Path, *args: str, user: str | None = None, env: dict[str, str] | None = None) -> str:
    env = {"PATH": "/usr/bin:/bin", "HOME": str(repo), **(env or {})}
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


def _seed_a4(config: dict[str, Any], seed: Path, *, reset: bool) -> None:
    """30 条种子记忆逐条写入 Graphiti，每条之后等它处理完（服务按 group 串行处理排队的记忆）。

    写入前 group 必须为空：Graphiti 服务与 group 跨运行共用，换运行名或种子写到一半中断，都会留下旧内容。
    不逐条续写：种子中断后用 ``--reset`` 清空这个 group，从头写入，四组才从同一起点出发。"""
    spec = config["arms"]["A4"]
    settle(config)  # 上次中断时排队的记忆先处理完，否则清空之后它们还会落进库
    with export.driver(spec["neo4j"]) as d:
        nodes = d.execute_query("MATCH (n {group_id: $g}) RETURN count(n) AS n", g=spec["group_id"]).records[0]["n"]
        if nodes:
            if not reset:
                raise SystemExit(f"A4: group {spec['group_id']!r} holds {nodes} nodes; pass --reset to clear it")
            if urlsplit(spec["neo4j"]).port in PROTECTED:
                raise SystemExit(f"refusing to clear {spec['neo4j']}")
            query = "MATCH (n {group_id: $g}) WITH n LIMIT 5000 DETACH DELETE n RETURN count(*) AS c"
            while d.execute_query(query, g=spec["group_id"]).records[0]["c"]:
                pass
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


def sandbox_arm(config: dict[str, Any], run: Path, arm: str, opened: list[str] | None = None, session: str = "") -> Arm:
    """写者的沙箱，断网（V3 §7 第 5 条）：大模型服务经转发；A3、A2 的 MCP 服务本来就经 socket；A4 的 Graphiti 经转发。
    不挂载论文与代码；``opened`` 是本会话可取的来源，经来源服务取得（f3 §2、§4）。"""
    spec = config["arms"][arm]
    llm = spec["llm"]
    read = ReadSource(sources_dir(run, arm), config["corpus_papers"], config["code"], tuple(opened or ()), session)
    if arm in GRAPH:
        data = arm_dir(run, arm) / "data"
        return Arm(arm, None, neo4j=spec["neo4j"], data=data, ablate=tuple(spec.get("ablate") or ()), isolated_llm=llm,
                   sources=sources_dir(run, arm), read_source=read)  # fmt: skip
    if arm == "A0":
        return Arm("A0", None, store=arm_dir(run, "A0") / "repo", isolated_llm=llm, read_source=read)
    graphiti = urlsplit(spec["graphiti"])
    return Arm("A4", None, graphiti=spec["graphiti"], isolated_llm=llm, read_source=read,
               isolated_tcp=(f"{graphiti.hostname}:{graphiti.port}",))  # fmt: skip


A4_CONTENT = (  # group 的全部节点与边，属性去掉嵌入（嵌入由内容算出，且体量大）
    "MATCH (n {group_id: $g}) RETURN 'node' AS what, n.uuid AS id, labels(n) AS kind, "
    "[k IN keys(n) WHERE NOT k ENDS WITH 'embedding' | [k, n[k]]] AS props "
    "UNION ALL MATCH (a)-[r {group_id: $g}]->(b) RETURN 'edge' AS what, r.uuid AS id, [type(r), a.uuid, b.uuid] AS kind, "
    "[k IN keys(r) WHERE NOT k ENDS WITH 'embedding' | [k, r[k]]] AS props"
)


def version(config: dict[str, Any], run: Path, arm: str) -> str | None:
    """库的版本：A3、A2 为分支头的提交 id，A0 为仓库的 HEAD。A4 没有版本，取 group 的内容指纹：先等排队的记忆
    处理完，再用 Cypher 读出全部节点与边（去掉嵌入），对排序后的内容取 sha256。任何属性的改动（包括实体摘要、
    事实失效）都会改变它。"""
    if arm in GRAPH:
        return export.head(config["arms"][arm]["neo4j"])
    if arm == "A0":
        return _git(arm_dir(run, "A0") / "repo", "rev-parse", "HEAD").strip()
    settle(config)
    spec = config["arms"]["A4"]
    with export.driver(spec["neo4j"]) as d:
        rows = d.execute_query(A4_CONTENT, g=spec["group_id"]).records
    content = sorted(json.dumps([r["what"], r["id"], sorted(r["kind"]) if r["what"] == "node" else r["kind"],
                                 sorted(r["props"])], default=str) for r in rows)  # fmt: skip
    nodes = sum(r["what"] == "node" for r in rows)
    digest = hashlib.sha256("\n".join(content).encode()).hexdigest()[:16]
    return f"nodes={nodes} edges={len(rows) - nodes} sha256={digest}"


def _a0_status(run: Path) -> list[str]:
    return _git(arm_dir(run, "A0") / "repo", "status", "--porcelain").splitlines()


def _a0_worktree(run: Path) -> str:
    """A0 工作区的内容指纹：暂存区的树，以及把工作区全部改动（已修改、已暂存、未跟踪，不含忽略的）加进去之后的树。
    ``git status`` 只给出文件名与状态，同一文件被再次修改时看不出来。两棵树都在临时索引上算，不动仓库自己的索引
    （只在对象库中多出几个不被引用的对象）。"""
    repo = arm_dir(run, "A0") / "repo"
    index = repo / _git(repo, "rev-parse", "--git-path", "index").strip()
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp) / "index"
        if index.exists():
            shutil.copy(index, scratch)
        env = {"GIT_INDEX_FILE": str(scratch)}
        staged = _git(repo, "write-tree", env=env).strip()
        _git(repo, "add", "-A", env=env)
        worktree = _git(repo, "write-tree", env=env).strip()
    return f"index={staged} worktree={worktree}"


def session_paths(run: Path, arm: str, seq: int) -> Paths:
    """一次会话（每次尝试）全新的目录 ``<组>/sessions/<序号>-<时刻>/``（f3 §2.1：不继承私人状态）。"""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    root = arm_dir(run, arm) / "sessions" / f"{seq:03d}-{stamp}"
    if root.exists():
        raise FileExistsError(f"refusing to reuse a session directory: {root}")
    return Paths(root)


def session(config: dict[str, Any], timeline: Timeline, run: Path, arm: str, step: dict[str, Any]) -> dict[str, Any]:
    """一个写者会话，在全新的工作目录与 home 中。开始前把序号、会话目录与库版本写进 ``<组>/inflight.json``（原子
    替换），会话记入 ``sessions.jsonl`` 之后才删掉；中断后续跑时据此判断这个会话是否已经改了库（:func:`recover`）。"""
    writer = writer_of(config, timeline.identities[step["identity"]])
    paths = session_paths(run, arm, step["seq"])
    opened = timeline.opened_through(step["seq"])
    box = sandbox_arm(config, run, arm, opened, f"{arm}-{step['seq']:03d}")
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
        max_tokens=runner.get("max_output_tokens"),
    )
    before = version(config, run, arm)  # A4：前一个会话写入的记忆处理完，这个写者才开始
    inflight = {"seq": step["seq"], "root": str(paths.root.relative_to(run)),
                "started": datetime.now(UTC).isoformat(timespec="seconds"), "started_epoch": time.time(),
                "version_before": before}  # fmt: skip
    if arm == "A0":
        inflight["worktree_before"] = _a0_worktree(run)
    _write_atomic(_inflight(run, arm), json.dumps(inflight, ensure_ascii=False))
    result = run_session(paths, box, writer, prompt(timeline, arm, step), timeout_s=runner["session_timeout_min"] * 60)
    return _session_record(config, timeline, run, arm, step, writer, paths, inflight, result)


def _session_record(config: dict[str, Any], timeline: Timeline, run: Path, arm: str, step: dict[str, Any],
                    writer: Writer, paths: Paths, inflight: dict[str, Any], result: dict[str, Any], *,
                    archived_as: str = "after") -> dict[str, Any]:  # fmt: skip
    events = paths.root / result["events"] if result["events"] else None
    record = {
        "arm": arm,
        "seq": step["seq"],
        "type": step["type"],
        "identity": writer.id,
        "root": str(paths.root.relative_to(run)),
        "started": inflight["started"],
        **result,
        "events": str(events.relative_to(run)) if events else None,
        "session": [str((paths.root / s).relative_to(run)) for s in result["session"]],
        "llm": config["arms"][arm]["llm"],
        "version_before": inflight["version_before"],
        "version_after": version(config, run, arm),
        "materials": materials_record(timeline, step["seq"]),
        "read_source": read_source_record(paths),
        "archive": archive(run, arm, step["seq"], paths, archived_as),
        "network": network_calls(events) if events else [],
    }
    if arm == "A0":
        record["uncommitted"] = _a0_status(run)
        record["worktree"] = _a0_worktree(run)
    return record


def materials_record(timeline: Timeline, seq: int) -> dict[str, Any]:
    """会话的材料清单（f3 §7）：任务点出的来源、本会话新开放的来源、此时可取的来源数。"""
    return {"named": timeline.named(seq), "opens": timeline.opens(seq), "available": len(timeline.opened_through(seq))}


def read_source_record(paths: Paths) -> dict[str, Any]:
    """来源服务的请求统计（逐次的记录在会话目录的 ``sources.jsonl``）：各结果的次数、取到的来源、拷贝的字节数。"""
    rows = read_jsonl(paths.root / "sources.jsonl", repair=False)
    outcomes: dict[str, int] = {}
    for r in rows:
        outcomes[r["outcome"]] = outcomes.get(r["outcome"], 0) + 1
    fetched = sorted({r["resolved"] for r in rows if r.get("resolved")})
    return {"requests": len(rows), "outcomes": outcomes, "fetched": fetched,
            "bytes": sum(int(r.get("bytes") or 0) for r in rows)}  # fmt: skip


def archive(run: Path, arm: str, seq: int, paths: Paths, when: str) -> dict[str, str]:
    """会话结束（``after``）或被中断（``interrupted``）时的工作目录（含 ``sources/``；A0 为共享仓库，含 ``.git``）与
    ``home/``，存成 ``<组>/session-snapshots/<序号>-<when>-<时刻>.tar.gz``，只供审计，不挂给后续会话（f3 B4）。

    文件名带时刻，从不覆盖：中断后重跑的会话有两份归档，被中断那次的记在 ``rerun_after_interruption`` 中。"""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = arm_dir(run, arm) / "session-snapshots" / f"{seq:03d}-{when}-{stamp}.tar.gz"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        raise FileExistsError(f"refusing to overwrite a recorded snapshot: {out}")
    work = arm_dir(run, "A0") / "repo" if arm == "A0" else paths.work
    partial = out.with_name(out.name + ".partial")
    with tarfile.open(partial, "w:gz") as tar:
        for source, name in ((work, "work"), (paths.home, "home")):
            if source.exists():
                tar.add(source, arcname=name)
    partial.replace(out)
    return {"path": str(out.relative_to(run)), "sha256": hashlib.sha256(out.read_bytes()).hexdigest()}


def _interrupted_result(paths: Paths, since: float) -> dict[str, Any]:
    """被中断那次留下的事件流与会话记录，有多少记多少。"""
    runs = sorted((p for p in (paths.root / "runs").glob("*.jsonl") if p.stat().st_mtime >= since),
                  key=lambda p: p.stat().st_mtime)  # fmt: skip
    sessions = sorted(p for p in (paths.home / "sessions").rglob("*.jsonl") if p.stat().st_mtime >= since)
    return {
        "exit": "interrupted",
        "seconds": None,
        "events": str(runs[-1].relative_to(paths.root)) if runs else None,
        "session": [str(p.relative_to(paths.root)) for p in sessions],
        "tool_kills": [],
    }


def recover(config: dict[str, Any], timeline: Timeline, run: Path, arm: str, step: dict[str, Any],
            inflight: dict[str, Any]) -> dict[str, Any]:  # fmt: skip
    """运行框架或基础设施在会话中途或记账之前退出后，续跑到这个会话时（f3 B4）：

    - 库没有变：返回 ``{"rerun": 被中断那次}``，调用者在全新目录中重跑；被中断那次的目录照样归档
      （``interrupted``），记在重跑记录的 ``rerun_after_interruption`` 中，重跑不继承它的任何文件；
    - 库变了：不重跑——同一任务在已改变的库上再做一次会留下重复的贡献——把这次会话按 ``exit: interrupted`` 照实
      记账（``recovered``），事件流与会话记录有多少记多少，目录归档为 ``interrupted``。

    A3、A2 看库版本，A4 看内容指纹（:func:`version`）。"""
    unchanged = version(config, run, arm) == inflight["version_before"]
    if arm == "A0":
        unchanged = unchanged and _a0_worktree(run) == inflight["worktree_before"]
    writer = writer_of(config, timeline.identities[step["identity"]])
    paths = Paths(run / inflight["root"])
    if unchanged:
        return {"rerun": {**inflight, "archive": archive(run, arm, step["seq"], paths, "interrupted")}}
    result = _interrupted_result(paths, inflight["started_epoch"])
    record = _session_record(config, timeline, run, arm, step, writer, paths, inflight, result,
                             archived_as="interrupted")  # fmt: skip
    return {"record": {**record, "recovered": True}}


def network_calls(events: Path) -> list[str]:
    """会话中联网的 shell 命令（curl、wget、git clone、pip install、带网址的命令），记为尝试联网：写者的沙箱断网后
    它们只会失败（V3 §7 第 5 条）。"""
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
    """读者看到的库，只读，没有论文目录与代码。A3、A2：MCP 服务只列不写入的工具，read_evidence 读产物文档与库中记录过
    的锚点所在的块（``anchored``，V3 §2.2：只能经库读原文，不能浏览）；
    A0：检查点标签处的仓库副本（只读挂载）；A4：pi 不列出 Graphiti 的写入工具。"""
    spec = config["arms"][arm]
    if arm in GRAPH:
        data = arm_dir(run, arm) / "data"
        ablate = tuple(spec.get("ablate") or ())
        return Arm(arm, None, neo4j=spec["neo4j"], data=data, read_only=True, evidence_scope="anchored", ablate=ablate)
    if arm == "A0":
        copy = arm_dir(run, "A0") / "readers" / f"k{papers}" / "repo"
        if not copy.exists():
            copy.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "clone", "-q", "--no-hardlinks", str(arm_dir(run, "A0") / "repo"), str(copy)], check=True)
            _git(copy, "checkout", "-q", f"checkpoint-{papers}")
        return Arm("A0", None, store=copy, read_only=True)
    return Arm("A4", None, graphiti=spec["graphiti"], hide_tools=A4_WRITE_TOOLS)


GROUPS = ("main", "aux")  # 主检验的 200 题；辅助组（代码题），存在 k<篇数>-aux.jsonl


def answers_file(run: Path, arm: str, papers: int, group: str = "main") -> Path:
    return run / "answers" / arm / (f"k{papers}.jsonl" if group == "main" else f"k{papers}-{group}.jsonl")


def answered(run: Path, arm: str, papers: int, group: str = "main") -> set[str]:
    return {r["probe"] for r in read_jsonl(answers_file(run, arm, papers, group))}


def readers(config: dict[str, Any], timeline: Timeline, run: Path, arm: str, papers: int,
            only: set[str] | None = None, group: str = "main") -> None:  # fmt: skip
    """检查点上，组 ``arm`` 的读者逐题作答，写者在此期间暂停。只存回答与记录，不判分（判分在全部运行结束后统一进行，
    按题号对回冻结的金标准）。已存的题跳过；``only`` 只答这些题（试跑，不按有效性筛选）。

    先看还有没有题要答，有才核对库仍在检查点上：已答完的检查点在续跑时库早已向前，不能因此报错。"""
    probes = [p for p in timeline.group(group) if p["id"] in only] if only else eligible(timeline, papers, group)
    todo = [p for p in probes if p["id"] not in answered(run, arm, papers, group)]
    if not todo:
        return
    expected = at_checkpoint(config, run, arm, papers)
    box = reader_arm(config, run, arm, papers)
    reader = Writer("reader", timeline.reader["user"], f"{config['runner']['agent']}/{config['runner']['model']}")
    path = answers_file(run, arm, papers, group)
    path.parent.mkdir(parents=True, exist_ok=True)

    def ask(probe: dict[str, Any]) -> None:
        record = answer(config, timeline, run, arm, papers, probe, box, reader)
        record["version"] = expected
        append_jsonl(path, record)
        emit("READER", arm, k=papers, probe=probe["id"], exit=record["exit"], seconds=record["seconds"],
             chars=len(record["answer"]))  # fmt: skip

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
        max_tokens=runner.get("max_output_tokens"),
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
        "stop": stop_reason(events),
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


def stop_reason(events: Path) -> str | None:
    """最后一条助手消息的结束原因：``stop``、``toolUse``、``length``（撞上单次回复的输出上限）、``error`` 等。"""
    messages = _assistant_messages(events)
    return messages[-1].get("stopReason") if messages else None


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
    return {(r["arm"], r["seq"]) for r in read_jsonl(run / "sessions.jsonl")}


def _append(run: Path, record: dict[str, Any]) -> None:
    append_jsonl(run / "sessions.jsonl", record)


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    """一条记录一次写入、带换行，写完刷到磁盘。进程在写入中被杀，只可能在文件末尾留下半行（:func:`read_jsonl`）。"""
    line = (json.dumps(record, ensure_ascii=False) + "\n").encode()
    with _locked(path), open(path, "ab") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())


def read_jsonl(path: Path, *, repair: bool = True) -> list[dict[str, Any]]:
    """读只追加的记录文件（sessions.jsonl、answers），与追加共用一把锁。``repair=False`` 供运行进程之外的只读查看
    （:mod:`pweval.harness.status`）：末尾没有换行的一段可能正在写，不动它，也不计入。

    - 末尾一段没有换行：若是完整的记录（换行没写上），补上换行；若不完整（进程在追加时被杀），原文另存为
      ``<文件>.torn-<时刻>`` 供审计，文件截到最后一个完整行，之后的追加从干净的行首开始。
    - 中间的行损坏不是追加中断造成的，报错，不静默跳过。"""
    if not path.exists():
        return []
    with _locked(path) if repair else nullcontext():
        if not path.exists():
            return []
        data = path.read_bytes()
        body, newline, tail = data.rpartition(b"\n")
        lines = body.split(b"\n") if newline else []
        if not newline:
            tail = data
        records = []
        for number, line in enumerate(lines, 1):
            try:
                records.append(json.loads(line))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise RuntimeError(f"{path}:{number}: damaged record in the middle of the file") from exc
        if tail and repair:
            try:
                records.append(json.loads(tail))
                with open(path, "ab") as f:
                    f.write(b"\n")
            except (json.JSONDecodeError, UnicodeDecodeError):
                stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
                path.with_name(f"{path.name}.torn-{stamp}").write_bytes(tail)
                with open(path, "r+b") as f:
                    f.truncate(len(data) - len(tail))
        return records


def _write_atomic(path: Path, text: str) -> None:
    """先写临时文件再替换：读者（另一组的线程，或中断后的续跑）只会看到旧的或新的完整内容，不会看到写了一半的。"""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _inflight(run: Path, arm: str) -> Path:
    return arm_dir(run, arm) / "inflight.json"


def checkpoints(run: Path) -> dict[str, dict[int, Any]]:
    """检查点记录；文件总是整份替换（:func:`_write_atomic`），读时不需要锁。"""
    path = run / "checkpoints.yml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {} if path.exists() else {}


def checkpoint(config: dict[str, Any], run: Path, arm: str, papers: int) -> None:
    """记下检查点的库版本；A0 另打 git 标签 ``checkpoint-<篇数>``（读者读这个标签处的副本）。"""
    if arm == "A0":
        _git(arm_dir(run, "A0") / "repo", "tag", "-f", f"checkpoint-{papers}", user="t1")
    head = version(config, run, arm)
    with _locked(run / "checkpoints.yml"):  # 读、改、写之间不让别的组（或别的进程）插进来
        data = checkpoints(run)
        data.setdefault(arm, {})[papers] = head
        _write_atomic(run / "checkpoints.yml", yaml.safe_dump(data, sort_keys=True))


def at_checkpoint(config: dict[str, Any], run: Path, arm: str, papers: int) -> str:
    """库必须仍在检查点 ``papers`` 的版本上（读者与快照要看的是检查点时的库）；返回这个版本。"""
    expected = checkpoints(run)[arm][papers]
    if (now := version(config, run, arm)) != expected:
        raise RuntimeError(f"{arm}: the store moved past checkpoint {papers} ({expected} → {now})")
    return expected


def snapshot(config: dict[str, Any], run: Path, arm: str, papers: int) -> None:
    """检查点的快照 ``snapshots/<组>/k<篇数>/``，供事后的库健康度审计与判分核对（库在两条时间线之间要清空）。
    A3、A2：Cypher 读出的节点、边与提交，加产物文档；A0：检查点标签下的文件树与提交列表；A4：group 的节点与边。

    先导出到 ``k<篇数>.partial/``，完整之后整个目录改名为 ``k<篇数>/``（同一文件系统内的改名是原子的）：
    ``k<篇数>/`` 存在即导出完成。跳过之前仍核对它的 ``meta.yml`` 与必需文件；不合格的另存为 ``.invalid-<时刻>``
    后重导，不静默接受。"""
    out = run / "snapshots" / arm / f"k{papers}"
    if out.exists():
        if snapshot_complete(out, arm):
            return
        out.rename(out.with_name(f"{out.name}.invalid-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}"))
    partial = out.with_name(f"{out.name}.partial")
    if partial.exists():
        shutil.rmtree(partial)
    spec = config["arms"][arm]
    if arm == "A0":  # 按标签导出，与仓库当前状态无关
        export.export_a0(arm_dir(run, "A0") / "repo", f"checkpoint-{papers}", partial)
    else:
        at_checkpoint(config, run, arm, papers)
        if arm in GRAPH:
            export.export_a3(spec["neo4j"], arm_dir(run, arm) / "data", partial, arm=arm)
        else:
            export.export_graphiti(spec["neo4j"], spec["group_id"], partial)
    if not snapshot_complete(partial, arm):
        raise RuntimeError(f"{arm}: snapshot of checkpoint {papers} is incomplete: {partial}")
    os.replace(partial, out)


SNAPSHOT_FILES = {"A0": ("log.jsonl", "tree"), "A4": ("graph.jsonl",)}  # 其余组：graph.jsonl 与 commits.jsonl
SNAPSHOT_COUNTS = {"A0": ("files", "commits"), "A4": ("nodes", "edges")}  # 其余组：nodes、edges、commits、documents


BACKUP_DB = "neo4j"  # 被测系统用 Neo4j 的默认库
BACKUP_FILES = ("neo4j.dump", "data.tar.gz", "sources.tar.gz")


def backup(config: dict[str, Any], run: Path, arm: str, papers: int, timeline: Timeline | None = None) -> None:
    """A3、A2 检查点上的库备份 ``backups/<组>/k<篇数>/``，供读者事后在检查点的库上作答（写读分离，V3 §7 第 9 条）。
    快照（:func:`snapshot`）去掉了向量，恢复它要重算向量，读者看到的就不是写者留下的那个库；备份是原样。

    - ``data.tar.gz``：材料根目录（产物文档的各个版本）；
    - ``sources.tar.gz``：组的已开放来源目录（``sources/``，即 ``PAPERWEAVE_SOURCES``），打包前按材料表逐个核对哈希。
      恢复后提交校验、``read_evidence`` 与过时检测都要读它，缺了会把来源缺失误判成产物过时（审查第 5 条）；
    - ``neo4j.dump``：停下图库的容器（检查点上没有写者会话，MCP 服务也没有起），用该容器实际运行的镜像（镜像 ID，
      不是标签）的 ``neo4j-admin database dump`` 离线导出，再启动容器，等库可连后核对分支头仍是检查点的版本；
    - ``meta.yml``：组、检查点（篇数）、记录的库版本、容器、镜像标签与 ID、三个文件的 SHA-256，以及开放的来源及其
      哈希（``sources``）。

    先写到 ``k<篇数>.partial/``，完整后改名。已有备份只在完整且属于这个检查点（篇数与 ``checkpoints.yml`` 记录的版本
    都对得上，:func:`backup_complete`）时跳过；不合格的另存为 ``k<篇数>.invalid-<时刻>`` 后重做，不静默接受。
    恢复：``neo4j-admin database load`` 到新容器的数据目录，材料根目录与来源目录解包，读者的 MCP 服务指向三者。"""
    if arm not in GRAPH or papers == 0:
        return
    out = run / "backups" / arm / f"k{papers}"
    expected = checkpoints(run)[arm][papers]
    if backup_complete(out, arm, papers, expected):
        return
    if out.exists():
        out.rename(out.with_name(f"{out.name}.invalid-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}"))
    container = config["arms"][arm].get("neo4j_container")
    if not container:
        raise RuntimeError(f"{arm}: neo4j_container is not configured; the checkpoint store cannot be backed up")
    at_checkpoint(config, run, arm, papers)
    image, image_id, data_dir = container_of(container)
    opened = _verified_sources(run, arm, timeline)
    partial = out.with_name(out.name + ".partial")
    shutil.rmtree(partial, ignore_errors=True)
    partial.mkdir(parents=True)
    with tarfile.open(partial / "data.tar.gz", "w:gz") as tar:
        tar.add(arm_dir(run, arm) / "data", arcname="data")
    with tarfile.open(partial / "sources.tar.gz", "w:gz") as tar:
        tar.add(sources_dir(run, arm), arcname="sources")
    _docker("stop", container)
    try:
        partial.chmod(0o777)  # 容器中的 neo4j 用户（7474）要往这里写 dump
        _docker("run", "--rm", "-v", f"{data_dir}:/data", "-v", f"{partial}:/backups", image_id,
                "neo4j-admin", "database", "dump", BACKUP_DB, "--to-path=/backups")  # fmt: skip
    finally:
        partial.chmod(0o755)
        _docker("start", container)
        _wait_store(config, run, arm)
    if (now := version(config, run, arm)) != expected:
        raise RuntimeError(f"{arm}: after the backup the store is at {now}, not at checkpoint {papers} ({expected})")
    meta = {"arm": arm, "papers": papers, "version": expected, "container": container, "image": image,
            "image_id": image_id, "created": datetime.now(UTC).isoformat(timespec="seconds"),
            "sha256": {n: _sha256(partial / n) for n in BACKUP_FILES}, "sources": opened}  # fmt: skip
    (partial / "meta.yml").write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8")
    partial.rename(out)


def _verified_sources(run: Path, arm: str, timeline: Timeline | None) -> dict[str, str]:
    """组的来源目录中的来源 → 内容哈希；给出 ``timeline`` 时逐个与材料表核对，不一致即停。"""
    root = sources_dir(run, arm)
    found = sorted(p.name for p in root.iterdir() if p.is_dir() and not p.name.endswith(".partial")) if root.exists() else []
    digests = {s: source_digest(root, s) for s in found}
    if timeline is not None and timeline.materials:
        wrong = [s for s, d in digests.items() if timeline.materials["sources"].get(s, {}).get("sha256") != d]
        if wrong:
            raise RuntimeError(f"{arm}: opened sources do not match materials.yml: {wrong}")
    return digests


def backup_complete(out: Path, arm: str, papers: int | None = None, version: str | None = None) -> bool:
    """备份是否完整，且属于检查点 ``papers``、库版本 ``version``（审查第 4 条：文件哈希自洽但属于别的检查点的备份
    不算）。版本取 ``checkpoints.yml`` 的记录，不取在线库的当前分支头（早期检查点早已过去）。"""
    try:
        meta = yaml.safe_load((out / "meta.yml").read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return False
    if not isinstance(meta, dict) or meta.get("arm") != arm or not isinstance(meta.get("sha256"), dict):
        return False
    if (papers is not None and meta.get("papers") != papers) or (version is not None and meta.get("version") != version):
        return False
    return all((out / n).exists() and meta["sha256"].get(n) == _sha256(out / n) for n in BACKUP_FILES)


def container_of(name: str) -> tuple[str, str, str]:
    """图库容器的镜像标签、实际运行的镜像 ID 与挂到 ``/data`` 的宿主机目录。``docker run --rm`` 起的容器停下即被
    删除，拒绝。dump 用镜像 ID：标签之后可能指向别的镜像。"""
    info = json.loads(_docker("inspect", name))[0]
    if info["HostConfig"].get("AutoRemove"):
        raise RuntimeError(f"container {name} was started with --rm: stopping it for the backup would delete it")
    data = [m["Source"] for m in info["Mounts"] if m["Destination"] == "/data"]
    if not data:
        raise RuntimeError(f"container {name} has no /data mount on the host")
    return info["Config"]["Image"], info["Image"], data[0]


def _docker(*args: str) -> str:
    done = subprocess.run(["docker", *args], capture_output=True, text=True)
    if done.returncode != 0:
        raise RuntimeError(f"docker {args[0]} failed: {done.stderr[-1000:]}")
    return done.stdout


def _wait_store(config: dict[str, Any], run: Path, arm: str, limit_s: int = 180) -> None:
    deadline = time.monotonic() + limit_s
    while True:
        try:
            version(config, run, arm)
            return
        except Exception:  # 容器刚启动：连接被拒或库尚未就绪
            if time.monotonic() > deadline:
                raise
            time.sleep(2)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_complete(out: Path, arm: str) -> bool:
    """快照是否完整：``meta.yml`` 是这一组的元数据，``counts`` 中该组的计数齐全且都是非负整数，必需文件都在
    （旧导出若中断在 ``counts:`` 之后，解析出的 ``counts`` 为 ``None``，不算完整）。"""
    try:
        meta = yaml.safe_load((out / "meta.yml").read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return False
    if not isinstance(meta, dict) or meta.get("arm") != arm or not isinstance(counts := meta.get("counts"), dict):
        return False
    keys = SNAPSHOT_COUNTS.get(arm, ("nodes", "edges", "commits", "documents"))
    if not all(isinstance(counts.get(k), int) and not isinstance(counts[k], bool) and counts[k] >= 0 for k in keys):
        return False
    return all((out / n).exists() for n in SNAPSHOT_FILES.get(arm, ("graph.jsonl", "commits.jsonl")))


def _plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return str(value) if isinstance(value, Path) else value


TIMING_ONLY = ("reader_workers",)  # 只影响用时的配置项，续跑时可以改。workers_by_group 不在其中：P 的成本进比较，并发影响缓存命中


def _comparable(config: dict[str, Any]) -> dict[str, Any]:
    runner = {k: v for k, v in config.get("runner", {}).items() if k not in TIMING_ONLY}
    return {**config, "runner": runner}


SESSION_CODE = (  # 写者会话实际执行的代码（相对仓库根目录）：被测系统、A2 的消融服务、沙箱内外的转发与来源服务、运行器
    "system/src", "system/pyproject.toml", "packages/graph-doc/src", "packages/graph-doc/pyproject.toml",
    "packages/graph-vc/src", "packages/graph-vc/pyproject.toml", "eval/baselines",
    "eval/src/pweval/harness/bridge.py", "eval/src/pweval/harness/source_server.py",
    "eval/src/pweval/harness/sandbox.py", "eval/src/pweval/harness/timeline.py", "eval/src/pweval/harness/export.py",
    "pyproject.toml", "uv.lock",
)  # fmt: skip


def code_fingerprint(repo: Path = REPO) -> dict[str, Any]:
    """写者会话所执行代码的指纹（审查第 3 条）：``SESSION_CODE`` 下已跟踪与未跟踪（不含忽略的）文件，按路径排序，
    逐个文件的 路径、NUL、磁盘上内容的 SHA-256。按磁盘内容算，未提交的改动也计入；只看提交号或 dirty 标志不够。"""
    listed = _git(repo, "ls-files", "-co", "--exclude-standard", "-z", "--", *SESSION_CODE).split("\0")
    files = sorted({f for f in listed if f and (repo / f).is_file()})
    digest = hashlib.sha256()
    for f in files:
        digest.update(f"{f}\0".encode() + hashlib.sha256((repo / f).read_bytes()).digest())
    return {"sha256": digest.hexdigest(), "files": len(files)}


def check_code(run: Path, expected: dict[str, Any]) -> None:
    """会话开始前：执行的代码仍是这次调用开始时的（MCP 服务、来源服务每个会话从工作区重新加载）。运行中有人改了
    这些文件，这一组停下，不让同一条时间线中途换实现。"""
    if (now := code_fingerprint()) != expected:
        raise RuntimeError(f"{run.name}: the session code changed during the run ({expected['sha256'][:12]} → "
                           f"{now['sha256'][:12]}); restart with --allow-code-change if the change is intended")  # fmt: skip


def _record_run(run: Path, config_path: Path, config: dict[str, Any], argv: list[str], *,
                allow_change: bool = False, code: dict[str, Any] | None = None,
                allow_code_change: bool = False) -> None:  # fmt: skip
    """``run.yml``：每次调用追加一条——时间、参数、实际生效的配置（含 ``--neo4j`` 的覆盖）、仓库与题库的提交、
    pi 的版本。种子与会话可以分几次调用完成。续跑时生效的配置（只影响用时的项除外）或题库的提交与第一次不同，
    就拒绝运行，除非给出 ``--allow-config-change``（改动随这次调用记下）。给出 ``code``（写者会话所执行代码的指纹，
    :func:`code_fingerprint`）时，它与第一次不同也拒绝，除非给出 ``--allow-code-change``：工程修正与正式实验代码不变
    分开处理，修正须显式放行并记下。仓库其余部分的提交可以变（如读者侧的开发），各次的提交都留在记录中。"""
    path = run / "run.yml"
    with _locked(path):
        _record_invocation(path, config_path, config, argv, allow_change, code, allow_code_change)


def _record_invocation(path: Path, config_path: Path, config: dict[str, Any], argv: list[str], allow_change: bool,
                       code: dict[str, Any] | None = None, allow_code_change: bool = False) -> None:  # fmt: skip
    run = path.parent
    record = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {"invocations": []}

    def commit(repo: Path) -> dict[str, Any]:
        head = _git(repo, "rev-parse", "HEAD").strip()
        return {"commit": head, "dirty": bool(_git(repo, "status", "--porcelain", "--untracked-files=no").strip())}

    effective, probes = _plain(config), commit(config["probes_repo"])
    if record["invocations"]:
        first = record["invocations"][0]
        changed = [name for name, a, b in (("config", _comparable(first.get("config", {})), _comparable(effective)),
                                           ("probes repo", first.get("probes"), probes)) if a != b]  # fmt: skip
        if changed and not allow_change:
            raise SystemExit(f"{run}: {' and '.join(changed)} differ from the first invocation; "
                             "pass --allow-config-change to continue with them")  # fmt: skip
        if code is not None and first.get("code") != code and not allow_code_change:
            raise SystemExit(f"{run}: the session code differs from the first invocation ({first.get('code')} → {code}); "
                             "pass --allow-code-change to continue with it")  # fmt: skip
    record["invocations"].append({
        "started": datetime.now(UTC).isoformat(timespec="seconds"),
        "argv": argv,
        "config_file": str(config_path),
        "config": effective,
        "repo": commit(REPO),
        **({"code": code, "allow_code_change": allow_code_change} if code is not None else {}),
        "probes": probes,
        "pi": pi_version(),
        "sandbox_python": site_record(),
    })  # fmt: skip
    _write_atomic(path, yaml.safe_dump(record, allow_unicode=True, sort_keys=False))


def preflight(config: dict[str, Any], arms: list[str]) -> list[str]:
    """各组要用的服务是否连得上（TCP）：大模型、图库、Graphiti；A3、A2 的图库容器能否停下备份（:func:`backup`）。"""
    problems = []
    for arm in arms:
        spec = config["arms"][arm]
        if arm in GRAPH:
            try:
                container_of(spec.get("neo4j_container") or "")
            except (RuntimeError, IndexError, json.JSONDecodeError) as exc:
                problems.append(f"{arm} neo4j_container {spec.get('neo4j_container')!r}: {exc}")
        for key in ("llm", "neo4j", "graphiti"):
            if key in spec:
                url = urlsplit(spec[key])
                try:
                    socket.create_connection((url.hostname, url.port or 80), timeout=5).close()
                except OSError as exc:
                    problems.append(f"{arm} {key} {spec[key]}: {exc}")
    return problems


# ---------------------------------------------------------------- 运行


def emit(kind: str, arm: str, **fields: Any) -> None:
    """进度事件，一行一个，供监视者过滤：``<类别> <组> <时刻> 键=值 …``。类别：RUN、SETUP、SESSION、READER、
    CHECKPOINT、DONE、ERROR（随后是 traceback）、EXIT。含空格的值加引号。"""
    parts = [kind, arm, datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")]
    for key, value in fields.items():
        text = str(value)
        parts.append(f"{key}={json.dumps(text, ensure_ascii=False) if ' ' in text or not text else text}")
    with _LOCK:
        print(" ".join(parts), flush=True)


def run_arm(config: dict[str, Any], timeline: Timeline, run: Path, arm: str, until: int | None, reset: bool,
            with_readers: bool = False, code: dict[str, Any] | None = None) -> None:  # fmt: skip
    """一组的写者时间线。``with_readers`` 留给 f3 之前的检查点读者；f3 的读者在备份上离线作答（M2），不经这里。"""
    if 0 not in (checkpoints(run).get(arm) or {}):
        setup(config, timeline, run, arm, reset=reset)
        checkpoint(config, run, arm, 0)
        emit("SETUP", arm, version=checkpoints(run)[arm][0])
    snapshot(config, run, arm, 0)
    done = _done(run)
    inflight = json.loads(_inflight(run, arm).read_text(encoding="utf-8")) if _inflight(run, arm).exists() else None
    if inflight and (arm, inflight["seq"]) in done:  # 记账之后、删掉之前退出
        _inflight(run, arm).unlink()
        inflight = None
    last_seq = 0
    for step in timeline.steps:
        if step["type"] == "checkpoint":
            if all((arm, s["seq"]) in done for s in timeline.steps if "seq" in s and s["seq"] <= last_seq):
                if step["papers"] not in (checkpoints(run).get(arm) or {}):
                    checkpoint(config, run, arm, step["papers"])
                snapshot(config, run, arm, step["papers"])
                backup(config, run, arm, step["papers"], timeline)  # 读者之前：读者以后也可以在备份上离线作答
                answers = {}
                for group in GROUPS:
                    if with_readers:
                        readers(config, timeline, run, arm, step["papers"], group=group)  # 读者答完，下一位写者才开始
                        expected = len(eligible(timeline, step["papers"], group))
                        answers[group] = f"{len(answered(run, arm, step['papers'], group))}/{expected}"
                    else:
                        answers[group] = "skipped"
                emit("CHECKPOINT", arm, k=step["papers"], version=checkpoints(run)[arm][step["papers"]],
                     snapshot="ok", backup="ok" if arm in GRAPH and step["papers"] else "-",
                     answers=answers["main"], aux=answers["aux"])  # fmt: skip
            continue
        last_seq = step["seq"]
        if until is not None and step["seq"] > until:
            emit("DONE", arm, until=until)
            return
        if (arm, step["seq"]) in done:
            continue
        if code is not None:
            check_code(run, code)
        open_sources(config, timeline, run, arm, timeline.opened_through(step["seq"]))  # 会话开始时开放（f3 §3.2）
        record, rerun_of = None, None
        if inflight and inflight["seq"] == step["seq"]:
            outcome = recover(config, timeline, run, arm, step, inflight)
            record, rerun_of, inflight = outcome.get("record"), outcome.get("rerun"), None
        if record is None:
            record = session(config, timeline, run, arm, step)
            if rerun_of:
                record["rerun_after_interruption"] = rerun_of
        if code is not None:
            record["code"] = code["sha256"]
        _append(run, record)
        _inflight(run, arm).unlink(missing_ok=True)
        done.add((arm, step["seq"]))
        flags = [f for f in ("recovered", "rerun_after_interruption") if record.get(f)]
        emit("SESSION", arm, seq=step["seq"], identity=step["identity"], type=step["type"], exit=record["exit"],
             seconds=record["seconds"], network=len(record["network"]), version=record.get("version_after"),
             **({"flags": ",".join(flags)} if flags else {}))  # fmt: skip
    emit("DONE", arm, until="end")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("name", help="运行名")
    parser.add_argument("--config", default=str(CONFIG))
    parser.add_argument("--arms", default=",".join(F3_ARMS))
    parser.add_argument("--until", type=int, help="只跑到这个序号（试跑）")
    parser.add_argument("--neo4j", help="覆盖图库地址，如 A3=bolt://localhost:7695（A4 为 Graphiti 的库）")
    parser.add_argument("--reset", action="store_true",
                        help="起点建立前库不空时清空（A3、A2 清整个图库，A4 清配置中的 group）；已有会话记录的组拒绝重建")
    parser.add_argument("--allow-code-change", action="store_true",
                        help="续跑时允许写者会话所执行的代码与第一次调用不同（工程修正；指纹记入 run.yml）")
    parser.add_argument("--allow-config-change", action="store_true",
                        help="续跑时允许生效的配置或题库提交与第一次调用不同（改动记入 run.yml）")
    args = parser.parse_args(argv)
    config_path = Path(args.config).resolve()
    config = load_config(config_path)
    for item in filter(None, (args.neo4j or "").split(",")):
        arm, uri = item.split("=", 1)
        config["arms"][arm]["neo4j"] = uri
    arms = args.arms.split(",")
    if unknown := set(arms) - set(ARMS):
        raise SystemExit(f"unknown arms: {sorted(unknown)}")
    if pending := [a for a in arms if a not in F3_ARMS]:
        raise SystemExit(f"{','.join(pending)}: the f3 writer conditions are not implemented for these arms yet (M3, M4)")
    if problems := preflight(config, arms):
        raise SystemExit("services are not reachable:\n" + "\n".join(problems))
    run = config["workdir_root"] / args.name
    run.mkdir(parents=True, exist_ok=True)
    code = code_fingerprint()
    _record_run(run, config_path, config, list(argv) if argv is not None else sys.argv[1:],
                allow_change=args.allow_config_change, code=code, allow_code_change=args.allow_code_change)
    timeline = timeline_of(config)
    emit("RUN", "-", name=args.name, arms=",".join(arms), pid=os.getpid())

    def guarded(arm: str) -> bool:  # 一组出错只停这一组，其他组照常跑完
        try:
            with _arm_lock(run, arm) as mine:
                if not mine:
                    emit("ERROR", arm, error="another process is running this arm; not started")
                    return False
                run_arm(config, timeline, run, arm, args.until, args.reset, code=code)
            return True
        except BaseException as exc:
            emit("ERROR", arm, error=f"{type(exc).__name__}: {exc}"[:500])
            traceback.print_exc()
            sys.stdout.flush()
            return False

    with ThreadPoolExecutor(max_workers=len(arms)) as pool:
        results = dict(zip(arms, pool.map(guarded, arms), strict=True))
    failed = [a for a, ok in results.items() if not ok]
    emit("EXIT", "-", failed=",".join(failed) or "none")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["Timeline", "load_config", "load_timeline", "main", "network_calls", "prompt", "setup"]
