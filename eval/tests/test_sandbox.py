"""沙箱怎样找到 pi（npm 全局安装随 node 挂载；托管安装只挂当前版本的 release 目录，不挂 ``~/.pi/agent``），
以及各组会话的挂载、网络、pi 设置与 MCP 登记。"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from pweval.harness import sandbox
from pweval.harness.sandbox import PI_DIR, Arm, Paths, Writer, pi_install


def _fake_which(node: Path):
    return lambda name: str(node) if name == "node" else None


def test_npm_global_pi_comes_with_node(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bin_dir = tmp_path / "node/bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "node").touch()
    (bin_dir / "pi").touch()
    monkeypatch.setattr(sandbox.shutil, "which", _fake_which(bin_dir / "node"))
    assert pi_install(str(bin_dir / "pi")) == (None, "pi")


def test_managed_pi_mounts_only_the_current_release(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = tmp_path / ".pi/agent"
    release = agent / "install/releases/1.2.0"
    (release / "node_modules/.bin").mkdir(parents=True)
    (release / "node_modules/.bin/pi").touch()
    (agent / "install/current-version").write_text("1.2.0\n", encoding="utf-8")
    (agent / "bin").mkdir()
    (agent / "bin/pi").touch()
    link = tmp_path / ".local/bin/pi"
    link.parent.mkdir(parents=True)
    link.symlink_to(agent / "bin/pi")
    (tmp_path / "usr/bin").mkdir(parents=True)
    monkeypatch.setattr(sandbox.shutil, "which", _fake_which(tmp_path / "usr/bin/node"))
    assert pi_install(str(link)) == (release.resolve(), f"{PI_DIR}/node_modules/.bin/pi")

    (agent / "install/current-version").write_text("9.9.9\n", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="missing"):
        pi_install(str(link))


# 各组的挂载、网络、pi 设置与 MCP 登记（不实际启动 bwrap）


@pytest.fixture
def host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    agent = tmp_path / "host-agent"
    agent.mkdir()
    models = {"providers": {"sglang": {"baseUrl": "http://192.0.2.1:30000/v1", "models": [{"id": "m"}, {"id": "x"}]}}}
    (agent / "models.json").write_text(json.dumps(models), encoding="utf-8")
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(agent))
    monkeypatch.setattr(sandbox, "pi_install", lambda: (None, "pi"))
    for d in ("papers", "code", "store", "data"):
        (tmp_path / d).mkdir()
    return tmp_path


SETTINGS = {
    "model": "sglang/m",
    "llm": "http://192.0.2.1:30001/v1",
    "thinking": "off",
    "context_window": 262144,
    "idle_timeout_ms": 600000,
    "reserve_tokens": 32768,
}
WRITER = Writer("w", "w@lab.example", "pi/sglang/m")


def _mounts(args: list[str]) -> dict[str, tuple[str, str]]:
    """bwrap 参数中的挂载：目标 → (方式, 来源)。"""
    out = {}
    for i, a in enumerate(args):
        if a in ("--bind", "--ro-bind"):
            out[args[i + 2]] = (a, args[i + 1])
    return out


def test_pi_settings_go_to_the_session_home(host: Path) -> None:
    paths = Paths(host / "run/A3/w")
    sandbox.prepare(paths, Arm("A3", host / "papers", neo4j="bolt://x", data=host / "data"), **SETTINGS)
    agent = paths.home / ".pi/agent"
    provider = json.loads((agent / "models.json").read_text())["providers"]["sglang"]
    assert provider["baseUrl"] == SETTINGS["llm"]  # 本组的大模型服务（D16），不经转发
    assert provider["models"] == [{"id": "m", "contextWindow": 262144}]  # D14
    settings = json.loads((agent / "settings.json").read_text())
    assert settings["compaction"] == {"reserveTokens": 32768}  # D15
    assert settings["sessionDir"] == "/home/agent/sessions"
    mcp = json.loads((agent / "mcp.json").read_text())["mcpServers"]
    assert list(mcp) == ["PaperWeave"] and mcp["PaperWeave"]["args"][-1] == "/run/t1/mcp.sock"
    assert not (paths.work / ".pi").exists()  # 工作目录里不放 pi 的配置


def test_max_tokens_overrides_the_output_limit_only_when_given(host: Path) -> None:
    paths = Paths(host / "run/C/r")
    sandbox.prepare(paths, Arm("C", None), **SETTINGS, max_tokens=98304)
    provider = json.loads((paths.home / ".pi/agent/models.json").read_text())["providers"]["sglang"]
    assert provider["models"] == [{"id": "m", "contextWindow": 262144, "maxTokens": 98304}]


def test_writer_sees_work_papers_and_code_with_the_network_shared(host: Path) -> None:
    paths = Paths(host / "run/A3/w")
    arm = Arm("A3", host / "papers", code=host / "code", neo4j="bolt://x", data=host / "data")
    sandbox.prepare(paths, arm, **SETTINGS)
    args = sandbox._bwrap(paths, arm, WRITER)
    assert "--unshare-all" in args and "--share-net" in args
    mounts = _mounts(args)
    assert mounts["/work"] == ("--bind", str(paths.work))
    assert mounts["/work/papers"] == ("--ro-bind", str(host / "papers"))
    assert mounts["/work/code"] == ("--ro-bind", str(host / "code"))
    assert mounts["/home/agent"] == ("--bind", str(paths.home))
    assert "/run/t1" in mounts
    assert str(host / "data") not in {src for _, src in mounts.values()}  # 材料根目录只给沙箱外的 MCP 服务
    assert all(not t.startswith(str(Path.home())) for t in mounts)  # 宿主机的 HOME 不挂载


def test_an_f3_writer_gets_sources_only_through_read_source(host: Path) -> None:
    """f3 §2、§4：不挂载论文与代码；来源服务在沙箱外，/work/sources 只读；MCP 服务的来源目录是本组已开放的来源。"""
    paths = Paths(host / "run/A3/sessions/001")
    read = sandbox.ReadSource(host / "sources", host / "papers", host / "code", ("2106.13008v5", "Autoformer@09994619"),
                              "A3-001")  # fmt: skip
    arm = Arm("A3", None, neo4j="bolt://x", data=host / "data", sources=host / "sources", read_source=read,
              isolated_llm=SETTINGS["llm"])  # fmt: skip
    sandbox.prepare(paths, arm, **SETTINGS)
    mounts = _mounts(sandbox._bwrap(paths, arm, WRITER))
    assert mounts["/work/sources"] == ("--ro-bind", str(paths.work / "sources"))
    assert "/work/papers" not in mounts and "/work/code" not in mounts
    sources = {src for _, src in mounts.values()}
    assert str(host / "papers") not in sources and str(host / "sources") not in sources
    mcp = json.loads((paths.home / ".pi/agent/mcp.json").read_text())["mcpServers"]
    assert list(mcp) == ["PaperWeave", "Sources"] and mcp["Sources"]["args"][-1] == "/run/t1/sources.sock"
    command = sandbox._source_command(paths, arm)
    assert command[1:3] == ["-m", "pweval.harness.source_server"]
    assert command[command.index("--dest") + 1] == str(paths.work / "sources")
    assert command[command.index("--library") + 1] == str(host / "sources")  # 与 MCP 服务读同一份（审查第 2 条）
    assert json.loads((paths.root / "opened.json").read_text()) == ["2106.13008v5", "Autoformer@09994619"]
    assert f"PAPERWEAVE_SOURCES={host / 'sources'}" in sandbox._mcp_command(paths, arm, WRITER)


def test_a0_writer_works_in_the_shared_repository(host: Path) -> None:
    paths = Paths(host / "run/A0/w")
    arm = Arm("A0", host / "papers", code=host / "code", store=host / "store")
    sandbox.prepare(paths, arm, **SETTINGS)
    mounts = _mounts(sandbox._bwrap(paths, arm, WRITER))
    assert mounts["/work"] == ("--bind", str(host / "store"))
    assert mounts["/work/papers"][0] == "--ro-bind"
    assert "/run/t1" not in mounts
    assert json.loads((paths.home / ".pi/agent/mcp.json").read_text()) == {"mcpServers": {}}
    assert not paths.work.exists()


def test_readers_get_no_papers_and_no_code(host: Path) -> None:
    for arm in (
        Arm("A0", None, store=host / "store", read_only=True),
        Arm("A3F", None, store=host / "store", read_only=True),
        Arm("A3", None, neo4j="bolt://x", data=host / "data", read_only=True, evidence_scope="artifacts"),
        Arm("A4", None, graphiti="http://127.0.0.1:8765/mcp/", hide_tools=("mcp__Graphiti__add_memory",)),
    ):
        paths = Paths(host / "run" / arm.name / "reader")
        sandbox.prepare(paths, arm, **SETTINGS)
        mounts = _mounts(sandbox._bwrap(paths, arm, WRITER))
        assert "/work/papers" not in mounts and "/work/code" not in mounts
        if arm.name in ("A0", "A3F"):
            assert mounts["/work"] == ("--ro-bind", str(host / "store"))  # 检查点处的副本，只读
            assert "PaperWeave" not in json.loads((paths.home / ".pi/agent/mcp.json").read_text())["mcpServers"]


def test_an_isolated_reader_has_no_network_and_reaches_the_model_through_a_socket(host: Path) -> None:
    paths = Paths(host / "run/P/k10/rep1/q")
    arm = Arm("P", host / "papers", read_only=True, isolated_llm=SETTINGS["llm"])
    sandbox.prepare(paths, arm, **SETTINGS)
    provider = json.loads((paths.home / ".pi/agent/models.json").read_text())["providers"]["sglang"]
    assert provider["baseUrl"] == f"http://127.0.0.1:{sandbox.LLM_PORT}/v1"  # 沙箱内的回环端口，路径保留
    args = sandbox._bwrap(paths, arm, WRITER)
    assert "--unshare-all" in args and "--share-net" not in args
    mounts = _mounts(args)
    assert mounts["/work/papers"] == ("--ro-bind", str(host / "papers"))
    assert mounts["/run/t1"] == ("--bind", str(paths.sock)) and "/opt/t1/bridge.py" in mounts
    assert mounts[sandbox.SITE_DIR] == ("--ro-bind", str(sandbox.SITE))  # PyYAML（§7 第 6 条），所有组相同
    assert args[args.index("PYTHONPATH") + 1] == sandbox.SITE_DIR
    assert "/work/code" not in mounts
    with pytest.raises(ValueError, match="forwards to"):  # 转发目标与模型配置必须一致
        sandbox.prepare(paths, Arm("P", None, isolated_llm="http://192.0.2.9:1/v1"), **SETTINGS)


def test_tool_calls_are_counted_from_the_event_stream(tmp_path: Path) -> None:
    events = tmp_path / "e.jsonl"
    rows = [{"type": "tool_execution_start", "toolName": "bash"}, {"type": "tool_execution_end"},
            {"type": "tool_execution_start", "toolName": "read"}, {"type": "message_end"}]  # fmt: skip
    events.write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows))
    assert sandbox.tool_calls(events) == 2


def test_a4_registers_graphiti_over_http(host: Path) -> None:
    paths = Paths(host / "run/A4/w")
    arm = Arm("A4", host / "papers", code=host / "code", graphiti="http://127.0.0.1:8765/mcp/")
    sandbox.prepare(paths, arm, **SETTINGS)
    mcp = json.loads((paths.home / ".pi/agent/mcp.json").read_text())["mcpServers"]
    assert mcp == {"Graphiti": {"url": "http://127.0.0.1:8765/mcp/", "exposure": "direct", "timeout": 300}}
    assert "/run/t1" not in _mounts(sandbox._bwrap(paths, arm, WRITER))


def test_an_isolated_a4_writer_reaches_graphiti_through_a_forward(host: Path) -> None:
    paths = Paths(host / "run/A4/w")
    arm = Arm("A4", host / "papers", graphiti="http://127.0.0.1:8765/mcp/", isolated_llm=SETTINGS["llm"],
              isolated_tcp=("127.0.0.1:8765",))  # fmt: skip
    sandbox.prepare(paths, arm, **SETTINGS)
    mcp = json.loads((paths.home / ".pi/agent/mcp.json").read_text())["mcpServers"]
    assert mcp["Graphiti"]["url"] == "http://127.0.0.1:8765/mcp/"  # 沙箱内回环地址的同一端口
    args = sandbox._bwrap(paths, arm, WRITER)
    assert "--share-net" not in args and "/run/t1" in _mounts(args)
    start = sandbox.isolated_start(arm)
    assert f"tcp-to-unix 127.0.0.1:{sandbox.LLM_PORT} /run/t1/llm.sock" in start
    assert "tcp-to-unix 127.0.0.1:8765 /run/t1/tcp-8765.sock" in start and start.endswith('exec "$@"')
    assert sandbox._forwards(arm) == [("llm.sock", "192.0.2.1:30001"), ("tcp-8765.sock", "127.0.0.1:8765")]
    with pytest.raises(ValueError, match="must forward"):  # 断网却没有转发 Graphiti
        sandbox.prepare(paths, Arm("A4", None, graphiti="http://127.0.0.1:8765/mcp/", isolated_llm=SETTINGS["llm"]),
                        **SETTINGS)  # fmt: skip


def test_a2_starts_the_ablated_server(host: Path) -> None:
    paths = Paths(host / "run/A2/w")
    arm = Arm("A2", host / "papers", neo4j="bolt://x", data=host / "data", ablate=("dedup", "revision"))
    command = sandbox._mcp_command(paths, arm, WRITER)
    assert "PAPERWEAVE_ABLATE=dedup,revision" in command
    assert command[-1] == str(sandbox.ABLATED_MCP) and sandbox.ABLATED_MCP.exists()
    a3 = sandbox._mcp_command(paths, Arm("A3", host / "papers", neo4j="bolt://x", data=host / "data"), WRITER)
    assert a3[-2:] == ["-m", "paperweave.mcp"] and not any(c.startswith("PAPERWEAVE_ABLATE") for c in a3)


ABLATION_PROBE = """
import runpy, sys
runpy.run_path(sys.argv[1])  # 不以 __main__ 运行：只装上消融，不启动服务
from paperweave.artifact import stale
from paperweave.query import read
def hidden(check):
    try:
        return check()
    except Exception:  # 没换掉的真实函数要连库，传 None 即报错
        return False
print(hidden(lambda: stale.stale(None, ["art_0001"]) == {"art_0001": []}),
      hidden(lambda: read.anchor_versions(None, ["exp_0001"]) == {}))
"""


@pytest.mark.parametrize(("ablate", "expected"), [("stale", "True True"), ("dedup", "False False")])
def test_a2_stale_ablation_also_hides_anchor_version(ablate: str, expected: str) -> None:
    """stale 关掉产物的 _stale，也关掉记录的 _anchor_version（f3 新增的过时提示，读视图按名字导入它）；
    其他消融不碰这两处。"""
    env = {"PAPERWEAVE_ABLATE": ablate, "PATH": "/usr/bin:/bin"}
    out = subprocess.run([sys.executable, "-c", ABLATION_PROBE, str(sandbox.ABLATED_MCP)], env=env,
                         capture_output=True, text=True, check=True).stdout  # fmt: skip
    assert out.strip() == expected


def _tool_tree() -> tuple[subprocess.Popen, float]:
    """一个以 ``node`` 为名的进程，下面起一条 ``bash -c`` 工具命令，形状与 pi 的 bash 工具调用相同。"""
    started = time.monotonic()
    root = subprocess.Popen(["bash", "-c", "exec -a node bash -c 'bash -c \"sleep 30; true\" & wait'"])
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        rows = subprocess.run(["ps", "-o", "args=", "--ppid", str(root.pid)], capture_output=True, text=True).stdout
        if "sleep 30" in rows:
            break
        time.sleep(0.05)
    return root, started


def test_a_young_tool_command_is_not_killed() -> None:
    # f1 开头：LXC 中 ps 的 etimes 对所有进程都溢出（约 41 亿秒），正在运行的 shell 命令每次轮询都被当作超时终止
    root, started = _tool_tree()
    try:
        assert sandbox.kill_long_tools(root.pid, 600, time.monotonic() - started) == []
    finally:
        root.kill()
        root.wait()


def test_a_tool_command_over_the_limit_is_killed() -> None:
    root, started = _tool_tree()
    try:
        time.sleep(1.2)
        killed = sandbox.kill_long_tools(root.pid, 0, time.monotonic() - started)
        assert [k["command"] for k in killed] == ['bash -c sleep 30; true']
        assert 0 < killed[0]["seconds"] < 5
    finally:
        root.kill()
        root.wait()


def test_a_forward_that_does_not_start_fails_fast(host: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    arm = Arm("P", None, isolated_llm=SETTINGS["llm"])
    monkeypatch.setattr(sandbox, "FORWARD_WAIT_S", 0.2)
    script = sandbox.isolated_start(arm).replace("python3 /opt/t1/bridge.py", "true")  # 转发进程起不来
    started = time.monotonic()
    done = subprocess.run(["bash", "-c", script, "bash", "echo", "pi"], capture_output=True, text=True)
    assert done.returncode == sandbox.FORWARD_EXIT and sandbox.FORWARD_FAILED in done.stderr
    assert time.monotonic() - started < 5  # 不等到会话时限


def test_an_f3_reader_gets_the_evidence_server_and_a_read_only_store(host: Path) -> None:
    paths = Paths(host / "run/A3/readers/k10/sessions/p1")
    evidence = sandbox.ReadEvidence(host / "allowlists/A3/k10.json", host / "sources", "p1")
    arm = Arm("A3", None, neo4j="bolt://x", data=host / "data", read_only=True, hide_tools=("read_evidence",),
              isolated_llm=SETTINGS["llm"], sources=host / "sources", evidence=evidence)  # fmt: skip
    sandbox.prepare(paths, arm, **SETTINGS)
    mcp = json.loads((paths.home / ".pi/agent/mcp.json").read_text())["mcpServers"]
    assert sorted(mcp) == ["Evidence", "PaperWeave"]  # 没有 Sources：读者不用 read_source
    assert mcp["Evidence"]["args"] == ["/opt/t1/bridge.py", "stdio-to-unix", "/run/t1/evidence.sock"]
    env = sandbox.mcp_env(paths, arm, WRITER)
    assert env["PAPERWEAVE_READ_ONLY"] == "1" and env["PAPERWEAVE_HIDE_TOOLS"] == "read_evidence"
    assert sandbox._evidence_command(paths, arm)[2:] == [
        "pweval.harness.evidence_server", "--allowlist", str(host / "allowlists/A3/k10.json"),
        "--library", str(host / "sources"), "--log", str(paths.root / "evidence.jsonl"), "--session", "p1"]  # fmt: skip
    args = sandbox._bwrap(paths, arm, WRITER)
    assert "--share-net" not in args and "/run/t1" in _mounts(args)
    assert "/work/papers" not in _mounts(args) and "/work/sources" not in _mounts(args)


def test_deep_session_directories_get_a_short_socket_directory(tmp_path: Path) -> None:
    deep = Paths(Path("/home/lzx/pw-lab/runs/f3-readers-smoke/A3/readers/k10/sessions/M-T10-tide-patchtst-elsewhere"))
    assert deep.sock.parent == sandbox.SHORT_SOCKS and deep.sock == Paths(deep.root).sock  # 与会话一一对应
    assert len(str(deep.sock / "tcp-65535.sock").encode()) < 108 and len(str(deep.sock / "evidence.sock")) < 108
    writer = Paths(Path("/home/lzx/pw-lab/runs/f3/A4/sessions/007-20261023T201405564176Z"))
    assert writer.sock == writer.root / "sock"  # 写者的会话目录照旧
