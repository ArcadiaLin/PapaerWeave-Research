"""沙箱转发只搬运字节：TCP ↔ unix socket 往返，以及每个连接启动一次命令（MCP 服务的接法）。"""

from __future__ import annotations

import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from pweval.harness.sandbox import BRIDGE


def _bridge(*args: str) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, str(BRIDGE), *args])


def _wait(path: Path) -> None:
    deadline = time.monotonic() + 5
    while not path.exists():
        assert time.monotonic() < deadline, f"{path} not ready"
        time.sleep(0.02)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_tcp_round_trip_through_a_unix_socket(tmp_path: Path) -> None:
    upstream = socket.create_server(("127.0.0.1", 0))
    upstream_port = upstream.getsockname()[1]

    def echo() -> None:
        conn, _ = upstream.accept()
        with conn:
            conn.sendall(b"echo:" + conn.recv(1024))

    threading.Thread(target=echo, daemon=True).start()
    sock, port = tmp_path / "llm.sock", _free_port()
    outside = _bridge("unix-to-tcp", str(sock), f"127.0.0.1:{upstream_port}")
    try:
        _wait(sock)
        inside = _bridge("tcp-to-unix", f"127.0.0.1:{port}", str(sock))
        try:
            deadline = time.monotonic() + 5
            while True:
                try:
                    client = socket.create_connection(("127.0.0.1", port))
                    break
                except ConnectionRefusedError:
                    assert time.monotonic() < deadline
                    time.sleep(0.02)
            with client:
                client.sendall(b"ping")
                assert client.recv(1024) == b"echo:ping"
        finally:
            inside.terminate()
    finally:
        outside.terminate()
        upstream.close()


def test_each_connection_runs_the_command_on_stdio(tmp_path: Path) -> None:
    sock = tmp_path / "mcp.sock"
    server = _bridge("unix-exec", str(sock), "--", "cat")
    try:
        _wait(sock)
        for line in (b'{"id": 1}\n', b'{"id": 2}\n'):
            client = subprocess.run(
                [sys.executable, str(BRIDGE), "stdio-to-unix", str(sock)],
                input=line,
                capture_output=True,
                timeout=10,
            )
            assert client.stdout == line
    finally:
        server.terminate()
