"""来源服务 ``read_source``：模拟从 arXiv、代码托管站取固定版本的材料（docs/experiments/f3/2026-10-22-f3-design.md §4；
工程记录 B3）。只用标准库的 MCP stdio 服务，四组接法与说明相同。

    python -m pweval.harness.source_server --library DIR --opened FILE --dest DIR --log FILE --session ID
        [--papers DIR --code DIR]

运行器为每个会话在沙箱外启动一次（经 :mod:`pweval.harness.bridge` 的 ``unix-exec`` 接入沙箱，与 A3 的 MCP 服务相同）：

- ``--library``：交付的唯一来源，即组的已开放来源目录（论文 ``<来源 ID>/paper.md``，代码 ``<仓库>@<commit>/``）。运行器
  在每个会话开始前按材料表核对其中每个来源的哈希；A3、A2 的 MCP 服务读同一目录，写者取到的与提交校验所用的是同一份；
- ``--papers``、``--code``：语料中的论文与代码，只用来在拒绝时记下原因（尚未开放还是不在语料中），不从中交付；
- ``--opened``：本会话可取的来源 ID（JSON 列表），由运行器按材料表算出：种子与此前开放的，加上本会话新开放的；
- ``--dest``：本会话 ``/work/sources/`` 在宿主机上的路径；写者看到的路径是 ``--alias``（默认 ``/work/sources``）；
- ``--log``：每次请求追加一行 JSON（请求、解析结果、结果、拷贝字节数），拒绝也记，原因只进记录。

一次一个来源：论文拷到 ``<dest>/<ID>/paper.md``；代码拷到 ``<dest>/<仓库>@<commit>/``（原有目录结构），清单
``<dest>/<仓库>@<commit>.files.tsv``（每行 路径、行数、SHA-256）放在仓库目录之外。拷来的文件只读。返回一条不到
1 KiB 的 JSON。同一会话再取同一来源时不重拷，返回已有路径（``reused``）并报告本地副本是否与来源一致（``intact``）。

不能检索、不能列目录：未开放与不存在统一回答 ``no source with this id is available``，不泄露以后会出现的材料。
不带版本的 arXiv 编号解析为该编号已开放的最新版本，返回实际版本。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any

PAPER = re.compile(r"\d{4}\.\d{4,5}v\d+")
CODE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*@[0-9a-f]{8}")
NUMBER = re.compile(r"\d{4}\.\d{4,5}")
REFUSED = "no source with this id is available"
FORMAT = "write the id alone: a paper like 2106.13008v5, a code repository like Autoformer@09994619"
PROTOCOL = "2025-06-18"

DESCRIPTION = (
    "Fetch a fixed version of a paper or a code repository by its id into /work/sources/, then read it with your file "
    "tools. A paper id is an arXiv id with its version, such as 2106.13008v5 (an id without the version gives the "
    "latest available version); a repository id is <name>@<commit>, such as Autoformer@09994619. A paper arrives as "
    "/work/sources/<id>/paper.md; a repository as the directory /work/sources/<id>/, with its file list (path, lines, "
    "sha256) in /work/sources/<id>.files.tsv. Only ids are accepted: there is no search and no listing."
)
TOOL = {
    "name": "read_source",
    "title": "Read source",
    "description": DESCRIPTION,
    "inputSchema": {
        "type": "object",
        "properties": {
            "source_id": {
                "type": "string",
                "description": "The id of one paper (like 2106.13008v5) or code repository (like Autoformer@09994619).",
            }
        },
        "required": ["source_id"],
        "additionalProperties": False,
    },
}


def tree_sha256(root: Path) -> str:
    """目录内容的哈希：按相对路径排序，逐个文件的 路径、NUL、内容 SHA-256（与题库 scripts/tasks.py 的算法相同）。"""
    digest = hashlib.sha256()
    for f in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(f"{f.relative_to(root).as_posix()}\0".encode() + hashlib.sha256(f.read_bytes()).digest())
    return digest.hexdigest()


def line_count(data: bytes) -> int | str:
    """文件的行数，与系统读锚点时相同（UTF-8 解码后 ``splitlines``：末行没有换行也算一行）；不是 UTF-8 文本时为 ``-``。"""
    try:
        return len(data.decode("utf-8").splitlines())
    except UnicodeDecodeError:
        return "-"


class Sources:
    """一个会话的来源：可取的 ID、语料位置与本会话的落盘目录。"""

    def __init__(self, library: Path, opened: list[str], dest: Path, alias: str, log: Path | None, session: str,
                 papers: Path | None = None, code: Path | None = None) -> None:  # fmt: skip
        self.library, self.opened = library, set(opened)
        self.papers, self.code = papers or library, code or library
        self.dest, self.alias, self.log, self.session = dest, alias.rstrip("/"), log, session

    def resolve(self, given: str) -> tuple[str | None, str]:
        """写者给的 ID → (来源 ID, 说明)；不能给出时来源 ID 为 ``None``，说明是返回给写者的话，原因另记。"""
        text = given.strip()
        if not text:
            return None, FORMAT
        if text.lower().startswith("arxiv:") or "/" in text or "::" in text or " " in text:
            return None, FORMAT
        if NUMBER.fullmatch(text):
            versions = [s for s in self.opened if PAPER.fullmatch(s) and s.rpartition("v")[0] == text]
            if not versions:
                return None, "not opened or not in the corpus"
            return max(versions, key=lambda s: int(s.rpartition("v")[2])), "latest available version"
        if not (PAPER.fullmatch(text) or CODE.fullmatch(text)):
            return None, FORMAT
        if text not in self.opened:
            exists = (self.papers / text / "paper.md").is_file() or (self.code / text).is_dir()
            return None, "not opened yet" if exists else "not in the corpus"
        if not (self.library / text).exists():  # 开放了却不在来源目录中：运行器的错，不是写者的
            return None, "opened but missing from the library"
        return text, ""

    def fetch(self, given: Any) -> tuple[dict[str, Any], bool]:
        """一次请求：返回 (结果, 是否出错)，并记一行（交付的记下内容哈希：论文为文件，代码为目录哈希）。"""
        record: dict[str, Any] = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "session": self.session, "requested": given}
        result: dict[str, Any]
        if not isinstance(given, str):
            result, error = {"error": FORMAT}, True
            record |= {"outcome": "format"}
        else:
            source, why = self.resolve(given)
            if source is None:
                shown = FORMAT if why == FORMAT else REFUSED
                result, error = {"error": shown}, True
                record |= {"outcome": "format" if why == FORMAT else "refused", "reason": why}
            else:
                result, copied, digest = (self._paper if PAPER.fullmatch(source) else self._code)(source)
                error = False
                record |= {"resolved": source, "outcome": "reused" if result["reused"] else "delivered", "bytes": copied,
                           "sha256": digest}  # fmt: skip
                if why:
                    record["note"] = why
        self._log(record)
        return result, error

    def _paper(self, source: str) -> tuple[dict[str, Any], int, str]:
        origin = self.library / source / "paper.md"
        target = self.dest / source / "paper.md"
        reused = target.exists()
        copied = 0
        if not reused:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(origin, target)
            copied = target.stat().st_size
            _read_only(target.parent)
        data = origin.read_bytes()
        out = {
            "source_id": source,
            "kind": "paper",
            "path": f"{self.alias}/{source}/paper.md",
            "lines": len(data.decode("utf-8").splitlines()),
            "sha256": hashlib.sha256(data).hexdigest(),
            "reused": reused,
        }
        if reused:
            out["intact"] = hashlib.sha256(target.read_bytes()).hexdigest() == out["sha256"]
        return out, copied, out["sha256"]

    def _code(self, source: str) -> tuple[dict[str, Any], int, str]:
        origin = self.library / source
        target = self.dest / source
        manifest = self.dest / f"{source}.files.tsv"
        reused = target.exists()
        copied = 0
        files = sorted(p for p in origin.rglob("*") if p.is_file())
        if not reused:
            shutil.copytree(origin, target, symlinks=False)
            rows = []
            for f in files:
                data = f.read_bytes()
                copied += len(data)
                rows.append(f"{f.relative_to(origin).as_posix()}\t{line_count(data)}\t{hashlib.sha256(data).hexdigest()}")
            manifest.write_text("path\tlines\tsha256\n" + "\n".join(rows) + "\n", encoding="utf-8")
            _read_only(target)
            manifest.chmod(0o444)
        out: dict[str, Any] = {
            "source_id": source,
            "kind": "code",
            "root": f"{self.alias}/{source}/",
            "files": len(files),
            "manifest": f"{self.alias}/{source}.files.tsv",
            "reused": reused,
        }
        tree = tree_sha256(origin)
        if reused:
            out["intact"] = tree_sha256(target) == tree
        return out, copied, tree  # 目录哈希只进记录，不返回给写者（返回字段照 B3）

    def _log(self, record: dict[str, Any]) -> None:
        if self.log is not None:
            with open(self.log, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _read_only(root: Path) -> None:
    """拷来的目录与文件只读（目录可进入、可列出）。"""
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        for name in filenames:
            os.chmod(os.path.join(dirpath, name), 0o444)
        os.chmod(dirpath, 0o555)


def handle(sources: Sources, msg: dict[str, Any]) -> dict[str, Any] | None:
    """一条 JSON-RPC 消息 → 回复；通知没有回复。"""
    method, msg_id = msg.get("method"), msg.get("id")
    if msg_id is None:
        return None
    if method == "initialize":
        asked = (msg.get("params") or {}).get("protocolVersion") or PROTOCOL
        result: dict[str, Any] = {
            "protocolVersion": asked,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "Sources", "version": "1"},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": [TOOL]}
    elif method == "tools/call":
        params = msg.get("params") or {}
        if params.get("name") != TOOL["name"]:
            return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32602, "message": f"unknown tool {params.get('name')}"}}
        arguments = params.get("arguments") or {}
        out, error = sources.fetch(arguments.get("source_id") if isinstance(arguments, dict) else None)
        result = {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}], "isError": error}
    else:
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def serve(sources: Sources, stdin=sys.stdin, stdout=sys.stdout) -> None:
    for line in stdin:
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            reply: dict[str, Any] | None = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            reply = handle(sources, msg) if isinstance(msg, dict) else None
        if reply is not None:
            stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            stdout.flush()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--library", type=Path, required=True, help="the arm's opened sources, verified by the runner")
    parser.add_argument("--papers", type=Path, help="the corpus papers, only to log why a request was refused")
    parser.add_argument("--code", type=Path, help="the corpus code, only to log why a request was refused")
    parser.add_argument("--opened", type=Path, required=True, help="JSON list of the source ids this session may fetch")
    parser.add_argument("--dest", type=Path, required=True)
    parser.add_argument("--alias", default="/work/sources")
    parser.add_argument("--log", type=Path)
    parser.add_argument("--session", default="")
    args = parser.parse_args(argv)
    opened = json.loads(args.opened.read_text(encoding="utf-8"))
    args.dest.mkdir(parents=True, exist_ok=True)
    serve(Sources(args.library, opened, args.dest, args.alias, args.log, args.session, args.papers, args.code))


if __name__ == "__main__":
    main()


__all__ = ["DESCRIPTION", "REFUSED", "TOOL", "Sources", "handle", "line_count", "main", "serve", "tree_sha256"]
