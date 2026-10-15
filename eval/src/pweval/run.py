"""T1 先导的一次运行：按配置建立各组的起点（检查点 0），按顺序调度写者会话，在检查点存档。

    python -m pweval.run <运行名> [--config …] [--arms A3,A0] [--limit N] [--reset-a3]

运行目录 ``<workdir_root>/<运行名>/``：

- ``run.yml``：配置副本、仓库提交与是否有未提交改动、开始时间；``code.tar.gz``：开始时 t1、system 与 packages 的
  源码（仓库有未提交改动时据此复现）；
- ``A3/neo4j-export.jsonl``：各组跑完后 A3 图库的全部节点与关系（图库会被下一次运行清空）；
- ``sessions.jsonl``：每次会话一行（组、序号、论文、写者、退出码、用时、事件流与会话记录的位置、会话前后的库版本、
  模型请求出错的次数与原因；A0 另记会话结束时笔记库中没有提交的改动）；
- ``checkpoints.yml``：各组每个检查点的库版本（A3 为分支头的提交 id，A0 为 git 标签 ``checkpoint-<k>`` 的提交）；
- ``checkpoints/<k>/<组>/``：检查点的快照；
- ``probes.jsonl``：配置给出 ``probes`` 时，每个检查点上读者对有效探针的回答（:mod:`pweval.probe`），在下一个写者开始
  之前跑完，所以读到的就是检查点的库；
- ``A3/data/``：A3 的材料根目录（论文副本与产物文档，``E09_DATA``）；``A0/store/``：A0 的笔记库（git 仓库），
  ``A0/papers/``：A0 的论文副本。两组的论文副本起初只有写者最初拿到的版本，版本事件开始前才放入新版本
  （:mod:`pweval.versions`）；
- ``<组>/<写者>/``：写者的沙箱目录（见 :mod:`pweval.sandbox`）。

A3 的起点：清空图库（``--reset-a3``，只允许配置中的 T1 图库），用系统的命令行按 ``seed_docs`` 的顺序（作者取文档的
``by``）提交，再经 MCP 检入种子 Leaderboard 与 skill（:mod:`pweval.seeding`）。A0 的起点由 A3 检查点 0 的快照渲染，加上
同样的种子 Leaderboard（:mod:`pweval.a0_seed`），两组内容因此相同。

每个检查点导出冻结的快照 ``checkpoints/<k>/<组>/``（:mod:`pweval.snapshot`），之后的测量只读快照。评测代码不导入被测
系统（evaluation_draft §10.1）：A3 的库只经命令行、MCP 与 Cypher 读取接触。

会话按“槽位”调度：每个槽位是一篇论文的一个写者，或一个版本事件（``events``：某个检查点之后，维护者把论文的新版本
带进库）。组内按槽位顺序逐个运行（写者轮流写），各组同时运行：两组的存储互不相干，并行只缩短总时间。
``runner.endpoints`` 可以给各组指定模型服务（权重与配置相同的副本），会话记录中记下所用的服务。中断后用同一个
运行名重跑，已记录的会话跳过。
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import threading
import urllib.request
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

from . import probe, seeding, skills, snapshot, versions
from .a0_seed import commit_seed, read_boards, render, write
from .paths import REPO, SEEDS
from .sandbox import Arm, Paths, Writer, pi_version, prepare, run_session

PROTECTED = {7687, 7688}  # neo4j-e09 与 neo4j-test：不清空
_LOCK = threading.Lock()  # 各组并行时，sessions.jsonl 与 checkpoints.yml 的写入


@dataclass(frozen=True)
class Slot:
    index: int  # 从 1 开始
    paper: dict[str, Any]
    writer: dict[str, Any]
    checkpoint: int | None  # 这个槽位之后存档的检查点编号
    event: dict[str, Any] | None = None  # 版本事件的槽位：配置中 events 的一项


def schedule(config: dict[str, Any]) -> list[Slot]:
    """槽位序列。配置有 ``assignment`` 时按伪用户分配（:func:`assign`），否则按先导的写者轮流（``alternate``）。
    版本事件的槽位紧接在它的检查点之后。"""
    if "assignment" in config:
        return _assigned(config)
    plan = config["schedule"]
    writers, papers = config["writers"], config["corpus"]["papers"]
    every = plan["checkpoint_every_papers"]
    by_arxiv = {p["arxiv"]: p for p in papers}
    event_writers = {w["id"]: w for w in config.get("event_writers") or []}
    slots: list[Slot] = []
    for n, paper in enumerate(papers, 1):
        order = writers if plan["order"] != "alternate" or n % 2 else writers[::-1]
        for i, writer in enumerate(order):
            last = i == len(order) - 1 and n % every == 0
            slots.append(Slot(len(slots) + 1, paper, writer, n // every if last else None))
            if last:
                for event in versions.events(config):
                    if event["after_checkpoint"] == n // every:
                        writer = event_writers[event["writer"]]
                        slots.append(Slot(len(slots) + 1, by_arxiv[event["paper"]], writer, None, event))
    if len(slots) != plan["sessions_per_arm"]:
        raise ValueError(f"schedule has {len(slots)} sessions, config says {plan['sessions_per_arm']}")
    return slots


def assign(papers: list[Any], users: list[str], seed: int, overlap: float) -> list[list[str]]:
    """每篇论文分给哪些伪用户（evaluation_draft §2.1、§4.2）。固定种子：先抽出 ``round(overlap × 篇数)`` 篇重叠的
    论文，再逐篇随机选一个伪用户，重叠的论文再选一个不同的。总是在完整的伪用户列表上抽，各种写者构成因此共用同一份
    分配与同样的随机数序列。"""
    rng = random.Random(seed)
    overlapped = set(rng.sample(range(len(papers)), round(overlap * len(papers))))
    out = []
    for i in range(len(papers)):
        first = rng.choice(users)
        out.append([first, rng.choice([u for u in users if u != first])] if i in overlapped else [first])
    return out


def _assigned(config: dict[str, Any]) -> list[Slot]:
    """按伪用户分配的槽位。``composition`` 选写者构成：构成之外的伪用户的槽位交给构成中的第一位，会话数与论文顺序
    在各构成之间不变，只差意图与身份。检查点在每 ``checkpoint_every_papers`` 篇的最后一个会话之后。"""
    if versions.events(config):
        raise ValueError("version events are not scheduled with pseudo-user assignment")
    plan, papers = config["assignment"], config["corpus"]["papers"]
    users = {w["id"]: w for w in config["writers"]}
    members = config["compositions"][config["composition"]]
    every = config["schedule"]["checkpoint_every_papers"]
    slots: list[Slot] = []
    plan_users = assign(papers, list(users), plan["seed"], plan["overlap"])
    for n, (paper, chosen) in enumerate(zip(papers, plan_users, strict=True), 1):
        for i, user in enumerate(chosen):
            writer = users[user if user in members else members[0]]
            last = i == len(chosen) - 1 and n % every == 0
            slots.append(Slot(len(slots) + 1, paper, writer, n // every if last else None))
    return slots


def prompt(config: dict[str, Any], arm: str, slot: Slot, titles: dict[str, str]) -> str:
    paper = slot.paper
    given = paper["arxiv"] if slot.event else paper.get("first_version") or paper["arxiv"]
    fields = {
        "title": titles[paper["arxiv"].rsplit("v", 1)[0]],
        "arxiv": given,
        "material": f"papers/{given}/paper.md",
        "old_material": f"papers/{paper.get('first_version')}/paper.md",
        "method": paper.get("method", ""),
    }
    if "background" in slot.writer:  # 伪用户：长期背景 + 各伪用户相同的任务句
        task = f"{slot.writer['background'].rstrip()}\n\n{config['writer_task'].format(**fields)}"
    else:
        task = slot.writer["task"].format(**fields)
    closing = config["writer_closing"].format(store=config["arms"][arm]["store"])
    return f"{task.rstrip()}\n\n{closing.rstrip()}\n"


def titles_of(config: dict[str, Any]) -> dict[str, str]:
    data = yaml.safe_load((REPO / config["corpus"]["candidates"]).read_text(encoding="utf-8"))
    return {p["arxiv_id"]: p["title"] for d in data["domains"] for p in d["papers"]}


# ---------------------------------------------------------------- 起点


def setup_a3(run: Path, config: dict[str, Any], *, reset: bool) -> None:
    arm = config["arms"]["A3"]
    data = run / "A3/data"
    if not (data / "papers").exists():
        copy_papers(config, data / "papers", versions.initial_papers(config))
    driver = snapshot.driver(arm["neo4j"])
    try:
        nodes = driver.execute_query("MATCH (n) RETURN count(n) AS n").records[0]["n"]
        if nodes:
            if not reset:
                raise SystemExit(f"{arm['neo4j']} holds {nodes} nodes; pass --reset-a3 to clear it for this run")
            if urlsplit(arm["neo4j"]).port in PROTECTED:
                raise SystemExit(f"refusing to clear {arm['neo4j']}")
            driver.execute_query("MATCH (n) DETACH DELETE n")
    finally:
        driver.close()
    env = _system_env(arm, data)
    for doc in config["seed_docs"]:
        args = [str(REPO / doc["doc"]), "--source", doc["source"], "--apply"]  # 作者取文档的 by
        args += ["--message", f"seed: {Path(doc['doc']).name}"] + ([] if doc["dedup"] else ["--no-dedup"])
        if not arm.get("embeddings", True):
            args.append("--no-embed")
        done = subprocess.run([sys.executable, "-m", "paperweave", *args], env=env, capture_output=True, text=True)
        if done.returncode != 0:
            raise SystemExit(f"seeding {doc['doc']} failed:\n{done.stdout}\n{done.stderr}")
    env = {**env, "E09_NO_EMBED": "1"} if not arm.get("embeddings", True) else env
    ok, replies = seeding.check_in(env)
    if not ok:
        raise SystemExit(f"checking in the seed artifacts failed:\n{replies[-1][1]}")


def setup_a0(run: Path, config: dict[str, Any]) -> None:
    """A0 的检查点 0：由 A3 检查点 0 的快照渲染笔记库，加上种子 Leaderboard，以 ``seed`` 提交。"""
    store = run / "A0/store"
    if store.exists():
        return
    snap = run / "checkpoints/0/A3"
    if not (snap / "graph.jsonl").exists():
        raise SystemExit(f"A0 checkpoint 0 is rendered from A3's snapshot, which is missing: {snap}")
    copy_papers(config, run / "A0/papers", versions.initial_papers(config))
    write(render(snapshot.load(snap), read_boards(SEEDS / "leaderboards")), store)
    commit_seed(store)


def check_checkpoint0(run: Path, config: dict[str, Any]) -> list[str]:
    """A3 检查点 0 的不变式：每份入库文档与每批种子产物各一个提交；种子产物在库中按原样保存。"""
    snap = snapshot.load(run / "checkpoints/0/A3")
    problems = []
    expected = len(config["seed_docs"]) + len(seeding.BATCHES)
    if len(snap.commits) != expected:
        problems.append(f"{len(snap.commits)} commits, expected {expected}")
    stored = {
        snap.nodes[dst]["props"].get("title"): snap.nodes[src]["props"]["path"]
        for src, rel, dst, _ in snap.edges
        if rel == "MATERIAL_OF" and "Artifact" in snap.nodes.get(dst, {}).get("labels", [])
    }
    for pattern, _ in seeding.BATCHES:
        for doc in seeding.documents(pattern):
            text = (SEEDS / doc).read_text(encoding="utf-8")
            matches = [path for path in stored.values() if snap.document(path) == text]
            if len(matches) != 1:
                problems.append(f"{doc}: stored {len(matches)} times verbatim")
    return problems


def papers_dir(run: Path, config: dict[str, Any], arm: str) -> Path:
    """组的论文副本；早先的运行没有 A0 副本时用语料目录。"""
    own = run / ("A3/data/papers" if arm == "A3" else "A0/papers")
    return own if own.exists() else REPO / config["corpus"]["material_root"] / "papers"


def copy_papers(config: dict[str, Any], target: Path, arxivs: list[str]) -> None:
    """把语料中的这些论文目录复制到 ``target``（已有的不动）。"""
    source = REPO / config["corpus"]["material_root"] / "papers"
    for arxiv in arxivs:
        if not (target / arxiv).exists():
            shutil.copytree(source / arxiv, target / arxiv)


# ---------------------------------------------------------------- 检查点与版本


def version(run: Path, config: dict[str, Any], arm: str) -> str | None:
    if arm == "A0":
        done = subprocess.run(["git", "-C", str(run / "A0/store"), "rev-parse", "HEAD"], capture_output=True, text=True)
        return done.stdout.strip() or None
    return snapshot.head(config["arms"]["A3"]["neo4j"])


def checkpoint(run: Path, config: dict[str, Any], arm: str, k: int) -> str | None:
    """记下检查点的库版本，并导出快照 ``checkpoints/<k>/<组>/``（已导出的不重导，续跑时保留原来的快照）。"""
    if arm == "A0":
        store = str(run / "A0/store")
        tag = ["git", "-C", store, "-c", "user.name=t1", "-c", "user.email=t1@t1.example", "tag", "-f", f"checkpoint-{k}"]
        subprocess.run(tag, check=True, capture_output=True)
    out = run / "checkpoints" / str(k) / arm
    if not (out / "meta.yml").exists():
        if out.exists():
            shutil.rmtree(out)  # 上次导出到一半
        if arm == "A3":
            snapshot.export_a3(config["arms"]["A3"]["neo4j"], run / "A3/data", out)
        else:
            snapshot.export_a0(run / "A0/store", f"checkpoint-{k}", out)
    head = version(run, config, arm)
    path = run / "checkpoints.yml"
    with _LOCK:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
        data.setdefault(arm, {})[k] = head
        path.write_text(yaml.safe_dump(data, sort_keys=True), encoding="utf-8")
    return head


# ---------------------------------------------------------------- 运行


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config_path = Path(args.config).resolve()
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["_path"] = str(config_path)
    arms = args.arms.split(",")
    run = Path(config["runner"]["workdir_root"]).expanduser() / args.name
    run.mkdir(parents=True, exist_ok=True)
    if args.composition and args.composition not in config.get("compositions", {}):
        raise SystemExit(f"unknown writer composition {args.composition!r}: {sorted(config.get('compositions', {}))}")
    if "assignment" in config and not args.composition and not (run / "run.yml").exists():
        raise SystemExit(f"choose a writer composition with --composition: {sorted(config['compositions'])}")
    overrides: dict[str, Any] = {"neo4j": args.neo4j, "composition": args.composition}
    if args.endpoints:
        overrides["endpoints"] = dict(e.split("=", 1) for e in args.endpoints.split(","))
    _record_run(run, config_path, arms, {k: v for k, v in overrides.items() if v})
    config = run_config(run, config)
    if url := config["runner"].get("embeddings_url"):
        os.environ.setdefault("EMBED_URL", url)  # 系统的嵌入服务地址，子进程（命令行、MCP 服务）继承
    if problems := preflight(config, arms):
        raise SystemExit("services are not reachable:\n" + "\n".join(problems))

    if "A3" in arms and "A3" not in _checkpoints(run):
        setup_a3(run, config, reset=args.reset_a3)
        checkpoint(run, config, "A3", 0)
        if problems := check_checkpoint0(run, config):
            raise SystemExit("A3 checkpoint 0 does not hold the seeds: " + "; ".join(problems))
    if "A0" in arms and "A0" not in _checkpoints(run):
        setup_a0(run, config)
        checkpoint(run, config, "A0", 0)

    probes = probe.for_run(config, REPO)
    if probes is not None and (problems := probe.check_anchors(probes, REPO / config["corpus"]["material_root"])):
        raise SystemExit("probe gold does not match the papers:\n" + "\n".join(problems))
    titles = titles_of(config)
    done = _done(run)
    default_llm = _llm_url(config["runner"]["model"])
    slots = schedule(config)[: args.limit] if args.limit else schedule(config)

    def run_arm(arm: str) -> None:
        llm = (config["runner"].get("endpoints") or {}).get(arm, default_llm)
        for i, slot in enumerate(slots):
            if (arm, slot.index) in done:
                following = slots[i + 1] if i + 1 < len(slots) else None
                if slot.checkpoint is not None and (following is None or (arm, following.index) not in done):
                    # 续跑：上次停在这个检查点之后、下一个写者之前，补齐检查点与读者（已记录的探针跳过）
                    if slot.checkpoint not in (_checkpoints(run).get(arm) or {}):
                        checkpoint(run, config, arm, slot.checkpoint)
                    if probes is not None:
                        _require_services(config, arm)
                        probe.run_probes(run, config, probes, arm, slot.checkpoint, llm)
                continue
            if slot.event:  # 新版本此刻才出现在论文副本中
                copy_papers(config, papers_dir(run, config, arm), [slot.event["paper"]])
            _require_services(config, arm)
            record = _session(run, config, arm, slot, prompt(config, arm, slot, titles), llm)
            with _LOCK, open(run / "sessions.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            print(
                f"[{arm} {slot.index:02d}] {slot.writer['id']} {slot.paper['short']}: "
                f"exit {record['exit']}, {record['seconds']}s",
                flush=True,
            )
            if slot.checkpoint is not None:
                checkpoint(run, config, arm, slot.checkpoint)
                if probes is not None:  # 下一个写者开始之前：读者读到的就是检查点的库
                    _require_services(config, arm)
                    probe.run_probes(run, config, probes, arm, slot.checkpoint, llm)

    with ThreadPoolExecutor(max_workers=len(arms)) as pool:
        for future in [pool.submit(run_arm, arm) for arm in arms]:
            future.result()  # 一组出错时报出，另一组照常跑完
    if "A3" in arms:
        export_a3(run, config)
    return 0


def export_a3(run: Path, config: dict[str, Any]) -> Path:
    """A3 图库的全部节点与关系（含版本记录）写成 JSONL，供图库清空后复查。"""
    out = run / "A3/neo4j-export.jsonl"
    driver = snapshot.driver(config["arms"]["A3"]["neo4j"])
    try:
        nodes = driver.execute_query("MATCH (n) RETURN elementId(n) AS id, labels(n) AS labels, properties(n) AS props")
        edges = driver.execute_query(
            "MATCH (a)-[e]->(b) RETURN elementId(a) AS a, type(e) AS type, elementId(b) AS b, properties(e) AS props"
        )
    finally:
        driver.close()
    with open(out, "w", encoding="utf-8") as f:
        for r in nodes.records:
            f.write(json.dumps({"node": r["id"], "labels": r["labels"], "props": r["props"]}, default=str) + "\n")
        for r in edges.records:
            f.write(json.dumps({"edge": [r["a"], r["type"], r["b"]], "props": r["props"]}, default=str) + "\n")
    return out


def _session(run: Path, config: dict[str, Any], arm: str, slot: Slot, text: str, llm: str) -> dict[str, Any]:
    spec = config["arms"][arm]
    w = slot.writer
    writer = Writer(w["id"], w["user"], w["agent"])
    papers = papers_dir(run, config, arm)
    if arm == "A3":
        sandbox_arm = Arm(
            "A3", papers, neo4j=spec["neo4j"], data=run / "A3/data", embeddings=spec.get("embeddings", True)
        )
    else:
        sandbox_arm = Arm("A0", papers, store=run / "A0/store")
    paths = Paths(run / arm / writer.id)
    runner = config["runner"]
    prepare(
        paths, sandbox_arm, runner["model"], runner["thinking"], runner["context_window"], runner["http_idle_timeout_ms"]
    )
    interrupted: list[str] = []
    if arm == "A0":  # 上一次运行在会话中途被终止时留下的改动：同样存档后丢弃，不留给这个写者
        stale = Path(f"runs/{datetime.now(UTC):%Y%m%dT%H%M%S}.interrupted.leftover.patch")
        interrupted = discard_leftovers(run / "A0/store", paths.root / stale)
    skills_placed = skills.place(paths, sandbox_arm, writer) if arm == "A3" else None
    before = version(run, config, arm)
    started = datetime.now(UTC).isoformat(timespec="seconds")
    result = run_session(
        paths, sandbox_arm, writer, text, timeout_s=config["runner"]["session_timeout_min"] * 60, llm=llm
    )
    record = {
        "arm": arm,
        "index": slot.index,
        "paper": slot.paper["arxiv"] if slot.event else slot.paper.get("first_version") or slot.paper["arxiv"],
        "writer": writer.id,
        "event": bool(slot.event),
        "llm": llm,
        "started": started,
        **result,
        "events": f"{arm}/{writer.id}/{result['events']}",
        "session": [f"{arm}/{writer.id}/{s}" for s in result["session"]],
        "request_errors": request_errors(paths.root / result["events"]),
        "before": before,
        "after": version(run, config, arm),
        "prompt": text,
    }
    if skills_placed is not None:
        record["skills"] = skills_placed
    if arm == "A0":
        patch = Path(result["events"]).with_suffix(".leftover.patch")
        record["leftover"] = discard_leftovers(run / "A0/store", paths.root / patch)
        if record["leftover"]:
            record["leftover_patch"] = f"{arm}/{writer.id}/{patch}"
        if interrupted:
            record["interrupted_leftover"] = interrupted
            record["interrupted_leftover_patch"] = f"{arm}/{writer.id}/{stale}"
    return record


def request_errors(events: Path) -> list[str]:
    """会话中出错结束的模型请求（pi 事件流中 ``stopReason: error`` 的助手消息），每次一条原因。"""
    errors = []
    if not events.exists():
        return errors
    for line in events.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = event.get("message") or {}
        if event.get("type") == "message_end" and message.get("stopReason") == "error":
            errors.append(str(message.get("errorMessage") or "error"))
    return errors


def discard_leftovers(store: Path, patch: Path) -> list[str]:
    """A0 会话结束后笔记库中没有提交的改动：存成补丁、返回改动的文件清单，然后丢弃。

    与 A3 对称：A3 中没有经 Commit 的内容不进库，A0 中没有 git commit 的内容也不留给下一个写者。"""

    def git(*args: str) -> str:
        return subprocess.run(["git", "-C", str(store), *args], check=True, capture_output=True, text=True).stdout

    changed = [line[3:] for line in git("status", "--porcelain", "--untracked-files=all").splitlines()]
    if changed:
        git("add", "-A")
        patch.parent.mkdir(parents=True, exist_ok=True)
        patch.write_text(git("diff", "--cached", "--binary", "HEAD"), encoding="utf-8")
        git("reset", "--hard", "HEAD")
        git("clean", "-fd")
    return changed


def run_config(run: Path, config: dict[str, Any]) -> dict[str, Any]:
    """配置加上这次运行的覆盖（``run.yml`` 的 ``overrides``）：A3 图库、各组的模型服务决定在哪里跑，不改协议；
    ``composition`` 选择这条时间线的写者构成（配置中 ``compositions`` 的一项）。pweval.health、pweval.probe、pweval.grade
    读同一份。"""
    path = run / "run.yml"
    overrides = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("overrides") or {} if path.exists() else {}
    config = {**config, "arms": {**config["arms"]}, "runner": {**config["runner"]}}
    if overrides.get("neo4j"):
        config["arms"]["A3"] = {**config["arms"]["A3"], "neo4j": overrides["neo4j"]}
    if overrides.get("endpoints"):
        config["runner"]["endpoints"] = overrides["endpoints"]
    if overrides.get("composition"):
        config["composition"] = overrides["composition"]
    if "assignment" in config and config.get("composition") not in config.get("compositions", {}):
        raise ValueError(f"{path} names no writer composition of {sorted(config.get('compositions', {}))}")
    return config


def _record_run(run: Path, config_path: Path, arms: list[str], overrides: dict[str, Any]) -> None:
    """第一次运行记下 ``run.yml``；之后每次（续跑）另存一份源码快照 ``code-<时间>.tar.gz``。覆盖只能在第一次给出，
    续跑时给出不同的覆盖即停止。"""
    path = run / "run.yml"
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    sources = ["eval", "system/src", "packages"]
    if path.exists():
        recorded = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("overrides") or {}
        if overrides and overrides != recorded:
            raise SystemExit(f"this run was started with overrides {recorded}; resume it without new ones")
        subprocess.run(
            ["tar", "czf", str(run / f"code-{stamp}.tar.gz"), "--exclude=__pycache__", "--exclude=.pytest_cache", *sources],
            cwd=REPO,
            check=True,
        )
        return
    sha = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(REPO), "status", "--porcelain", "--", "eval", "system", "packages"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    data = {
        "started": datetime.now(UTC).isoformat(timespec="seconds"),
        "repo_commit": sha,
        "repo_dirty": bool(dirty),
        "arms": arms,
        "config_file": str(config_path.relative_to(REPO)),
        "overrides": overrides,
        # 写者与读者所用的 pi 与 node（换机器后版本可能不同，运行之间据此区分）
        "agent_runtime": {"pi": pi_version(), "node": _node_version()},
    }
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    shutil.copy(config_path, run / "config.yml")
    subprocess.run(
        ["tar", "czf", str(run / "code.tar.gz"), "--exclude=__pycache__", "--exclude=.pytest_cache", *sources],
        cwd=REPO,
        check=True,
    )


def _node_version() -> str:
    done = subprocess.run(["node", "--version"], capture_output=True, text=True)
    return done.stdout.strip() or "unknown"


def _checkpoints(run: Path) -> dict[str, Any]:
    path = run / "checkpoints.yml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _done(run: Path) -> set[tuple[str, int]]:
    path = run / "sessions.jsonl"
    if not path.exists():
        return set()
    return {(r["arm"], r["index"]) for r in map(json.loads, path.read_text(encoding="utf-8").splitlines())}


def preflight(config: dict[str, Any], arms: list[str]) -> list[str]:
    """开跑前确认各组的模型服务与（A3 用嵌入时）嵌入服务都能连上：服务不在时种库或写者会话会中途失败，留下半截的
    运行。只发只读请求（``/models``），代理按环境变量。"""
    default = _llm_url(config["runner"]["model"])
    urls = {f"{arm} model service": (config["runner"].get("endpoints") or {}).get(arm, default) for arm in arms}
    embed = os.environ.get("EMBED_URL") or config["runner"].get("embeddings_url")
    if "A3" in arms and config["arms"]["A3"].get("embeddings", True) and embed:
        urls["embedding service"] = embed
    problems = []
    for name, url in urls.items():
        models = url.rsplit("/", 1)[0] + "/models" if url.endswith("/embeddings") else url.rstrip("/") + "/models"
        try:
            with urllib.request.urlopen(models, timeout=15) as reply:
                reply.read()
        except (OSError, ValueError) as e:
            problems.append(f"{name} {models}: {e}")
    return problems


def _require_services(config: dict[str, Any], arm: str) -> None:
    """每个写者会话与每轮读者之前再查一次服务：中途掉线时停下这一组，续跑时从这里接上（不让会话挂到超时）。"""
    if problems := preflight(config, [arm]):
        lines = "\n".join(problems)
        raise SystemExit(f"{arm}: services are not reachable, stopping; resume when they are back:\n{lines}")


def _llm_url(model: str) -> str:
    provider = model.split("/", 1)[0]
    models = json.loads((Path.home() / ".pi/agent/models.json").read_text(encoding="utf-8"))
    return models["providers"][provider]["baseUrl"]


def _system_env(arm: dict[str, Any], data: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("E09_")}
    return env | {"E09_NEO4J_URI": arm["neo4j"], "E09_DATA": str(data)}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m pweval.run", description=__doc__.split("\n\n")[0])
    parser.add_argument("name", help="运行名：运行目录为 <workdir_root>/<name>/")
    parser.add_argument("--config", default=str(REPO / "eval/config/pilot-ltsf.yml"))
    parser.add_argument("--arms", default="A3,A0", help="逗号分隔，按此顺序在每个槽位运行")
    parser.add_argument("--limit", type=int, help="只跑前 N 个槽位（冒烟测试）")
    parser.add_argument("--reset-a3", action="store_true", help="A3 图库非空时清空它（只允许 T1 图库）")
    parser.add_argument("--neo4j", help="A3 用这个图库（另一条时间线并行时），记入 run.yml")
    parser.add_argument("--composition", help="写者构成（配置中 compositions 的键，如 single、multi），记入 run.yml")
    parser.add_argument("--endpoints", help="各组的模型服务，如 A3=http://…/v1,A0=http://…/v1，记入 run.yml")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "Slot",
    "check_checkpoint0",
    "checkpoint",
    "copy_papers",
    "main",
    "papers_dir",
    "prompt",
    "run_config",
    "schedule",
    "setup_a0",
    "setup_a3",
]
