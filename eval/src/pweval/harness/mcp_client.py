"""最小的 MCP stdio 客户端，只用标准库：评测框架经被测系统的 MCP 入口检入种子、给写者取 skill（evaluation_draft
§10.1“只经外部接口交互”）。

    with Client([sys.executable, "-m", "paperweave.mcp"], env) as client:
        text = client.call("CheckIn", {"artifact_doc": [...], "update_abstract": "..."})

服务进程的环境（库地址、``PAPERWEAVE_WORKDIR``、``PAPERWEAVE_USER`` 等）由调用者给出；stdio 上逐行 JSON-RPC。
:class:`HttpClient` 是同样用法的 HTTP 版（streamable HTTP），给 A4 的种子经 Graphiti 的 MCP 服务写入。
工具结果是文本，:func:`status` 与 :func:`field` 只按行取顶层键，不解析结果的结构。
"""

from __future__ import annotations

import json
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
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


class HttpClient:
    """streamable HTTP 上的 MCP 客户端：每个请求一次 POST，回复是 JSON 或 SSE（取其中 ``data:`` 行的 JSON）；
    初始化时服务给出的 ``mcp-session-id`` 随之后的请求带上。"""

    def __init__(self, url: str, *, name: str = "t1", timeout_s: float = 300) -> None:
        self.url, self.name, self.timeout_s, self.next_id = url, name, timeout_s, 0
        self.session: str | None = None

    def __enter__(self) -> HttpClient:
        info = {"name": self.name, "version": "1"}
        self._post({"jsonrpc": "2.0", "id": self._id(), "method": "initialize",
                    "params": {"protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": info}})  # fmt: skip
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return self

    def __exit__(self, kind: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None) -> None:
        return None

    def call(self, tool: str, arguments: dict) -> str:
        msg = self._post({"jsonrpc": "2.0", "id": self._id(), "method": "tools/call",
                          "params": {"name": tool, "arguments": arguments}})  # fmt: skip
        if msg is None or "error" in msg:
            raise RuntimeError(f"{tool}: {msg}")
        return "\n".join(c.get("text", "") for c in msg["result"].get("content", []))

    def _id(self) -> int:
        self.next_id += 1
        return self.next_id

    def _post(self, body: dict) -> dict | None:
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self.session:
            headers["mcp-session-id"] = self.session
        req = urllib.request.Request(self.url, data=json.dumps(body).encode(), headers=headers, method="POST")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 本机服务，不走代理
        try:
            resp = opener.open(req, timeout=self.timeout_s)
        except urllib.error.HTTPError as exc:  # urllib 不对 POST 跟随 307/308（Graphiti 把 /mcp/ 转到 /mcp）
            if exc.code not in (307, 308) or not exc.headers.get("Location"):
                raise
            self.url = urllib.parse.urljoin(self.url, exc.headers["Location"])
            return self._post(body)
        with resp:
            self.session = resp.headers.get("mcp-session-id") or self.session
            text = resp.read().decode("utf-8")
        if not text.strip():
            return None
        if resp.headers.get("Content-Type", "").startswith("text/event-stream"):
            data = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")]
            return json.loads(data[-1]) if data else None
        return json.loads(text)


def field(text: str, name: str) -> str | None:
    """工具结果中顶层键 ``name`` 的值（同一行内的标量）。"""
    m = re.search(rf"^{re.escape(name)}: (\S+)", text, re.M)
    return m[1] if m else None


def status(text: str) -> str | None:
    return field(text, "status")


__all__ = ["Client", "HttpClient", "field", "status"]
