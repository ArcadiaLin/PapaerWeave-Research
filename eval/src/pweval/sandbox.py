"""写者会话的隔离运行：一次 pi 会话在 bubblewrap 沙箱中执行（默认配置的 pi，非交互）。

沙箱里能看到的只有：系统目录与 node（只读）、本写者的工作目录 ``/work``（可写）、本写者的 ``HOME``（pi 的
agent 目录：只有模型配置与设置，不带宿主机的扩展、skills 与认证）、论文材料 ``/work/papers``（只读）；A0 另有
共享笔记库 ``/work/store``（可写，各写者共用一份）。读者（:mod:`pweval.probe`）的库只读：A0 的笔记库只读挂载，A3 的 MCP
服务只列出不写入的工具；只读库的读者没有论文，A3 的 ReadEvidence 只读产物文档。闭卷与神谕参照线（``name`` 为 ``none``）
既没有库，也没有论文。仓库、``docs/``、金标准、其他组与其他写者的目录都不可见；
环境变量清空后只设必要的几个（宿主机的代理设置不带进去）。

网络断开，只剩回环地址。与外面的联系只有挂载进去的 unix socket（:mod:`pweval.bridge`）：

- ``llm.sock``：沙箱内 ``127.0.0.1:<端口>`` → 沙箱外的大模型服务；
- ``mcp.sock``（A3）：沙箱内登记的 MCP 服务只是一条转发命令，每个连接在沙箱外启动一个 ``python -m paperweave.mcp``，
  登录身份与连接参数在沙箱外写定。写者拿不到图库的端口与口令，进入共享库的唯一途径是 MCP 接口。

``pi`` 从工作目录及其上层加载 ``AGENTS.md``，沙箱中 ``/work`` 的上层为空，仓库的说明文件不会被加载。
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from .paths import REPO

BRIDGE = Path(__file__).with_name("bridge.py")
LLM_PORT = 30000  # 沙箱内大模型服务的回环端口
PI_DIR = "/opt/pi"  # 托管安装的 pi：当前版本的 release 目录只读挂到这里


def pi_install(launcher: str | None = None) -> tuple[Path | None, str]:
    """宿主机上的 pi 怎样带进沙箱：返回要只读挂载的目录（不需要时为 ``None``）与沙箱内的启动命令。

    - npm 全局安装：``pi`` 在 node 的 bin 目录下，随 node 一起挂载，沙箱内直接用 ``pi``；
    - pi 的托管安装（``~/.pi/agent/bin/pi`` 启动脚本，版本在 ``install/current-version``，程序在
      ``install/releases/<版本>/``）：只挂当前版本的 release 目录。不挂 ``~/.pi/agent`` 本身，其中有宿主机的模型
      配置、认证与会话记录；沙箱内的 agent 目录仍是写者自己的 ``HOME``。
    """
    found = launcher or shutil.which("pi")
    if not found:
        raise FileNotFoundError("pi is not on PATH")
    path = Path(found).resolve()
    node_bin = Path(shutil.which("node") or "").resolve().parent
    if path.parent == node_bin or node_bin in path.parents:
        return None, "pi"
    agent = path.parent.parent
    version_file = agent / "install/current-version"
    if path.parent.name != "bin" or not version_file.exists():
        raise FileNotFoundError(f"{path} is neither in node's tree nor a managed pi install")
    release = agent / "install/releases" / version_file.read_text(encoding="utf-8").strip()
    if not (release / "node_modules/.bin/pi").exists():
        raise FileNotFoundError(f"managed pi release is missing: {release}")
    return release, f"{PI_DIR}/node_modules/.bin/pi"


def pi_version() -> str:
    """宿主机上 pi 的版本（运行记录用）。"""
    found = shutil.which("pi")
    done = subprocess.run([found or "pi", "--version"], capture_output=True, text=True, timeout=30)
    return (done.stdout or done.stderr).strip().splitlines()[-1] if done.returncode == 0 else "unknown"


@dataclass(frozen=True)
class Writer:
    id: str
    user: str  # 登录身份：A3 的 PAPERWEAVE_USER（formed_by、提交 author），A0 的 git author
    agent: str  # 所用的 Agent 与模型：A3 的 PAPERWEAVE_AGENT（提交 meta.agent）


@dataclass(frozen=True)
class Arm:
    name: str  # A0、A3，或 none（参照线：没有库）
    papers: Path | None  # 论文材料目录（只读挂载到 /work/papers）；参照线为 None
    store: Path | None = None  # A0：共享笔记库（git 仓库）
    neo4j: str | None = None  # A3：图库
    data: Path | None = None  # A3：材料根目录（PAPERWEAVE_DATA：论文与产物文档）
    embeddings: bool = True
    read_only: bool = False  # 读者：库只读
    hide_tools: tuple[str, ...] = ()  # A3：不列出的 MCP 工具
    evidence_scope: str | None = None  # A3：artifacts 时 ReadEvidence 只读产物文档（只读库的读者不读论文原文）


@dataclass(frozen=True)
class Paths:
    root: Path  # ~/t1-runs/<run>/<arm>/<writer>/
    work: Path = field(init=False)
    home: Path = field(init=False)
    sock: Path = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "work", self.root / "work")
        object.__setattr__(self, "home", self.root / "home")
        object.__setattr__(self, "sock", self.root / "sock")


def prepare(paths: Paths, arm: Arm, model: str, thinking: str, context_window: int, idle_timeout_ms: int) -> None:
    """建立写者的工作目录与 pi 的 agent 目录（只有模型配置与设置；思考级别、上下文窗口与请求的空闲超时取实验配置）。

    已存在时保留会话记录，只重写配置。
    """
    for d in (paths.work / ".pi", paths.home / ".pi/agent", paths.sock):
        d.mkdir(parents=True, exist_ok=True)
    provider, model_id = model.split("/", 1)
    host_agent = Path(os.environ.get("PI_CODING_AGENT_DIR", Path.home() / ".pi/agent")).expanduser()
    models = json.loads((host_agent / "models.json").read_text(encoding="utf-8"))
    entry = models["providers"][provider]
    parts = urlsplit(entry["baseUrl"])
    entry["baseUrl"] = f"http://127.0.0.1:{LLM_PORT}{parts.path}"
    entry["models"] = [m | {"contextWindow": context_window} for m in entry["models"] if m["id"] == model_id]
    if not entry["models"]:
        raise ValueError(f"{model} is not in {host_agent / 'models.json'}")
    models["providers"] = {provider: entry}
    _write_json(paths.home / ".pi/agent/models.json", models)
    _write_json(
        paths.home / ".pi/agent/settings.json",
        {
            "defaultProvider": provider,
            "defaultModel": model_id,
            "modelThinkingLevels": {model: thinking},
            "httpIdleTimeoutMs": idle_timeout_ms,
        },
    )
    _write_json(paths.work / ".pi/settings.json", {"sessionDir": ".pi/sessions"})
    if arm.name == "A3":
        server = {
            "command": "python3",
            "args": ["/opt/t1/bridge.py", "stdio-to-unix", "/run/t1/mcp.sock"],
            "exposure": "direct",
            "timeout": 300,
        }
        _write_json(paths.work / ".pi/mcp.json", {"mcpServers": {"PaperWeave": server}})


def run_session(paths: Paths, arm: Arm, writer: Writer, prompt: str, *, timeout_s: int, llm: str) -> dict:
    """在沙箱中跑一次 pi 会话。返回退出码、用时与这次会话的记录文件；pi 的 JSON 事件流写到 ``<root>/runs/``。"""
    stamp = time.strftime("%Y%m%dT%H%M%S")
    runs = paths.root / "runs"
    runs.mkdir(exist_ok=True)
    before = set((paths.work / ".pi/sessions").rglob("*.jsonl")) if (paths.work / ".pi/sessions").exists() else set()
    # 转发进程与它启动的 MCP 服务的 stderr 写到写者目录（MCP 服务另有自己的日志 paperweave.log）
    stderr = open(paths.root / "bridge.err", "ab")  # noqa: SIM115
    bridges = [_spawn(["unix-to-tcp", str(paths.sock / "llm.sock"), urlsplit(llm).netloc], stderr)]
    if arm.name == "A3":
        mcp = ["unix-exec", str(paths.sock / "mcp.sock"), "--", *_mcp_command(paths, arm, writer)]
        bridges.append(_spawn(mcp, stderr))
    try:
        _wait_for(paths.sock / "llm.sock", *([paths.sock / "mcp.sock"] if arm.name == "A3" else []))
        started = time.monotonic()
        inner = (
            f"python3 /opt/t1/bridge.py tcp-to-unix 127.0.0.1:{LLM_PORT} /run/t1/llm.sock & "
            f'sleep 0.3; exec {pi_install()[1]} -p --offline --approve --mode json "$T1_PROMPT"'
        )
        killed: list[dict] = []
        with open(runs / f"{stamp}.jsonl", "wb") as out, open(runs / f"{stamp}.err", "wb") as err:
            proc = subprocess.Popen(
                [*_bwrap(paths, arm, writer, prompt), "bash", "-c", inner],
                stdin=subprocess.DEVNULL,  # pi -p 在 stdin 不是终端时会读它
                stdout=out,
                stderr=err,
            )
            code: int | str | None = None
            while code is None:
                try:
                    code = proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    if time.monotonic() - started > timeout_s:
                        proc.kill()
                        proc.wait()
                        code = "timeout"
                    else:
                        killed += kill_long_tools(proc.pid, TOOL_LIMIT_S)
        seconds = round(time.monotonic() - started, 1)
    finally:
        for p in bridges:
            p.terminate()
            p.wait(timeout=10)
        stderr.close()
    after = set((paths.work / ".pi/sessions").rglob("*.jsonl"))
    session = sorted(str(p.relative_to(paths.root)) for p in after - before)
    return {"exit": code, "seconds": seconds, "events": f"runs/{stamp}.jsonl", "session": session, "tool_kills": killed}


TOOL_LIMIT_S = 600  # 单个 shell 工具命令的时限：超过即终止，pi 收到出错结果后继续（两组相同）


def kill_long_tools(root: int, limit_s: int) -> list[dict]:
    """终止沙箱中运行超过 ``limit_s`` 秒的 shell 工具命令（pi 为每次 bash 工具调用起的 ``bash -c``）及其子进程。
    pilot-2 中一个写者的脚本陷入死循环，没有这个时限就要等到会话超时、整次会话作废。"""
    rows = subprocess.run(["ps", "-eo", "pid=,ppid=,etimes=,args="], capture_output=True, text=True).stdout
    procs = {}
    for line in rows.splitlines():
        parts = line.split(None, 3)
        if len(parts) == 4:
            procs[int(parts[0])] = (int(parts[1]), int(parts[2]), parts[3])
    children: dict[int, list[int]] = {}
    for pid, (ppid, _, _) in procs.items():
        children.setdefault(ppid, []).append(pid)

    def tree(pid: int) -> list[int]:
        out = [pid]
        for c in children.get(pid, []):
            out += tree(c)
        return out

    killed = []
    for pid in tree(root)[1:]:
        ppid, age, args = procs[pid]
        parent = procs.get(ppid, (0, 0, ""))[2]
        if age > limit_s and re.match(r"(/usr)?(/bin/)?bash -c ", args) and re.search(r"\bpi\b|node", parent):
            for victim in reversed(tree(pid)):
                with contextlib.suppress(ProcessLookupError):
                    os.kill(victim, signal.SIGKILL)
            killed.append({"seconds": age, "command": args[:300]})
    return killed


def _bwrap(paths: Paths, arm: Arm, writer: Writer, prompt: str) -> list[str]:
    node = Path(shutil.which("node") or "").resolve().parent.parent
    args = [
        "bwrap", "--unshare-all", "--die-with-parent", "--clearenv",
        "--ro-bind", "/usr", "/usr",
        "--symlink", "usr/bin", "/bin", "--symlink", "usr/lib", "/lib",
        "--symlink", "usr/lib64", "/lib64", "--symlink", "usr/sbin", "/sbin",
        "--ro-bind", "/etc", "/etc", "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
        "--ro-bind", str(node), str(node),
        "--ro-bind", str(BRIDGE), "/opt/t1/bridge.py",
        *(["--ro-bind", str(pi_dir), PI_DIR] if (pi_dir := pi_install()[0]) else []),
        "--bind", str(paths.sock), "/run/t1",
        "--bind", str(paths.work), "/work",
        "--bind", str(paths.home), "/home/agent",
    ]  # fmt: skip
    if arm.papers is not None:
        args += ["--ro-bind", str(arm.papers), "/work/papers"]
    if arm.name == "A0":
        assert arm.store is not None
        args += ["--ro-bind" if arm.read_only else "--bind", str(arm.store), "/work/store"]
    env = {
        "HOME": "/home/agent",
        "PATH": f"{node}/bin:/usr/bin",
        "LANG": "C.UTF-8",
        "TERM": "dumb",
        "T1_PROMPT": prompt,
        "GIT_AUTHOR_NAME": writer.user,
        "GIT_AUTHOR_EMAIL": writer.user,
        "GIT_COMMITTER_NAME": writer.user,
        "GIT_COMMITTER_EMAIL": writer.user,
    }
    for key, value in env.items():
        args += ["--setenv", key, value]
    return [*args, "--chdir", "/work"]


def mcp_env(paths: Paths, arm: Arm, writer: Writer) -> dict[str, str]:
    """写者的 MCP 服务在沙箱外的环境：库、材料根目录、登录身份、工作目录与开关。"""
    assert arm.neo4j is not None and arm.data is not None
    env = {
        "PAPERWEAVE_NEO4J_URI": arm.neo4j,
        "PAPERWEAVE_DATA": str(arm.data),
        "PAPERWEAVE_USER": writer.user,
        "PAPERWEAVE_AGENT": writer.agent,
        "PAPERWEAVE_ENABLE_COMMIT": "1",
        "PAPERWEAVE_MCP_LOG": str(paths.root / "paperweave.log"),
        "PAPERWEAVE_WORKDIR": str(paths.work),  # 草稿文件（payload_file、doc_file）只从写者的工作目录读
        "PAPERWEAVE_WORKDIR_ALIAS": "/work",  # 写者在沙箱中看到的同一目录
    }
    if not arm.embeddings:
        env["PAPERWEAVE_NO_EMBED"] = "1"
    if arm.read_only:
        env["PAPERWEAVE_READ_ONLY"] = "1"
        del env["PAPERWEAVE_ENABLE_COMMIT"]
    if arm.hide_tools:
        env["PAPERWEAVE_HIDE_TOOLS"] = ",".join(arm.hide_tools)
    if arm.evidence_scope:
        env["PAPERWEAVE_EVIDENCE_SCOPE"] = arm.evidence_scope
    return env


def _mcp_command(paths: Paths, arm: Arm, writer: Writer) -> list[str]:
    env = mcp_env(paths, arm, writer)
    return ["env", *(f"{k}={v}" for k, v in env.items()), str(REPO / ".venv/bin/python"), "-m", "paperweave.mcp"]


def _spawn(args: list[str], stderr) -> subprocess.Popen:
    return subprocess.Popen(["python3", str(BRIDGE), *args], cwd=REPO / "system", stderr=stderr)


def _wait_for(*socks: Path, timeout_s: float = 10) -> None:
    deadline = time.monotonic() + timeout_s
    while not all(s.exists() for s in socks):
        if time.monotonic() > deadline:
            raise RuntimeError(f"bridge sockets not ready: {[str(s) for s in socks if not s.exists()]}")
        time.sleep(0.05)


def _write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


__all__ = ["Arm", "Paths", "Writer", "pi_install", "pi_version", "prepare", "run_session"]
