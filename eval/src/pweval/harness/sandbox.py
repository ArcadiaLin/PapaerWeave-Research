"""写者与读者会话的隔离运行：一次 pi 会话在 bubblewrap 沙箱中执行（默认配置的 pi，非交互）。

沙箱隔离文件系统；写者与 P 原文组的沙箱另外断网（V3 §7 第 5 条，10-21；此前按用户 2026-10-19 的决定不断网），
大模型服务与 Graphiti 经 unix socket 转发进去（``Arm.isolated_llm``、``Arm.isolated_tcp``），联网命令只会失败，
仍由会话后的审计记下。沙箱里能看到的只有：系统目录与
node（只读）、工作目录 ``/work``（可写）、本会话的 ``HOME``（pi 的 agent 目录：模型配置、设置、MCP 登记与会话记录，
不带宿主机的扩展、skills 与认证）。写者另有论文材料 ``/work/papers`` 与按论文版本固定 commit 的代码 ``/work/code``
（都只读）；读者两者都没有。各组的 ``/work``：

- A3、A2：每个写者自己的目录；库只经 MCP 进入（见下）。
- A0：共享仓库本身（各写者共用一份，写者轮流运行）；读者是检查点处的副本，只读。仓库的 ``AGENTS.md`` 由 pi 从
  工作目录加载。
- A4：每个写者自己的目录；Graphiti 的 MCP 服务在沙箱外，经 HTTP 连接（断网时经转发，沙箱内连同一回环端口）。
- 参照线（``none``）：没有库。

仓库、``docs/``、题库与金标准、其他组与其他写者的目录、宿主机的 ``/tmp`` 都不可见；环境变量清空后只设必要的几个
（宿主机的代理设置不带进去）。

A3、A2 的 MCP 服务在沙箱外：沙箱内登记的只是一条转发命令（``mcp.sock``，:mod:`pweval.harness.bridge`），每个连接
在沙箱外启动一次服务，登录身份与连接参数在沙箱外写定，写者拿不到图库的口令。A2 启动的是消融版
（``eval/baselines/a2_mcp.py``）。大模型服务的地址取实验配置：断网的沙箱经转发连接，其余由 pi 直接连接。

``pi`` 从工作目录及其上层加载 ``AGENTS.md``：沙箱中 ``/work`` 的上层为空，仓库的说明文件不会被加载。
"""

from __future__ import annotations

import contextlib
import hashlib
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

from ..paths import REPO

BRIDGE = Path(__file__).with_name("bridge.py")
ABLATED_MCP = REPO / "eval/baselines/a2_mcp.py"  # A2：关掉机制的 PaperWeave MCP 服务
GRAPH = ("A3", "A2")  # 经 PaperWeave MCP 进入库的组
LLM_PORT = 18080  # 断网的沙箱内，pi 连这个回环端口，转发到沙箱外的大模型服务
PI_DIR = "/opt/pi"  # 托管安装的 pi：当前版本的 release 目录只读挂到这里
# V3 §7 第 6 条：沙箱中的 python3 另有固定版本的 PyYAML（为系统 python3 安装，只读），所有组相同
SITE = Path("~/pw-lab/sandbox-site/pyyaml-6.0.3").expanduser()
SITE_DIR = "/opt/t1/site"
# V3 §7 第 5 条：所有组的写者任务与读者提示语末尾的环境说明（断网与可用的 Python）
ENV_NOTE = (
    "You are working in a sandbox for a test. There is no network access: any network command (curl, wget, pip\n"
    "install, git clone, web search) will fail. Python 3 is available with the standard library and PyYAML only;\n"
    "nothing else can be installed. Use only what is available locally."
)


def site_record() -> dict[str, str]:
    """记入 ``run.yml``：挂进沙箱的 Python 包（按 dist-info 的名称）与目录内容的 SHA-256。"""
    if not SITE.is_dir():
        return {"missing": str(SITE)}
    files = sorted(f for f in SITE.rglob("*") if f.is_file())
    digest = hashlib.sha256()
    for f in files:
        digest.update(f"{f.relative_to(SITE)}\0".encode() + hashlib.sha256(f.read_bytes()).digest())
    packages = ",".join(sorted(d.name.removesuffix(".dist-info") for d in SITE.glob("*.dist-info")))
    return {"path": str(SITE), "packages": packages, "sha256": digest.hexdigest()}


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
    name: str  # A0、A2、A3、A4，或参照组 C、D、P（没有库），以及先导的 none
    papers: Path | None  # 论文材料目录（只读挂载到 /work/papers）；读者与参照线为 None
    code: Path | None = None  # 按论文版本固定 commit 的代码（只读挂载到 /work/code）；读者为 None
    store: Path | None = None  # A0：共享仓库，挂载为 /work
    neo4j: str | None = None  # A3、A2：图库
    data: Path | None = None  # A3、A2：材料根目录（PAPERWEAVE_DATA：论文与产物文档），只给沙箱外的 MCP 服务
    embeddings: bool = True
    read_only: bool = False  # 读者：库只读
    hide_tools: tuple[str, ...] = ()  # A3、A2：MCP 服务不列出的工具；A4：pi 不列出的工具（--exclude-tools）
    evidence_scope: str | None = None  # A3、A2：artifacts 时 read_evidence 只读产物文档（读者不读论文原文）
    ablate: tuple[str, ...] = ()  # A2：关掉的机制（dedup、revision、stale、affected）
    graphiti: str | None = None  # A4：Graphiti MCP 服务的地址
    pi_args: tuple[str, ...] = ()  # 附加给 pi 的参数，例如参照组的 --no-tools（docs/designs/v3/evaluation.md §10）
    isolated_llm: str | None = None  # 断网（--unshare-net）时大模型服务的地址：经 unix socket 转发进沙箱（V3 §7 第 5 条）
    isolated_tcp: tuple[str, ...] = ()  # 断网时另外转发进沙箱的服务（host:port），沙箱内在回环地址的同一端口上可连，如 A4 的 Graphiti


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


def prepare(
    paths: Paths,
    arm: Arm,
    *,
    model: str,
    llm: str,
    thinking: str,
    context_window: int,
    idle_timeout_ms: int | None,
    reserve_tokens: int,
    max_tokens: int | None = None,
) -> None:
    """建立会话的工作目录与 pi 的 agent 目录：模型配置、设置、MCP 登记，都写在本会话的 ``HOME`` 中（用户级配置，
    不受项目信任的限制；A0 的共享仓库里不放各写者的设置）。

    - 模型：宿主机 models.json 中的这一个模型，地址换成本组的大模型服务（D16：两台 sglang 按组分），上下文窗口
      取实验配置（D14：sglang 实际支持 262144）。``max_tokens`` 给出时覆盖单次回复的输出上限（宿主机为 32768；
      不带工具的参照组只有一次回复，思考与答案都在其中，评测设计 V3 §7 第 4 条）。
    - 设置：思考级别、请求的空闲超时、会话记录目录，以及压缩时预留的 token（D15：摘要的生成上限是 0.8 ×
      reserveTokens，默认 16384 时开着思考的摘要会撞上限、压缩失败）。

    已存在时保留会话记录，只重写配置。
    """
    agent = paths.home / ".pi/agent"
    for d in (agent, paths.home / "sessions", paths.sock):
        d.mkdir(parents=True, exist_ok=True)
    if arm.name != "A0":
        paths.work.mkdir(parents=True, exist_ok=True)
    provider, model_id = model.split("/", 1)
    host_agent = Path(os.environ.get("PI_CODING_AGENT_DIR", Path.home() / ".pi/agent")).expanduser()
    models = json.loads((host_agent / "models.json").read_text(encoding="utf-8"))
    entry = models["providers"][provider]
    if arm.isolated_llm is not None:
        if arm.isolated_llm != llm:
            raise ValueError(f"isolated arm forwards to {arm.isolated_llm}, but the model is configured for {llm}")
        entry["baseUrl"] = f"http://127.0.0.1:{LLM_PORT}{urlsplit(llm).path}"
    else:
        entry["baseUrl"] = llm
    limits = {"contextWindow": context_window} | ({"maxTokens": max_tokens} if max_tokens else {})
    entry["models"] = [m | limits for m in entry["models"] if m["id"] == model_id]
    if not entry["models"]:
        raise ValueError(f"{model} is not in {host_agent / 'models.json'}")
    models["providers"] = {provider: entry}
    _write_json(agent / "models.json", models)
    settings = {
        "defaultProvider": provider,
        "defaultModel": model_id,
        "modelThinkingLevels": {model: thinking},
        "compaction": {"reserveTokens": reserve_tokens},
        "sessionDir": "/home/agent/sessions",
    }
    if idle_timeout_ms is not None:  # 不设时用 pi 的默认值（V3 先导如此）
        settings["httpIdleTimeoutMs"] = idle_timeout_ms
    _write_json(agent / "settings.json", settings)
    servers = {}
    if arm.name in GRAPH:
        servers["PaperWeave"] = {
            "command": "python3",
            "args": ["/opt/t1/bridge.py", "stdio-to-unix", "/run/t1/mcp.sock"],
            "exposure": "direct",
            "timeout": 300,
        }
    elif arm.name == "A4":
        assert arm.graphiti is not None
        url = urlsplit(arm.graphiti)
        if arm.isolated_llm is not None:  # 断网：沙箱内连回环地址的同一端口（isolated_tcp 转发到沙箱外的服务）
            if f"{url.hostname}:{url.port}" not in arm.isolated_tcp:
                raise ValueError(f"an isolated A4 sandbox must forward {url.hostname}:{url.port} (isolated_tcp)")
            url = url._replace(netloc=f"127.0.0.1:{url.port}")
        servers["Graphiti"] = {"url": url.geturl(), "exposure": "direct", "timeout": 300}
    _write_json(agent / "mcp.json", {"mcpServers": servers})


def run_session(paths: Paths, arm: Arm, writer: Writer, prompt: str, *, timeout_s: int,
                max_tool_calls: int | None = None) -> dict:  # fmt: skip
    """在沙箱中跑一次 pi 会话。返回退出码、用时与这次会话的记录文件；pi 的 JSON 事件流写到 ``<root>/runs/``。

    安全上限（V3 §7 第 4 条）：会话超过 ``timeout_s`` 秒退出码记 ``timeout``；给出 ``max_tool_calls`` 时，工具调用
    （事件流中的 ``tool_execution_start``）超过它即终止，退出码记 ``tool-limit``。两者都每 15 秒检查一次。"""
    stamp = time.strftime("%Y%m%dT%H%M%S")
    runs = paths.root / "runs"
    runs.mkdir(exist_ok=True)
    if not SITE.is_dir():
        raise FileNotFoundError(f"the sandbox Python packages are missing: {SITE} (V3 §7 第 6 条)")
    sessions = paths.home / "sessions"
    before = set(sessions.rglob("*.jsonl"))
    # 转发进程与它启动的 MCP 服务的 stderr 写到会话目录（MCP 服务另有自己的日志 paperweave.log）
    stderr = open(paths.root / "bridge.err", "ab")  # noqa: SIM115
    bridges = []
    socks = []
    if arm.name in GRAPH:
        mcp = ["unix-exec", str(paths.sock / "mcp.sock"), "--", *_mcp_command(paths, arm, writer)]
        bridges.append(_spawn(mcp, stderr))
        socks.append(paths.sock / "mcp.sock")
    if arm.isolated_llm is not None:
        for name, target in _forwards(arm):
            bridges.append(_spawn(["unix-to-tcp", str(paths.sock / name), target], stderr))
            socks.append(paths.sock / name)
    try:
        if socks:
            _wait_for(*socks)
        started = time.monotonic()
        exclude = ["--exclude-tools", ",".join(arm.hide_tools)] if arm.name == "A4" and arm.hide_tools else []
        command = [pi_install()[1], "-p", "--offline", "--approve", "--mode", "json", *exclude, *arm.pi_args]
        stdin = None
        if len(prompt.encode()) > ARG_LIMIT:
            # 过长的提示语经 stdin 传入：pi 读入后去掉首尾空白，没有消息参数时即作为提示语。读者提示语都以一个换行结尾，
            # 经 stdin 时这个换行被去掉，此外逐字相同；其他首尾空白会改变提示语，不允许
            if prompt.strip() != prompt.rstrip("\n"):
                raise ValueError("a prompt passed through stdin must not start or end with whitespace other than newlines")
            stdin = runs / f"{stamp}.prompt.txt"
            stdin.write_text(prompt, encoding="utf-8")
        else:
            command.append(prompt)
        if arm.isolated_llm is not None:  # 沙箱内先起回环端口到 socket 的转发，端口都可连后再换成 pi
            command = ["bash", "-c", isolated_start(arm), "bash", *command]
        killed: list[dict] = []
        with (
            open(runs / f"{stamp}.jsonl", "wb") as out,
            open(runs / f"{stamp}.err", "wb") as err,
            open(stdin or os.devnull, "rb") as source,  # pi -p 在 stdin 不是终端时会读它
        ):
            proc = subprocess.Popen(
                [*_bwrap(paths, arm, writer), *command],
                stdin=source,
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
                    elif max_tool_calls is not None and tool_calls(runs / f"{stamp}.jsonl") > max_tool_calls:
                        proc.kill()
                        proc.wait()
                        code = "tool-limit"
                    else:
                        killed += kill_long_tools(proc.pid, TOOL_LIMIT_S, time.monotonic() - started)
        seconds = round(time.monotonic() - started, 1)
        if code == FORWARD_EXIT and FORWARD_FAILED.encode() in (runs / f"{stamp}.err").read_bytes():
            raise RuntimeError(f"the sandbox forward did not start: {(runs / f'{stamp}.err').read_text()[-500:]}")
    finally:
        for p in bridges:
            p.terminate()
            p.wait(timeout=10)
        stderr.close()
    after = set(sessions.rglob("*.jsonl"))
    session = sorted(str(p.relative_to(paths.root)) for p in after - before)
    return {"exit": code, "seconds": seconds, "events": f"runs/{stamp}.jsonl", "session": session, "tool_kills": killed}


def tool_calls(events: Path) -> int:
    """事件流中到目前为止的工具调用次数（并行的调用各算一次）。"""
    with open(events, "rb") as f:
        return f.read().count(b'"type":"tool_execution_start"')


def _forwards(arm: Arm) -> list[tuple[str, str]]:
    """断网的沙箱要转发的服务：(socket 文件名, 沙箱外的 host:port)。大模型服务在沙箱内的 ``LLM_PORT``，``isolated_tcp``
    中的服务在沙箱内的同一端口。"""
    assert arm.isolated_llm is not None
    llm = urlsplit(arm.isolated_llm)
    out = [("llm.sock", f"{llm.hostname}:{llm.port or 80}")]
    for target in arm.isolated_tcp:
        port = int(target.rsplit(":", 1)[1])
        if port == LLM_PORT:
            raise ValueError(f"port {LLM_PORT} is taken by the model forward inside the sandbox")
        out.append((f"tcp-{port}.sock", target))
    return out


def isolated_start(arm: Arm) -> str:
    """沙箱内的启动脚本：每个转发在回环地址上起一个端口接到 socket，端口都可连后 ``exec`` 换成 pi。某个端口
    ``FORWARD_WAIT_S`` 秒内仍不可连，就打印 ``FORWARD_FAILED`` 并以 ``FORWARD_EXIT`` 退出（见 :func:`run_session`）。"""
    tries = int(FORWARD_WAIT_S / 0.05)
    parts = []
    for name, target in _forwards(arm):
        port = LLM_PORT if name == "llm.sock" else int(target.rsplit(":", 1)[1])
        parts.append(f"python3 /opt/t1/bridge.py tcp-to-unix 127.0.0.1:{port} /run/t1/{name} & n=0; "
                     f"until (: >/dev/tcp/127.0.0.1/{port}) 2>/dev/null; do n=$((n+1)); "
                     f"if [ $n -gt {tries} ]; then echo '{FORWARD_FAILED} 127.0.0.1:{port}' >&2; exit {FORWARD_EXIT}; fi; "
                     f"sleep 0.05; done; ")  # fmt: skip
    return "".join(parts) + 'exec "$@"'
FORWARD_WAIT_S = 10  # 沙箱内的转发端口最多等这么久；起不来是基础设施故障，不记作会话超时
FORWARD_FAILED = "FORWARD_FAILED"
FORWARD_EXIT = 97
ARG_LIMIT = 100_000  # 字节；单个命令行参数的上限是 131072 字节（Linux MAX_ARG_STRLEN），D 的长材料会超过
TOOL_LIMIT_S = 600  # 单个 shell 工具命令的时限：超过即终止，pi 收到出错结果后继续（两组相同）


def _start_ticks(pid: int) -> int | None:
    """进程的启动时刻（``/proc/<pid>/stat`` 第 22 项，开机以来的时钟滴答）；进程已不在时为 None。"""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    return int(stat[stat.rindex(")") + 2 :].split()[19])


def kill_long_tools(root: int, limit_s: int, root_age_s: float) -> list[dict]:
    """终止沙箱中运行超过 ``limit_s`` 秒的 shell 工具命令（pi 为每次 bash 工具调用起的 ``bash -c``）及其子进程。
    pilot-2 中一个写者的脚本陷入死循环，没有这个时限就要等到会话超时、整次会话作废。

    进程年龄按启动滴答相对 ``root``（已运行 ``root_age_s`` 秒）计算，不用 ps 的 etimes：LXC 容器中 /proc/uptime
    被虚拟化，etimes 对所有进程都溢出成约 41 亿秒，f1 开头因此每次轮询都把正在运行的 shell 命令当作超时终止。"""
    rows = subprocess.run(["ps", "-eo", "pid=,ppid=,args="], capture_output=True, text=True).stdout
    procs = {}
    for line in rows.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3:
            procs[int(parts[0])] = (int(parts[1]), parts[2])
    root_ticks = _start_ticks(root)
    hz = os.sysconf("SC_CLK_TCK")
    children: dict[int, list[int]] = {}
    for pid, (ppid, _) in procs.items():
        children.setdefault(ppid, []).append(pid)

    def tree(pid: int) -> list[int]:
        out = [pid]
        for c in children.get(pid, []):
            out += tree(c)
        return out

    killed = []
    if root_ticks is None:
        return killed
    for pid in tree(root)[1:]:
        ppid, args = procs[pid]
        parent = procs.get(ppid, (0, ""))[1]
        if not (re.match(r"(/usr)?(/bin/)?bash -c ", args) and re.search(r"\bpi\b|node", parent)):
            continue
        ticks = _start_ticks(pid)
        if ticks is None:
            continue
        age = round(root_age_s - (ticks - root_ticks) / hz)
        if age > limit_s:
            for victim in reversed(tree(pid)):
                with contextlib.suppress(ProcessLookupError):
                    os.kill(victim, signal.SIGKILL)
            killed.append({"seconds": age, "command": args[:300]})
    return killed


def _bwrap(paths: Paths, arm: Arm, writer: Writer) -> list[str]:
    node = Path(shutil.which("node") or "").resolve().parent.parent
    work = arm.store if arm.name == "A0" else paths.work
    assert work is not None
    args = [
        "bwrap", "--unshare-all", *(() if arm.isolated_llm else ("--share-net",)), "--die-with-parent", "--clearenv",
        "--ro-bind", "/usr", "/usr",
        "--symlink", "usr/bin", "/bin", "--symlink", "usr/lib", "/lib",
        "--symlink", "usr/lib64", "/lib64", "--symlink", "usr/sbin", "/sbin",
        "--ro-bind", "/etc", "/etc", "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
        "--ro-bind", str(node), str(node),
        *(["--ro-bind", str(pi_dir), PI_DIR] if (pi_dir := pi_install()[0]) else []),
        "--ro-bind" if arm.read_only and arm.name == "A0" else "--bind", str(work), "/work",
        "--bind", str(paths.home), "/home/agent",
        "--ro-bind", str(SITE), SITE_DIR,
    ]  # fmt: skip
    if arm.name in GRAPH or arm.isolated_llm:
        args += ["--ro-bind", str(BRIDGE), "/opt/t1/bridge.py", "--bind", str(paths.sock), "/run/t1"]
    for source, target in ((arm.papers, "/work/papers"), (arm.code, "/work/code")):
        if source is not None:
            (work / target.removeprefix("/work/")).mkdir(exist_ok=True)  # 挂载点；A0 的仓库在 .gitignore 中忽略它们
            args += ["--ro-bind", str(source), target]
    env = {
        "HOME": "/home/agent",
        "PATH": f"{node}/bin:/usr/bin",
        "LANG": "C.UTF-8",
        "TERM": "dumb",
        "PYTHONPATH": SITE_DIR,
        "GIT_AUTHOR_NAME": writer.user,
        "GIT_AUTHOR_EMAIL": writer.user,
        "GIT_COMMITTER_NAME": writer.user,
        "GIT_COMMITTER_EMAIL": writer.user,
    }
    for key, value in env.items():
        args += ["--setenv", key, value]
    return [*args, "--chdir", "/work"]


def mcp_env(paths: Paths, arm: Arm, writer: Writer) -> dict[str, str]:
    """A3、A2 的 MCP 服务在沙箱外的环境：库、材料根目录、登录身份、工作目录与开关。"""
    assert arm.neo4j is not None and arm.data is not None
    env = {
        "PAPERWEAVE_NEO4J_URI": arm.neo4j,
        "PAPERWEAVE_DATA": str(arm.data),
        "PAPERWEAVE_USER": writer.user,
        "PAPERWEAVE_AGENT": writer.agent,
        "PAPERWEAVE_MCP_LOG": str(paths.root / "paperweave.log"),
        "PAPERWEAVE_WORKDIR": str(paths.work),  # 草稿文件（payload_file、doc_file）只从写者的工作目录读
        "PAPERWEAVE_WORKDIR_ALIAS": "/work",  # 写者在沙箱中看到的同一目录
    }
    if not arm.embeddings:
        env["PAPERWEAVE_NO_EMBED"] = "1"
    if arm.read_only:
        env["PAPERWEAVE_READ_ONLY"] = "1"
    if arm.hide_tools:
        env["PAPERWEAVE_HIDE_TOOLS"] = ",".join(arm.hide_tools)
    if arm.evidence_scope:
        env["PAPERWEAVE_EVIDENCE_SCOPE"] = arm.evidence_scope
    if arm.ablate:
        env["PAPERWEAVE_ABLATE"] = ",".join(arm.ablate)
    return env


def _mcp_command(paths: Paths, arm: Arm, writer: Writer) -> list[str]:
    env = mcp_env(paths, arm, writer)
    entry = [str(ABLATED_MCP)] if arm.ablate else ["-m", "paperweave.mcp"]
    return ["env", *(f"{k}={v}" for k, v in env.items()), str(REPO / ".venv/bin/python"), *entry]


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


__all__ = ["ENV_NOTE", "GRAPH", "Arm", "Paths", "Writer", "isolated_start", "pi_install", "pi_version", "prepare",
           "run_session"]
