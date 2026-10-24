"""写者组的离线读者（f3 设计 §6）：在检查点备份恢复的读者库上逐题作答，原文只经评测侧的 read_evidence。

    <冻结副本>/.venv/bin/python -m pweval.harness.store_readers <运行名> --config ~/pw-lab/runs/f3/f3-readers.yml \\
        --arm A3 --checkpoint 10 [--group main|aux|all] [--probes <题号>,…] [--out <目录>] [--check-only] [--unfrozen]

输入（备份、快照、放行名单）总在运行目录；输出（恢复的材料、会话、回答与调用记录）默认也在运行目录，``--out`` 另给
一个目录时写到那里（冒烟与试跑，不碰正式的回答文件）。

读者配置（``f3-readers.yml``）指向写者配置，只写读者不同的项：读者的大模型服务、读者库，以及读者的安全上限与并发。
题库、模型与其余设置都取写者配置，与写者相同。

一个检查点的步骤：

1. **恢复。** 检查点备份（``backups/<组>/k<篇数>/``）的文件逐个核对哈希。读者库容器（不能是写者的容器）停下，用
   ``neo4j-admin database load`` 载入备份的 dump（覆盖），再启动；材料根目录与开放来源解到
   ``<输出>/<组>/readers/k<篇数>/{data,sources}``。读者库已经载入这份备份时（容器数据目录旁的 ``restored.yml``）不重载。
2. **核对。** 分支头是备份的版本；从读者库导出的节点、边、提交与产物文档与检查点快照逐字节相同；带检索文字的节点
   与边都有向量；索引全部在线；来源哈希与备份相同；放行名单的检查点与版本与备份相同。读者用的两个服务实际列出的
   工具与 :data:`TOOLS` 相同（A3、A2：只读工具，没有 commit 与系统自己的 read_evidence；证据服务：read_evidence）。
3. **作答。** 每题一次 pi 会话，模型与设置同写者；断网，库只读；单题 ``probe_timeout_min`` 分钟或 ``max_tool_calls``
   次工具调用的上限；``reader_workers`` 路并发。已存的题跳过；回答存 ``<输出>/answers/<组>/k<篇数>[-aux].jsonl``。
4. **答完再核对一次**（第 2 步的库与文档部分）：读者没有改动读者库。

开始之前（:func:`guard`）：这一组必须在读者配置中写明自己的读者库，容器与数据目录不能是写者的，地址必须是这个
容器的端口；之后整个检查点在读者库的进程锁中完成（:func:`store_lock`），另一个进程不能中途重载这个库。续跑时已存的
回答必须是同一个版本与同一份放行名单下答的（:func:`check_answers`）。

**A0**（10-24 用户定）：没有备份与容器。每个检查点在输出目录中新建一份读者仓库（:func:`build_a0`）：空仓库中只取
检查点标签及其祖先，不带标签与远端；全部会话共用，只读挂载为 ``/work``。核对（:func:`verify_a0`，作答前后各一次）：
只有 ``main`` 一个引用，对象库恰好是检查点可达的对象，之后的提交取不到，提交列表、Git 树与工作树同快照；原文目录
只有检查点上开放的来源（与放行名单同一推导）。读者配置中 A0 不能写任何库的设置。证据服务之外没有 MCP 服务。

A3、A2、A0 已实现；A4 的放行名单与读者库待做（f3 设计 §6.3），没有在读者配置中声明的组一律拒绝。
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
from collections import Counter
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

from ..protocol import allowlist
from . import export
from .mcp_client import Client
from .refs import reader_prompt
from .sandbox import (
    GRAPH,
    Arm,
    Paths,
    ReadEvidence,
    Writer,
    _evidence_command,
    _mcp_command,
    prepare,
    run_session,
)
from .timeline import (
    BACKUP_DB,
    GROUPS,
    _docker,
    _locked,
    _record_invocation,
    _sha256,
    _wait_store,
    answered,
    answers_file,
    append_jsonl,
    arm_dir,
    backup_files,
    code_fingerprint,
    container_of,
    eligible,
    emit,
    final_text,
    frozen_problems,
    load_config,
    network_calls,
    read_jsonl,
    source_digest,
    stop_reason,
    timeline_of,
    tool_counts,
    usage,
    version,
)

# 读者实际看到的工具（f3 设计 §6.1）：A3、A2 的 PaperWeave 服务只列只读工具，隐藏系统自己的 read_evidence
TOOLS = {
    "PaperWeave": {"search", "get", "traverse", "checkout", "log", "show", "diff", "as_of"},
    "Evidence": {"read_evidence"},
}
HIDDEN = ("read_evidence",)  # A3、A2：PAPERWEAVE_HIDE_TOOLS；commit 由 PAPERWEAVE_READ_ONLY 去掉
A0_TOOLS = {"Evidence": {"read_evidence"}}  # A0：没有库的服务，仓库就是 /work（pi 自带的工具），原文只经证据服务
ARMS = (*GRAPH, "A0")
# A0 读者仓库建好后删掉的 git 记录：FETCH_HEAD 与引用日志写着共享仓库的宿主机路径与标签名
A0_LEFTOVERS = ("FETCH_HEAD", "ORIG_HEAD", "logs")
# 读者仓库中不能有的：引用日志、取库记录、浅克隆与借用对象库（alternates 会让共享仓库的对象可达）
A0_FORBIDDEN = (*A0_LEFTOVERS, "shallow", "objects/info/alternates", "objects/info/http-alternates")
SNAPSHOT_FILES = ("graph.jsonl", "commits.jsonl")


def load(path: Path) -> dict[str, Any]:
    """读者配置合并到它指向的写者配置上：``runner`` 逐项覆盖，``llm`` 覆盖大模型服务。``arms`` 只留读者配置中声明
    的组，每组必须写明自己的读者库（``neo4j`` 与 ``neo4j_container``），其余项（如 A2 的 ``ablate``）取写者配置；
    没有声明的组不能运行，不会回退到写者的库。写者各组的库记在 ``writer_stores``，供 :func:`guard` 排除。"""
    readers = yaml.safe_load(path.read_text(encoding="utf-8"))
    writers = (path.parent / Path(readers["writers"]).expanduser()).resolve()
    config = load_config(writers)
    config["writers_config"] = str(writers)
    config["writers_sha256"] = _sha256(writers)
    config["writer_stores"] = {a: {k: s[k] for k in ("neo4j", "neo4j_container") if k in s}
                               for a, s in config["arms"].items()}  # fmt: skip
    taken = {v for s in config["writer_stores"].values() for v in s.values()}
    arms = {}
    for arm, spec in (readers.get("arms") or {}).items():
        if arm == "A0":  # 读者仓库由运行器从检查点新建（:func:`build_a0`），配置中不能指向任何库
            if spec:
                raise SystemExit(f"{path}: the readers of A0 read a repository built from the checkpoint; "
                                 f"give no store settings ({', '.join(spec)})")  # fmt: skip
            arms[arm] = config["arms"][arm] | {"llm": readers["llm"]}
            continue
        if missing := [k for k in ("neo4j", "neo4j_container") if not spec.get(k)]:
            raise SystemExit(f"{path}: the readers of {arm} need their own store ({', '.join(missing)} missing)")
        if used := sorted({spec["neo4j"], spec["neo4j_container"]} & taken):
            raise SystemExit(f"{path}: the readers of {arm} must not use a writers' store ({', '.join(used)})")
        arms[arm] = config["arms"][arm] | spec | {"llm": readers["llm"]}
    config["arms"] = arms
    config["runner"] = config["runner"] | (readers.get("runner") or {})
    config["llm"] = readers["llm"]
    return config


def guard(config: dict[str, Any], arm: str) -> Path | None:
    """在停下或载入任何库之前：这一组在读者配置中声明了读者库；容器不是写者的，``/data`` 挂载目录与任何写者容器
    的任何挂载目录都不重叠；库的地址是本机上这个容器映射出的 bolt 端口（恢复的库就是读者连的库）。返回容器的数据
    目录。写者容器只有 Docker 明确答复不存在时才跳过；其他查询失败一律停下。以 ``--rm`` 起的写者容器照样核对挂载，
    它同样可能挂着这个目录。A0 没有容器，读者仓库在输出目录中新建，返回 ``None``。"""
    if arm not in config["arms"]:
        raise RuntimeError(f"{arm} has no readers' store in the reader config; it cannot run")
    if arm == "A0":
        return None
    spec = config["arms"][arm]
    container = spec["neo4j_container"]
    info = _inspect(container)
    if info is None:
        raise RuntimeError(f"the readers' container {container} does not exist")
    if info["HostConfig"].get("AutoRemove"):
        raise RuntimeError(f"container {container} was started with --rm: stopping it to restore would delete it")
    data = [m["Source"] for m in info["Mounts"] if m["Destination"] == "/data"]
    if not data:
        raise RuntimeError(f"container {container} has no /data mount on the host")
    data_dir = Path(data[0]).resolve()
    for name in sorted({s["neo4j_container"] for s in config["writer_stores"].values() if "neo4j_container" in s}):
        if name == container:
            raise RuntimeError(f"{container} is a writers' container")
        theirs = _inspect(name)
        if theirs is None:  # Docker 答复没有这个容器：没有挂载可以重叠
            continue
        for mount in theirs.get("Mounts") or []:
            other = Path(mount["Source"]).resolve()
            if data_dir == other or data_dir.is_relative_to(other) or other.is_relative_to(data_dir):
                raise RuntimeError(f"{container} mounts {data_dir}, which overlaps {other} of the writers' {name}")
    url = urlsplit(spec["neo4j"])
    ports = {b.get("HostPort") for b in (info["HostConfig"].get("PortBindings") or {}).get("7687/tcp") or []}
    if url.hostname not in ("localhost", "127.0.0.1", "::1") or str(url.port) not in ports:
        raise RuntimeError(f"{spec['neo4j']} is not the bolt port of {container} (mapped to {sorted(ports)})")
    return data_dir


def _inspect(name: str) -> dict[str, Any] | None:
    """``docker inspect`` 的结果；只有 Docker 明确答复没有这个对象时返回 ``None``，其他失败报错。"""
    done = subprocess.run(["docker", "inspect", "--type", "container", name], capture_output=True, text=True)
    if done.returncode == 0:
        return json.loads(done.stdout)[0]
    if re.search(rf"No such (object|container): {re.escape(name)}\s*$", done.stderr, re.MULTILINE):
        return None
    raise RuntimeError(f"docker inspect {name} failed: {done.stderr[-1000:]}")


@contextmanager
def store_lock(data_dir: Path) -> Iterator[None]:
    """一个读者库同时只由一个进程使用（恢复、核对、作答到结束核对）：数据目录旁的非阻塞 flock。按库加锁而不是按
    输出目录：不同的 ``--out`` 仍共用这个库。"""
    with open(data_dir.with_name(data_dir.name + ".readers.lock"), "a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError(f"another process is using the readers' store {data_dir}") from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def reader_dir(run: Path, arm: str, papers: int) -> Path:
    return arm_dir(run, arm) / "readers" / f"k{papers}"


def allowlist_of(run: Path, arm: str, papers: int) -> Path:
    return run / "allowlists" / arm / f"k{papers}.json"


# ---------------------------------------------------------------- 恢复与核对


def restore(config: dict[str, Any], run: Path, out: Path, arm: str, papers: int) -> dict[str, Any]:
    """把检查点备份恢复到读者库与 ``<输出>/<组>/readers/k<篇数>/``；返回备份的 meta。"""
    backup = run / "backups" / arm / f"k{papers}"
    meta = yaml.safe_load((backup / "meta.yml").read_text(encoding="utf-8"))
    if (meta["arm"], meta["papers"]) != (arm, papers):
        raise RuntimeError(f"{backup}: the backup is of {meta['arm']} k{meta['papers']}")
    for name in backup_files(arm):
        if _sha256(backup / name) != meta["sha256"][name]:
            raise RuntimeError(f"{backup / name}: the hash differs from meta.yml")
    data_dir = guard(config, arm)
    container = config["arms"][arm]["neo4j_container"]
    _, image_id, _ = container_of(container)
    if image_id != meta["image_id"]:
        raise RuntimeError(f"{container} runs image {image_id}, the backup was dumped by {meta['image_id']}")
    marker = data_dir.parent / "restored.yml"
    want = {"run": str(run), "arm": arm, "papers": papers, "version": meta["version"],
            "dump_sha256": meta["sha256"]["neo4j.dump"]}  # fmt: skip
    loaded = yaml.safe_load(marker.read_text(encoding="utf-8")) if marker.exists() else None
    if loaded != want or _head(config, run, arm) != meta["version"]:
        emit("RESTORE", arm, k=papers, container=container, version=meta["version"])
        marker.unlink(missing_ok=True)
        _docker("stop", container)
        _docker("run", "--rm", "-v", f"{data_dir}:/data", "-v", f"{backup}:/backups", image_id,
                "neo4j-admin", "database", "load", BACKUP_DB, "--from-path=/backups", "--overwrite-destination=true")  # fmt: skip
        _docker("start", container)
        _wait_store(config, run, arm)
        marker.write_text(yaml.safe_dump(want, sort_keys=False), encoding="utf-8")
    where = reader_dir(out, arm, papers)
    for name, part in (("data.tar.gz", "data"), ("sources.tar.gz", "sources")):
        if not (where / part).exists():
            partial = where / f"{part}.partial"
            shutil.rmtree(partial, ignore_errors=True)
            partial.mkdir(parents=True)
            with tarfile.open(backup / name) as tar:
                tar.extractall(partial, filter="data")
            (partial / part).rename(where / part)
            partial.rmdir()
    return meta


def _head(config: dict[str, Any], run: Path, arm: str) -> str | None:
    try:
        return version(config, run, arm)
    except Exception:  # 容器停着或库未就绪：按未恢复处理
        return None


def verify(config: dict[str, Any], run: Path, out: Path, arm: str, papers: int, meta: dict[str, Any]) -> dict[str, Any]:
    """读者库与材料仍是检查点的：版本、与快照逐字节相同的导出、向量、索引、来源哈希。返回核对的计数。"""
    uri, where = config["arms"][arm]["neo4j"], reader_dir(out, arm, papers)
    if (head := export.head(uri)) != meta["version"]:
        raise RuntimeError(f"{arm} readers' store is at {head}, not at checkpoint {papers} ({meta['version']})")
    snap = run / "snapshots" / arm / f"k{papers}"
    out = where / "verify"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir()
    try:
        got = export.export_a3(uri, where / "data", out, arm=arm)
        expected = yaml.safe_load((snap / "meta.yml").read_text(encoding="utf-8"))
        if (got["counts"], got["branches"]) != (expected["counts"], expected["branches"]):
            raise RuntimeError(f"{arm} k{papers}: readers' store {got['counts']} differs from the snapshot {expected['counts']}")
        for name in SNAPSHOT_FILES:
            if _sha256(out / name) != _sha256(snap / name):
                raise RuntimeError(f"{arm} k{papers}: {name} of the readers' store differs from the snapshot")
        if _tree(out / "documents") != _tree(snap / "documents"):
            raise RuntimeError(f"{arm} k{papers}: artifact documents of the readers' store differ from the snapshot")
    finally:
        shutil.rmtree(out, ignore_errors=True)
    with export.driver(uri) as d:
        rows = {kind: d.execute_query(query).records[0] for kind, query in (
            ("nodes", "MATCH (n) WHERE n.search_text IS NOT NULL "
                      "RETURN count(n) AS all, count(n.embedding) AS vec, count(n.embedding_key) AS key"),
            ("edges", "MATCH ()-[e]->() WHERE e.search_text IS NOT NULL "
                      "RETURN count(e) AS all, count(e.embedding) AS vec, count(e.embedding_key) AS key"),
        )}  # fmt: skip
        offline = [r["name"] for r in d.execute_query("SHOW INDEXES YIELD name, state").records if r["state"] != "ONLINE"]
    vectors = {kind: dict(r) for kind, r in rows.items()}
    if any(len(set(v.values())) != 1 for v in vectors.values()):
        raise RuntimeError(f"{arm} k{papers}: records without vectors: {vectors}")
    if offline:
        raise RuntimeError(f"{arm} k{papers}: indexes not online: {offline}")
    found = sorted(p.name for p in (where / "sources").iterdir() if p.is_dir())
    digests = {s: source_digest(where / "sources", s) for s in found}
    if digests != meta["sources"]:
        raise RuntimeError(f"{arm} k{papers}: restored sources differ from the backup")
    return {"version": head, "counts": got["counts"], "vectors": vectors, "sources": len(digests)}


def _tree(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): _sha256(p) for p in sorted(root.rglob("*")) if p.is_file()} if root.exists() else {}


def check_allowlist(run: Path, arm: str, papers: int, meta: dict[str, Any]) -> str:
    """放行名单是这个检查点的：旁边的 ``.sha256`` 与内容相符，名单中的组、检查点与版本与备份相同。返回哈希。"""
    path = allowlist_of(run, arm, papers)
    digest = _sha256(path)
    if path.with_suffix(".json.sha256").read_text(encoding="utf-8").split()[0] != digest:
        raise RuntimeError(f"{path}: the content differs from its .sha256")
    data = json.loads(path.read_text(encoding="utf-8"))
    if (data["arm"], data["checkpoint"], data["version"]) != (arm, papers, meta["version"]):
        raise RuntimeError(f"{path}: allowlist of {data['arm']} k{data['checkpoint']} at {data['version']}, "
                           f"the backup is at {meta['version']}")  # fmt: skip
    if data["inputs"]["sources"] != meta["sources"]:
        raise RuntimeError(f"{path}: the allowlist was collected over other opened sources than the readers get")
    return digest


def check_tools(config: dict[str, Any], run: Path, out: Path, arm: str, papers: int,
                reader: Writer) -> dict[str, list[str]]:  # fmt: skip
    """读者会话登记的 MCP 服务（``prepare`` 写下的 ``mcp.json``）正是预期的那几个，再以会话的同一命令与环境启动
    它们，取实际列出的工具；与 :data:`TOOLS`（A3、A2）或 :data:`A0_TOOLS`（A0：只有证据服务，没有来源服务与库的
    服务）不同即停。"""
    expected = A0_TOOLS if arm == "A0" else TOOLS
    paths = Paths(reader_dir(out, arm, papers) / "tools-check")
    shutil.rmtree(paths.root, ignore_errors=True)
    paths.work.mkdir(parents=True)
    box = reader_arm(config, run, out, arm, papers, "tools-check")
    found = {}
    try:
        _prepare(config, paths, box)
        registered = json.loads((paths.home / ".pi/agent/mcp.json").read_text(encoding="utf-8"))["mcpServers"]
        if set(registered) != set(expected):
            raise RuntimeError(f"{arm} readers' sessions register {sorted(registered)}, expected {sorted(expected)}")
        commands = {"Evidence": _evidence_command(paths, box)}
        if "PaperWeave" in expected:
            commands["PaperWeave"] = _mcp_command(paths, box, reader)
        for name, command in sorted(commands.items(), reverse=True):
            with Client(command, dict(os.environ)) as client:  # 会话中的服务同样继承运行器的环境（命令中另给）
                found[name] = sorted(client.tools())
    finally:
        shutil.rmtree(paths.root, ignore_errors=True)
    if {k: set(v) for k, v in found.items()} != expected:
        raise RuntimeError(f"{arm} readers' tools are {found}, expected {expected}")
    return found


# ---------------------------------------------------------------- A0：检查点仓库


def a0_store(out: Path, papers: int) -> Path:
    return reader_dir(out, "A0", papers) / "store"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


def a0_checkpoint(config: dict[str, Any], run: Path, papers: int) -> dict[str, Any]:
    """A0 的检查点：版本（``checkpoints.yml``）、快照的标签，以及开放的来源。来源与放行名单同一推导
    （:func:`pweval.protocol.allowlist.a0_frozen`、``a0_opened``：写者运行时的计划与材料表，与会话记录交叉核对）。"""
    checkpoints = yaml.safe_load((run / "checkpoints.yml").read_text(encoding="utf-8"))["A0"]
    snapshot = yaml.safe_load((run / "snapshots/A0" / f"k{papers}" / "meta.yml").read_text(encoding="utf-8"))
    frozen = allowlist.a0_frozen(run, config["probes_repo"])
    opened, _ = allowlist.a0_opened(run, papers, frozen, checkpoints[0], checkpoints[papers])
    return {"arm": "A0", "papers": papers, "version": checkpoints[papers], "tag": snapshot["tag"], "sources": opened}


def build_a0(run: Path, out: Path, papers: int, meta: dict[str, Any]) -> None:
    """读者仓库 ``<输出>/A0/readers/k<篇数>/store``：空仓库中只取检查点标签（及其祖先）为 ``main``，不带标签、不留
    远端，检出工作树，再删掉记着共享仓库路径的取库记录；原文目录 ``sources/`` 只复制检查点上开放的来源。已建好的
    不重建，由 :func:`verify_a0` 核对。先在 ``.partial`` 中建好再改名。"""
    store, where = a0_store(out, papers), reader_dir(out, "A0", papers)
    if not store.exists():
        emit("BUILD", "A0", k=papers, tag=meta["tag"], version=meta["version"])
        partial = store.with_name("store.partial")
        shutil.rmtree(partial, ignore_errors=True)
        partial.mkdir(parents=True)
        _git(partial, "init", "-q", "-b", "main")
        _git(partial, "fetch", "-q", "--no-tags", "--update-head-ok", str(run / allowlist.A0_REPO),
             f"+refs/tags/{meta['tag']}:refs/heads/main")  # fmt: skip
        _git(partial, "reset", "-q", "--hard", "refs/heads/main")
        for name in A0_LEFTOVERS:
            leftover = partial / ".git" / name
            shutil.rmtree(leftover) if leftover.is_dir() else leftover.unlink(missing_ok=True)
        partial.rename(store)
    sources = where / "sources"
    if not sources.exists():
        partial = where / "sources.partial"
        shutil.rmtree(partial, ignore_errors=True)
        partial.mkdir(parents=True)
        for source in meta["sources"]:
            shutil.copytree(run / "A0/sources" / source, partial / source)
        partial.rename(sources)


def verify_a0(run: Path, out: Path, papers: int, meta: dict[str, Any]) -> dict[str, Any]:
    """读者仓库与原文目录仍是检查点的，作答前后各一次：

    - 引用只有 ``refs/heads/main``，指向检查点；HEAD 是它；没有远端，没有 :data:`A0_FORBIDDEN` 中的记录；
    - 对象库中的对象恰好是检查点提交可达的那些；共享仓库中检查点之后的每个提交都不在其中（``git show`` 取不到）；
    - 提交列表（逐字段）与 Git 树同检查点快照（:func:`pweval.protocol.allowlist.a0_history`、``a0_tree``），检出的
      工作树与快照的文件树逐个相同；
    - 原文目录恰好是开放的来源，哈希相同。"""
    store, where = a0_store(out, papers), reader_dir(out, "A0", papers)
    snapshot = run / "snapshots/A0" / f"k{papers}"
    head = meta["version"]
    refs = _git(store, "for-each-ref", "--format=%(refname) %(objectname)").splitlines()
    if refs != [f"refs/heads/main {head}"] or _git(store, "symbolic-ref", "HEAD").strip() != "refs/heads/main":
        raise RuntimeError(f"A0 k{papers}: the readers' repository has refs {refs}, expected only main at {head}")
    if remotes := _git(store, "remote").split():
        raise RuntimeError(f"A0 k{papers}: the readers' repository has remotes {remotes}")
    if found := [n for n in A0_FORBIDDEN if (store / ".git" / n).exists()]:
        raise RuntimeError(f"A0 k{papers}: the readers' repository keeps {found}")
    objects = set(_git(store, "cat-file", "--batch-all-objects", "--batch-check=%(objectname)").split())
    reachable = {line.split()[0] for line in _git(store, "rev-list", "--objects", head).splitlines()}
    if objects != reachable:
        raise RuntimeError(f"A0 k{papers}: {len(objects - reachable)} objects beyond checkpoint {head}, "
                           f"{len(reachable - objects)} missing")  # fmt: skip
    later = _git(run / allowlist.A0_REPO, "rev-list", "--all", "--not", head).split()
    if present := [c for c in later if c in objects]:
        raise RuntimeError(f"A0 k{papers}: later commits are in the readers' repository: {present[:3]}")
    try:
        commits, _, history = allowlist.a0_history(store, snapshot, head, ref="refs/heads/main")
        tree = allowlist.a0_tree(store, history["head"], snapshot)
    except allowlist.InputError as e:
        raise RuntimeError(f"A0 k{papers}: the readers' repository differs from the snapshot: {e}") from e
    worktree = {str(p.relative_to(store)): _sha256(p) for p in sorted(store.rglob("*"))
                if p.is_file() and p.relative_to(store).parts[0] != ".git"}  # fmt: skip
    if worktree != _tree(snapshot / "tree"):
        raise RuntimeError(f"A0 k{papers}: the files of the readers' repository differ from the snapshot")
    found = sorted(p.name for p in (where / "sources").iterdir())
    digests = {s: source_digest(where / "sources", s) for s in found}
    if digests != meta["sources"]:
        raise RuntimeError(f"A0 k{papers}: the readers' sources differ from those opened at the checkpoint")
    return {"version": head, "commits": len(commits), "files": tree["files"], "objects": len(objects),
            "later_absent": len(later), "sources": len(digests)}  # fmt: skip


# ---------------------------------------------------------------- 作答


def reader_arm(config: dict[str, Any], run: Path, out: Path, arm: str, papers: int, session: str) -> Arm:
    """读者的沙箱：断网，没有论文与代码目录，库只读；原文只经证据服务。A0 的 ``/work`` 是检查点的读者仓库（只读
    挂载），没有来源服务。"""
    if arm not in ARMS:
        raise NotImplementedError(f"the offline readers of {arm} are not implemented yet (f3 design §6.3)")
    if arm not in config["arms"]:
        raise RuntimeError(f"{arm} has no readers' store in the reader config; it cannot run")
    spec, where = config["arms"][arm], reader_dir(out, arm, papers)
    evidence = ReadEvidence(allowlist_of(run, arm, papers), where / "sources", session)
    if arm == "A0":
        return Arm("A0", None, store=a0_store(out, papers), read_only=True, isolated_llm=config["llm"], evidence=evidence)
    return Arm(arm, None, neo4j=spec["neo4j"], data=where / "data", read_only=True, hide_tools=HIDDEN,
               ablate=tuple(spec.get("ablate") or ()), isolated_llm=config["llm"], sources=where / "sources",
               evidence=evidence)  # fmt: skip


def _prepare(config: dict[str, Any], paths: Paths, box: Arm) -> None:
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


def answer(config: dict[str, Any], tools: str, run: Path, out: Path, arm: str, papers: int, group: str,
           probe: dict[str, Any], reader: Writer) -> dict[str, Any]:  # fmt: skip
    """一题一次读者会话：回答原文、事件流与会话记录、用时、token、工具调用、联网命令与证据请求的统计。"""
    paths = Paths(reader_dir(out, arm, papers) / "sessions" / probe["id"])
    if paths.root.exists():  # 中断后重跑：上次没存下回答的会话目录不留
        shutil.rmtree(paths.root)
    box = reader_arm(config, run, out, arm, papers, probe["id"])
    runner = config["runner"]
    _prepare(config, paths, box)
    text = reader_prompt(arm, probe, tools=tools)
    started = datetime.now(UTC).isoformat(timespec="seconds")
    result = run_session(paths, box, reader, text, timeout_s=runner["probe_timeout_min"] * 60,
                         max_tool_calls=runner["max_tool_calls"])  # fmt: skip
    events = paths.root / result["events"]
    return {
        "arm": arm,
        "checkpoint": papers,
        "group": group,
        "probe": probe["id"],
        "template": probe["template"],
        "started": started,
        **result,
        "events": str(events.relative_to(out)),
        "session": [str((paths.root / s).relative_to(out)) for s in result["session"]],
        "llm": config["llm"],
        "prompt": text,
        "answer": final_text(events),
        "stop": stop_reason(events),
        "usage": usage(events),
        "tools": tool_counts(events),
        "network": network_calls(events),
        "evidence": evidence_summary(paths.root / "evidence.jsonl"),
    }


def evidence_summary(log: Path) -> dict[str, Any]:
    """证据服务的请求记录：调用次数、引用条数、各状态的条数、返回字节数，以及截断的行（§6.2 的交付限制）。"""
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
    items = [it for c in calls for it in c.get("items", [])]
    return {
        "calls": len(calls),
        "errors": sum(c["error"] for c in calls),
        "refs": sum(len(c["refs"]) if isinstance(c["refs"], list) else 1 for c in calls),
        "status": dict(Counter(it["status"] for it in items)),
        "bytes": sum(c["bytes"] for c in calls),
        "cut": [{"ref": it["ref"], **cut} for it in items for cut in it.get("cut", [])],
    }


def check_answers(out: Path, arm: str, papers: int, version: str, digest: str) -> None:
    """续跑前：已存的回答都是同一个检查点版本、同一份放行名单下答的；不一致即停，不把两种证据条件混进一个文件。"""
    for group in GROUPS:
        path = answers_file(out, arm, papers, group)
        wrong = [r["probe"] for r in read_jsonl(path)
                 if (r.get("arm"), r.get("checkpoint"), r.get("version"), r.get("allowlist_sha256"))
                 != (arm, papers, version, digest)]  # fmt: skip
        if wrong:
            raise RuntimeError(f"{path}: {len(wrong)} answers (such as {wrong[0]}) were given at another version or "
                               f"allowlist than {version} / {digest[:12]}; answer into another --out")  # fmt: skip


def run_readers(config: dict[str, Any], run: Path, out: Path, arm: str, papers: int, groups: Sequence[str],
                only: set[str] | None = None, check_only: bool = False) -> None:  # fmt: skip
    """一个检查点：在读者库的锁中完成恢复、核对、作答与结束核对。A0 的锁在本输出目录的读者仓库旁。"""
    lock = guard(config, arm)
    if lock is None:
        lock = a0_store(out, papers)
        lock.parent.mkdir(parents=True, exist_ok=True)
    with store_lock(lock):
        _run_readers(config, run, out, arm, papers, groups, only, check_only)


def _run_readers(config: dict[str, Any], run: Path, out: Path, arm: str, papers: int, groups: Sequence[str],
                 only: set[str] | None, check_only: bool) -> None:  # fmt: skip
    timeline = timeline_of(config)
    reader = Writer("reader", timeline.reader["user"], f"{config['runner']['agent']}/{config['runner']['model']}")
    if arm == "A0":
        meta = a0_checkpoint(config, run, papers)
        build_a0(run, out, papers, meta)
        checked = verify_a0(run, out, papers, meta)
        counts = {k: checked[k] for k in ("commits", "files", "objects", "later_absent")}
    else:
        meta = restore(config, run, out, arm, papers)
        checked = verify(config, run, out, arm, papers, meta)
        counts = {k: checked["counts"][k] for k in ("nodes", "edges", "documents")}
    digest = check_allowlist(run, arm, papers, meta)
    check_answers(out, arm, papers, meta["version"], digest)
    tools = check_tools(config, run, out, arm, papers, reader)
    emit("READY", arm, k=papers, version=checked["version"], **counts, sources=checked["sources"],
         allowlist=digest[:12], tools=",".join(t for v in tools.values() for t in v))  # fmt: skip
    if check_only:
        return
    sentence = timeline.hints[arm.lower()]["TOOLS"]
    for group in groups:
        probes = [p for p in timeline.group(group) if p["id"] in only] if only else eligible(timeline, papers, group)
        done = answered(out, arm, papers, group)
        todo = [p for p in probes if p["id"] not in done]
        path = answers_file(out, arm, papers, group)
        path.parent.mkdir(parents=True, exist_ok=True)

        def ask(probe: dict[str, Any], group: str = group, path: Path = path) -> None:
            record = answer(config, sentence, run, out, arm, papers, group, probe, reader)
            record |= {"version": meta["version"], "allowlist_sha256": digest}
            append_jsonl(path, record)
            emit("READER", arm, k=papers, group=group, probe=probe["id"], exit=record["exit"],
                 seconds=record["seconds"], tools=sum(record["tools"].values()), chars=len(record["answer"]))  # fmt: skip

        with ThreadPoolExecutor(max_workers=config["runner"]["reader_workers"]) as pool:
            list(pool.map(ask, todo))
        emit("GROUP", arm, k=papers, group=group, answered=f"{len(answered(out, arm, papers, group))}/{len(probes)}")
    if arm == "A0":
        verify_a0(run, out, papers, meta)
    else:
        verify(config, run, out, arm, papers, meta)
    emit("DONE", arm, k=papers)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("name", help="运行名")
    parser.add_argument("--config", required=True, help="读者配置（指向写者配置）")
    parser.add_argument("--arm", required=True, choices=sorted(ARMS))
    parser.add_argument("--checkpoint", type=int, required=True, help="检查点的篇数")
    parser.add_argument("--group", default="all", choices=[*GROUPS, "all"])
    parser.add_argument("--probes", help="只答这些题（逗号分隔，试跑；不按有效性筛选）")
    parser.add_argument("--out", help="输出目录（冒烟、试跑）；默认为运行目录")
    parser.add_argument("--check-only", action="store_true", help="只恢复并核对读者库、放行名单与工具，不作答")
    parser.add_argument("--unfrozen", action="store_true", help="不从冻结副本运行（冒烟、开发）")
    parser.add_argument("--allow-config-change", action="store_true",
                        help="续跑时允许生效的配置或题库提交与第一次调用不同（改动记入记录）")
    parser.add_argument("--allow-code-change", action="store_true",
                        help="续跑时允许执行的代码与第一次调用不同（工程修正；指纹记入记录）")
    args = parser.parse_args(argv)
    if not args.unfrozen and (problems := frozen_problems()):
        raise SystemExit("start the readers from a frozen copy (python -m pweval.harness.freeze <commit>), "
                         "or pass --unfrozen for a smoke run:\n" + "\n".join(problems))  # fmt: skip
    config_path = Path(args.config).expanduser().resolve()
    config = load(config_path)
    guard(config, args.arm)  # 没有声明读者库、或会碰到写者的库：在记下这次调用之前就拒绝
    run = config["workdir_root"] / args.name
    out = Path(args.out).expanduser().resolve() if args.out else run
    groups = GROUPS if args.group == "all" else (args.group,)
    only = set(args.probes.split(",")) if args.probes else None
    record = reader_dir(out, args.arm, args.checkpoint).parent / "run.yml"
    record.parent.mkdir(parents=True, exist_ok=True)
    with _locked(record):
        _record_invocation(record, config_path, config, list(argv) if argv is not None else sys.argv[1:],
                           args.allow_config_change, code_fingerprint(), args.allow_code_change,
                           not args.unfrozen)  # fmt: skip
    emit("RUN", args.arm, name=args.name, k=args.checkpoint, groups=",".join(groups))
    run_readers(config, run, out, args.arm, args.checkpoint, groups, only, args.check_only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["A0_TOOLS", "TOOLS", "a0_checkpoint", "a0_store", "answer", "build_a0", "check_answers", "check_tools", "guard", "store_lock", "evidence_summary", "load", "main", "reader_arm", "restore", "run_readers",
           "verify", "verify_a0"]
