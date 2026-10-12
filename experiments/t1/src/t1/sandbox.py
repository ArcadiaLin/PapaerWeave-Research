"""写者会话的隔离运行：一次 pi 会话在 bubblewrap 沙箱中执行（默认配置的 pi，非交互）。

沙箱里能看到的只有：系统目录与 node（只读）、本写者的工作目录 ``/work``（可写）、本写者的 ``HOME``（pi 的
agent 目录：只有模型配置与设置，不带宿主机的扩展、skills 与认证）、论文材料 ``/work/papers``（只读）；A0 另有
共享笔记库 ``/work/store``（可写，各写者共用一份）。读者（:mod:`t1.probe`）的库只读：A0 的笔记库只读挂载，A3 的 MCP
服务只列出不写入的工具；只读库的读者没有论文，A3 的 ReadEvidence 只读产物文档。闭卷与神谕参照线（``name`` 为 ``none``）
既没有库，也没有论文。仓库、``docs/``、金标准、其他组与其他写者的目录都不可见；
环境变量清空后只设必要的几个（宿主机的代理设置不带进去）。

网络断开，只剩回环地址。与外面的联系只有挂载进去的 unix socket（:mod:`t1.bridge`）：

- ``llm.sock``：沙箱内 ``127.0.0.1:<端口>`` → 沙箱外的大模型服务；
- ``mcp.sock``（A3）：沙箱内登记的 MCP 服务只是一条转发命令，每个连接在沙箱外启动一个 ``python -m e09.mcp``，
  登录身份与连接参数在沙箱外写定。写者拿不到图库的端口与口令，进入共享库的唯一途径是 MCP 接口。

``pi`` 从工作目录及其上层加载 ``AGENTS.md``，沙箱中 ``/work`` 的上层为空，仓库的说明文件不会被加载。
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import signal
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from e09.config import REPO

BRIDGE = Path(__file__).with_name("bridge.py")
LLM_PORT = 30000  # 沙箱内大模型服务的回环端口


@dataclass(frozen=True)
class Writer:
    id: str
    user: str  # 登录身份：A3 的 E09_USER（formed_by、提交 author），A0 的 git author
    agent: str  # 所用的 Agent 与模型：A3 的 E09_AGENT（提交 meta.agent）


@dataclass(frozen=True)
class Arm:
    name: str  # A0、A3，或 none（参照线：没有库）
    papers: Path | None  # 论文材料目录（只读挂载到 /work/papers）；参照线为 None
    store: Path | None = None  # A0：共享笔记库（git 仓库）
    neo4j: str | None = None  # A3：图库
    data: Path | None = None  # A3：材料根目录（E09_DATA：论文与产物文档）
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
            'sleep 0.3; exec pi -p --offline --approve --mode json "$T1_PROMPT"'
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


def _mcp_command(paths: Paths, arm: Arm, writer: Writer) -> list[str]:
    assert arm.neo4j is not None and arm.data is not None
    env = {
        "E09_NEO4J_URI": arm.neo4j,
        "E09_DATA": str(arm.data),
        "E09_USER": writer.user,
        "E09_AGENT": writer.agent,
        "E09_ENABLE_COMMIT": "1",
        "E09_MCP_LOG": str(paths.root / "paperweave.log"),
        "E09_WORKDIR": str(paths.work),  # 草稿文件（payload_file、doc_file）只从写者的工作目录读
        "E09_WORKDIR_ALIAS": "/work",  # 写者在沙箱中看到的同一目录
    }
    if not arm.embeddings:
        env["E09_NO_EMBED"] = "1"
    if arm.read_only:
        env["E09_READ_ONLY"] = "1"
        del env["E09_ENABLE_COMMIT"]
    if arm.hide_tools:
        env["E09_HIDE_TOOLS"] = ",".join(arm.hide_tools)
    if arm.evidence_scope:
        env["E09_EVIDENCE_SCOPE"] = arm.evidence_scope
    return ["env", *(f"{k}={v}" for k, v in env.items()), str(REPO / ".venv/bin/python"), "-m", "e09.mcp"]


def _spawn(args: list[str], stderr) -> subprocess.Popen:
    return subprocess.Popen(["python3", str(BRIDGE), *args], cwd=REPO / "experiments/e09", stderr=stderr)


def _wait_for(*socks: Path, timeout_s: float = 10) -> None:
    deadline = time.monotonic() + timeout_s
    while not all(s.exists() for s in socks):
        if time.monotonic() > deadline:
            raise RuntimeError(f"bridge sockets not ready: {[str(s) for s in socks if not s.exists()]}")
        time.sleep(0.05)


def _write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


__all__ = ["Arm", "Paths", "Writer", "prepare", "run_session"]
