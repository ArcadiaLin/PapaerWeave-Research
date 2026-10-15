"""最小的 MCP stdio 客户端，只用标准库：评测框架经被测系统的 MCP 入口检入种子、给写者取 skill（evaluation_draft
§10.1“只经外部接口交互”）。

    with Client([sys.executable, "-m", "paperweave.mcp"], env) as client:
        text = client.call("CheckIn", {"artifact_doc": [...], "update_abstract": "..."})

服务进程的环境（库地址、``PAPERWEAVE_WORKDIR``、``PAPERWEAVE_USER`` 等）由调用者给出；stdio 上逐行 JSON-RPC。
工具结果是文本，:func:`status` 与 :func:`field` 只按行取顶层键，不解析结果的结构。
"""

from __future__ import annotations

import json
import re
import subprocess
from types import TracebackType

PROTOCOL = "2025-06-18"


class Client:
    """初始化后逐个调用工具；回复是工具结果的文本。服务的 stderr 丢弃（服务自己有日志）。"""

    def __init__(self, cmd: list[str], env: dict[str, str], *, name: str = "t1") -> None:
        self.cmd, self.env, self.name, self.next_id = cmd, env, name, 0
        self.proc: subprocess.Popen[str] | None = None

    def __enter__(self) -> Client:
        self.proc = subprocess.Popen(
            self.cmd, env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
        )
        info = {"name": self.name, "version": "1"}
        self._request("initialize", {"protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": info})
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return self

    def __exit__(self, kind: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None) -> None:
        assert self.proc is not None and self.proc.stdin is not None
        self.proc.stdin.close()
        self.proc.wait(timeout=60)

    def call(self, tool: str, arguments: dict) -> str:
        result = self._request("tools/call", {"name": tool, "arguments": arguments})
        return "\n".join(c.get("text", "") for c in result.get("content", []))

    def _request(self, method: str, params: dict) -> dict:
        assert self.proc is not None and self.proc.stdout is not None
        self.next_id += 1
        self._send({"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params})
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError(f"MCP server exited during {method}")
            msg = json.loads(line)
            if msg.get("id") == self.next_id:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg["result"]

    def _send(self, msg: dict) -> None:
        assert self.proc is not None and self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()


def field(text: str, name: str) -> str | None:
    """工具结果中顶层键 ``name`` 的值（同一行内的标量）。"""
    m = re.search(rf"^{re.escape(name)}: (\S+)", text, re.M)
    return m[1] if m else None


def status(text: str) -> str | None:
    return field(text, "status")


__all__ = ["Client", "field", "status"]
