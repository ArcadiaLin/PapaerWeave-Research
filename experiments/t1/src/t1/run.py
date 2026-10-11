"""T1 先导的一次运行：按配置建立各组的起点（检查点 0），按顺序调度写者会话，在检查点存档。

    python -m t1.run <运行名> [--config …] [--arms A3,A0] [--limit N] [--reset-a3]

运行目录 ``<workdir_root>/<运行名>/``：

- ``run.yml``：配置副本、仓库提交与是否有未提交改动、开始时间；
- ``sessions.jsonl``：每次会话一行（组、序号、论文、写者、退出码、用时、事件流与会话记录的位置、会话前后的库版本）；
- ``checkpoints.yml``：各组每个检查点的库版本（A3 为 graph-vc 的提交 id，A0 为 git 标签 ``checkpoint-<k>``）；
- ``A3/data/``：A3 的材料根目录（论文副本与产物文档，``E09_DATA``）；``A0/store/``：A0 的笔记库（git 仓库）；
- ``<组>/<写者>/``：写者的沙箱目录（见 :mod:`t1.sandbox`）。

A3 的起点：清空图库（``--reset-a3``，只允许配置中的 T1 图库），按 ``seed_docs`` 的顺序
（作者取文档的 ``by``）提交，再与内存重放的状态逐项比较，不一致即停止。A0 的起点由同一个内存重放渲染（:mod:`t1.a0_seed`）。两组内容因此相同。

会话按“槽位”调度：每个槽位是一篇论文的一个写者。组内按槽位顺序逐个运行（写者轮流写），各组同时运行：
两组的存储互不相干，并行只缩短总时间。中断后用同一个运行名重跑，已记录的会话跳过。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml
from e09.config import REPO

from .a0_seed import commit_seed, render, seed_docs, write
from .replay import replay
from .sandbox import Arm, Paths, Writer, prepare, run_session

PROTECTED = {7687, 7688}  # neo4j-e09 与 neo4j-test：不清空
_LOCK = threading.Lock()  # 各组并行时，sessions.jsonl 与 checkpoints.yml 的写入


@dataclass(frozen=True)
class Slot:
    index: int  # 从 1 开始
    paper: dict[str, Any]
    writer: dict[str, Any]
    checkpoint: int | None  # 这个槽位之后存档的检查点编号


def schedule(config: dict[str, Any]) -> list[Slot]:
    """每篇论文两个写者；``alternate`` 时奇数篇按写者列表顺序，偶数篇反过来。"""
    plan = config["schedule"]
    writers, papers = config["writers"], config["corpus"]["papers"]
    every = plan["checkpoint_every_papers"]
    slots: list[Slot] = []
    for n, paper in enumerate(papers, 1):
        order = writers if plan["order"] != "alternate" or n % 2 else writers[::-1]
        for i, writer in enumerate(order):
            last = i == len(order) - 1 and n % every == 0
            slots.append(Slot(len(slots) + 1, paper, writer, n // every if last else None))
    if len(slots) != plan["sessions_per_arm"]:
        raise ValueError(f"schedule has {len(slots)} sessions, config says {plan['sessions_per_arm']}")
    return slots


def prompt(config: dict[str, Any], arm: str, slot: Slot, titles: dict[str, str]) -> str:
    paper = slot.paper
    task = slot.writer["task"].format(
        title=titles[paper["arxiv"].rsplit("v", 1)[0]],
        arxiv=paper["arxiv"],
        material=f"papers/{paper['arxiv']}/paper.md",
        method=paper["method"],
    )
    closing = config["writer_closing"].format(store=config["arms"][arm]["store"])
    return f"{task.rstrip()}\n\n{closing.rstrip()}\n"


def titles_of(config: dict[str, Any]) -> dict[str, str]:
    data = yaml.safe_load((REPO / config["corpus"]["candidates"]).read_text(encoding="utf-8"))
    return {p["arxiv_id"]: p["title"] for d in data["domains"] for p in d["papers"]}


# ---------------------------------------------------------------- 起点


def setup_a3(run: Path, config: dict[str, Any], *, reset: bool) -> None:
    arm = config["arms"]["A3"]
    material = REPO / config["corpus"]["material_root"]
    data = run / "A3/data"
    if not (data / "papers").exists():
        shutil.copytree(material / "papers", data / "papers")
    driver = _driver(arm["neo4j"])
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
    env = _e09_env(arm, data)
    for doc in config["seed_docs"]:
        args = [str(REPO / doc["doc"]), "--source", doc["source"], "--apply"]  # 作者取文档的 by
        args += ["--message", f"seed: {Path(doc['doc']).name}"] + ([] if doc["dedup"] else ["--no-dedup"])
        if not arm.get("embeddings", True):
            args.append("--no-embed")
        done = subprocess.run([sys.executable, "-m", "e09", *args], env=env, capture_output=True, text=True)
        if done.returncode != 0:
            raise SystemExit(f"seeding {doc['doc']} failed:\n{done.stdout}\n{done.stderr}")
    differences = _compare(config, arm, data)
    if differences:
        raise SystemExit(f"A3 checkpoint 0 differs from the replayed seed state: {differences[:5]}")


def setup_a0(run: Path, config: dict[str, Any]) -> None:
    store = run / "A0/store"
    if store.exists():
        return
    material = REPO / config["corpus"]["material_root"]
    write(render(replay(seed_docs(_config_path(config)), material)), store)
    commit_seed(store)


def _compare(config: dict[str, Any], arm: dict[str, Any], data: Path) -> list[str]:
    from e09.store import open_graph

    material = REPO / config["corpus"]["material_root"]
    expected = replay(seed_docs(_config_path(config)), material)
    driver = _driver(arm["neo4j"])
    try:
        actual = open_graph(driver, file_root=data).snapshot()
    finally:
        driver.close()
    out = []
    if set(actual.nodes) != set(expected.nodes):
        out.append(f"node set: {sorted(set(actual.nodes) ^ set(expected.nodes))[:3]}")
    out += [i for i in sorted(expected.nodes) if i in actual.nodes and actual.nodes[i] != expected.nodes[i]]
    if actual.edges != expected.edges:
        out.append("edges")
    return out


# ---------------------------------------------------------------- 检查点与版本


def version(run: Path, config: dict[str, Any], arm: str) -> str | None:
    if arm == "A0":
        done = subprocess.run(["git", "-C", str(run / "A0/store"), "rev-parse", "HEAD"], capture_output=True, text=True)
        return done.stdout.strip() or None
    from e09.store import open_graph

    driver = _driver(config["arms"]["A3"]["neo4j"])
    try:
        return open_graph(driver, file_root=run / "A3/data").head()
    finally:
        driver.close()


def checkpoint(run: Path, config: dict[str, Any], arm: str, k: int) -> str | None:
    if arm == "A0":
        store = str(run / "A0/store")
        tag = ["git", "-C", store, "-c", "user.name=t1", "-c", "user.email=t1@t1.example", "tag", "-f", f"checkpoint-{k}"]
        subprocess.run(tag, check=True, capture_output=True)
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
    _record_run(run, config_path, arms)

    if "A3" in arms and "A3" not in _checkpoints(run):
        setup_a3(run, config, reset=args.reset_a3)
        checkpoint(run, config, "A3", 0)
    if "A0" in arms and "A0" not in _checkpoints(run):
        setup_a0(run, config)
        checkpoint(run, config, "A0", 0)

    titles = titles_of(config)
    done = _done(run)
    llm = _llm_url(config["runner"]["model"])
    slots = schedule(config)[: args.limit] if args.limit else schedule(config)

    def run_arm(arm: str) -> None:
        for slot in slots:
            if (arm, slot.index) in done:
                continue
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

    with ThreadPoolExecutor(max_workers=len(arms)) as pool:
        for future in [pool.submit(run_arm, arm) for arm in arms]:
            future.result()  # 一组出错时报出，另一组照常跑完
    return 0


def _session(run: Path, config: dict[str, Any], arm: str, slot: Slot, text: str, llm: str) -> dict[str, Any]:
    spec = config["arms"][arm]
    w = slot.writer
    writer = Writer(w["id"], w["user"], w["agent"])
    papers = run / "A3/data/papers" if arm == "A3" else REPO / config["corpus"]["material_root"] / "papers"
    if arm == "A3":
        sandbox_arm = Arm(
            "A3", papers, neo4j=spec["neo4j"], data=run / "A3/data", embeddings=spec.get("embeddings", True)
        )
    else:
        sandbox_arm = Arm("A0", papers, store=run / "A0/store")
    paths = Paths(run / arm / writer.id)
    runner = config["runner"]
    prepare(paths, sandbox_arm, runner["model"], runner["thinking"], runner["context_window"])
    before = version(run, config, arm)
    started = datetime.now(UTC).isoformat(timespec="seconds")
    result = run_session(
        paths, sandbox_arm, writer, text, timeout_s=config["runner"]["session_timeout_min"] * 60, llm=llm
    )
    return {
        "arm": arm,
        "index": slot.index,
        "paper": slot.paper["arxiv"],
        "writer": writer.id,
        "started": started,
        **result,
        "events": f"{arm}/{writer.id}/{result['events']}",
        "session": [f"{arm}/{writer.id}/{s}" for s in result["session"]],
        "before": before,
        "after": version(run, config, arm),
        "prompt": text,
    }


def _record_run(run: Path, config_path: Path, arms: list[str]) -> None:
    path = run / "run.yml"
    if path.exists():
        return
    sha = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(REPO), "status", "--porcelain", "--", "experiments", "packages"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    data = {
        "started": datetime.now(UTC).isoformat(timespec="seconds"),
        "repo_commit": sha,
        "repo_dirty": bool(dirty),
        "arms": arms,
        "config_file": str(config_path.relative_to(REPO)),
    }
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    shutil.copy(config_path, run / "config.yml")


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


def _llm_url(model: str) -> str:
    provider = model.split("/", 1)[0]
    models = json.loads((Path.home() / ".pi/agent/models.json").read_text(encoding="utf-8"))
    return models["providers"][provider]["baseUrl"]


def _e09_env(arm: dict[str, Any], data: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("E09_")}
    return env | {"E09_NEO4J_URI": arm["neo4j"], "E09_DATA": str(data)}


def _driver(uri: str):
    from e09.config import NEO4J_AUTH
    from neo4j import GraphDatabase

    return GraphDatabase.driver(uri, auth=NEO4J_AUTH)


def _config_path(config: dict[str, Any]) -> Path:
    return Path(config["_path"])


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m t1.run", description=__doc__.split("\n\n")[0])
    parser.add_argument("name", help="运行名：运行目录为 <workdir_root>/<name>/")
    parser.add_argument("--config", default=str(REPO / "experiments/t1/config/pilot-ltsf.yml"))
    parser.add_argument("--arms", default="A3,A0", help="逗号分隔，按此顺序在每个槽位运行")
    parser.add_argument("--limit", type=int, help="只跑前 N 个槽位（冒烟测试）")
    parser.add_argument("--reset-a3", action="store_true", help="A3 图库非空时清空它（只允许 T1 图库）")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["Slot", "checkpoint", "main", "prompt", "schedule", "setup_a0", "setup_a3"]
