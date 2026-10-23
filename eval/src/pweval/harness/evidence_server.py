"""读者的 ``read_evidence``：只读放行名单中的块（docs/experiments/f3/2026-10-22-f3-design.md §6.2、§6.3）。MCP stdio 服务，
四组（A0、A2、A3、A4）的服务名、工具说明与参数说明逐字相同。

    python -m pweval.harness.evidence_server --allowlist FILE --library DIR [--log FILE] [--session ID]

运行器为每个读者会话在沙箱外启动一次（经 :mod:`pweval.harness.bridge` 接入沙箱，与来源服务相同）：

- ``--allowlist``：该组该检查点归档的放行名单（:mod:`pweval.protocol.allowlist`），旁边的 ``.sha256`` 必须对得上；
- ``--library``：组的已开放来源目录；名单 ``inputs.sources`` 中的每个来源先按哈希核对，不符即不启动，不回退到别处；
- ``--log``：每次调用追加一行 JSON：请求、每条引用的结果、返回的行段与字节数。

**一条引用的判断顺序**（10-23 用户定）：

1. 来源在名单中没有可读范围（未开放、不存在、开放了但没有可读锚点，或不是来源 ID）：``refused``，
   ``no readable lines for this source id``，``readable: []``，不区分原因；
2. 有可读范围、但没写行号或写法不对：``refused``，列出该来源能读的行段（代码为 ``<文件>::<起>:<止>``）；
3. 有一个块完整包含所请求的行：返回包含它的最小块（整段或整张表），``available``；
4. 没有单块完整包含：返回请求与可读范围的交集，不额外扩出请求范围，逐段标出 ``returned`` 与 ``unavailable``；
   交集就是整个请求时 ``available``，只返回一部分时 ``partial``，交集为空时 ``refused``（列出能读的行段）。

**大小**：一条最多 ``MAX_LINES`` 行；整个回复按最终 YAML 的 UTF-8 字节数不超过 ``LIMIT``，状态与 ``next`` 等元数据
一并计入，后面还没轮到的引用也按“未读”预留位置。第 3 步的块本身超过限制时不扩块，只返回请求的子区间（``passage``
仍写整块的范围）。仍放不下时返回能放下的前段，``partial``，``next`` 是从第一条尚未返回的可读行起的引用（不可读的
缺口不作为续读位置）。一次请求多条引用时，只有本次第一条交付正文的引用可以这样截断；之后的引用放不下就整条
``not read``，不从中间截断。超过 ``LINE_MAX`` 字节的单行只返回前 ``LINE_MAX`` 字节：该条为 ``partial``，
``cut`` 列出被截断的行与原始字节数，并说明余下部分无法经这个工具读到（证据交付限制，单独记录；CATS 的 notebook 中有
一行约 1.2 MB）。

**章节名**：与系统 ``query/sections.py`` 同一规则（``#`` 到 ``######`` 的标题，取所在行或之前最近的一个，去掉标记），
按每段实际返回的第一行查；找不到就不给。代码不给章节（``#`` 是注释）。引用中写的章节提示只是输入，不作为返回的章节名。

**行的写法**：与系统 ``read_evidence`` 相同，``<行号>| <原文>``，去掉行尾空白。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import yaml

from ..protocol.allowlist import CODE_SOURCE, SOURCE_ID, Ref, Sources, normalize, parse

LIMIT = 16 * 1024  # 一次回复的 YAML 字节数上限，留在 pi 的 20 KiB 截断阈值以内（设计 §6.2）
MAX_LINES = 400  # 一条引用最多返回的行数（与系统 read_evidence 相同）
MAX_REFS = 50  # 一次调用最多的引用条数
LINE_MAX = 4000  # 单行的字节数上限，超过的截断
ECHO_MAX = 300  # 回显引用原文的字数上限

DESCRIPTION = (
    "Read the source lines that anchors recorded in the store point to. Write each reference as "
    "<source id>::<start>:<end>, such as 2205.13504v2::120:135 (a section in between, "
    "2205.13504v2::4.2 Results::120:135, is accepted and ignored); code is <repo>@<commit>::<file>::<start>:<end>. "
    "Only passages that a recorded anchor falls in can be read: any lines inside such a passage return the whole "
    "passage (a paragraph, or a whole table) with line numbers and the section it is in. A reference that runs past "
    "these passages returns only its readable lines and lists the lines that are not readable. A reference with no "
    "readable lines, or without lines, is refused with the line ranges of that source that can be read. A passage too "
    "long for one reply comes back in parts, with the reference to continue from; a reference that does not fit in "
    "this reply is marked not read, so request it again."
)
TOOL = {
    "name": "read_evidence",
    "title": "Read evidence",
    "description": DESCRIPTION,
    "inputSchema": {
        "type": "object",
        "properties": {
            "refs": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 50,
                "description": "List of references <source id>::<start>:<end>.",
            }
        },
        "required": ["refs"],
        "additionalProperties": False,
    },
}
PROTOCOL = "2025-06-18"

NO_LINES = "no readable lines for this source id"
GIVE_LINES = "give lines: <source id>::<start>:<end>"
FORMAT = "write it as <source id>::<start>:<end> (code: <repo>@<commit>::<file>::<start>:<end>)"
OUTSIDE = "these lines are outside the readable ranges"
NOT_READ = "this reply is full; request it again"
TOO_LONG = ("error: these {n} references do not fit in one reply even without any text ({size} bytes); "
            "send fewer or shorter references\n")  # fmt: skip
_HEADING = re.compile(r"#{1,6}\s+(?P<title>.+?)\s*#*\s*$")  # 同系统 query/sections.py


class _Dumper(yaml.SafeDumper):
    pass


def _str(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
    if "\n" in value:
        return dumper.represent_scalar("tag:yaml.org,2002:str", value, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", value)


def _list(dumper: yaml.SafeDumper, value: list[Any]) -> yaml.SequenceNode:
    flow = all(isinstance(v, str) for v in value) and sum(len(v) + 2 for v in value) < 80
    return dumper.represent_sequence("tag:yaml.org,2002:seq", value, flow_style=flow)


_Dumper.add_representer(str, _str)
_Dumper.add_representer(list, _list)


def dump(items: list[dict[str, Any]]) -> str:
    return yaml.dump(items, Dumper=_Dumper, allow_unicode=True, sort_keys=False, width=120)


def size(items: list[dict[str, Any]]) -> int:
    return len(dump(items).encode("utf-8"))


def span(a: int, b: int) -> str:
    return f"{a}:{b}"


def gaps(s: int, e: int, pieces: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """[s, e] 中不在 ``pieces``（有序、不重叠）里的行段。"""
    out, at = [], s
    for a, b in pieces:
        if a > at:
            out.append((at, a - 1))
        at = b + 1
    if at <= e:
        out.append((at, e))
    return out


class Plan:
    """一条可读引用要交付的行：``pieces`` 依次交付；``block`` 是第 3 步的块（交叉时为 ``None``）。"""

    def __init__(self, ref: str, head: str, parsed: Ref, lines: list[str], pieces: list[tuple[int, int]],
                 block: tuple[int, int] | None, sections: list[tuple[int, str]] | None) -> None:  # fmt: skip
        self.ref, self.head, self.parsed, self.lines = ref, head, parsed, lines
        self.pieces, self.block, self.sections = pieces, block, sections
        self.unavailable = [] if block else gaps(parsed.start, parsed.end, pieces)

    @property
    def total(self) -> int:
        return sum(b - a + 1 for a, b in self.pieces)

    def section(self, line: int) -> str | None:
        title = None
        for n, text in self.sections or ():
            if n > line:
                break
            title = text
        return title

    def text(self, a: int, b: int) -> str:
        return "\n".join(f"{n}| {_cut(self.lines[n - 1])}".rstrip() for n in range(a, b + 1)) + "\n"

    def narrow(self) -> Plan:
        """第 3 步的块在本次回复中放不下时，只交付请求的子区间（``passage`` 仍写整块）：续读的位置因此总在请求之内。"""
        return Plan(self.ref, self.head, self.parsed, self.lines, [(self.parsed.start, self.parsed.end)], self.block,
                    self.sections)  # fmt: skip

    def render(self, k: int) -> dict[str, Any]:
        """交付前 ``k`` 行（``k`` 不超过 :attr:`total`）的结果。"""
        sent: list[tuple[int, int]] = []
        left = k
        for a, b in self.pieces:
            if left <= 0:
                break
            take = min(b - a + 1, left)
            sent.append((a, a + take - 1))
            left -= take
        done = k >= self.total
        nxt = None
        if not done:  # 第一条尚未返回的可读行（不可读的缺口不作为续读位置）
            last = sent[-1][1] if sent else self.parsed.start - 1
            first = next(max(a, last + 1) for a, b in self.pieces if b > last)
            nxt = f"{self.parsed.key}::{span(first, self.parsed.end)}"
        cut = [(n, nbytes) for a, b in sent for n in range(a, b + 1)
               if (nbytes := len(self.lines[n - 1].encode("utf-8"))) > LINE_MAX]  # fmt: skip
        status = "available" if done and not self.unavailable and not cut else "partial"
        item: dict[str, Any] = {"ref": self.ref, "status": status}
        cut_note = (f"{_and([f'line {n} ({nbytes} bytes)' for n, nbytes in cut])} {'is' if len(cut) == 1 else 'are'} cut "
                    f"to the first {LINE_MAX} bytes; the rest of {'it' if len(cut) == 1 else 'them'} cannot be read "
                    "through this tool") if cut else None  # fmt: skip
        if self.block:
            a, b = sent[0]
            said = [f"Only lines {span(a, b)} are returned; the rest did not fit in this reply"] if not done else []
            if cut_note:
                said.append(cut_note)
            if said:
                item["reason"] = "; ".join(said) + "."
            item["passage"] = span(*self.block)
            if (a, b) != self.block:
                item["lines"] = span(a, b)
            if title := self.section(a):
                item["section"] = title
            item["text"] = self.text(a, b)
        else:
            if status == "partial":
                said = [f"Only lines {_and([span(*p) for p in sent])} are returned"]
                if self.unavailable:
                    said.append(f"lines {_and([span(*p) for p in self.unavailable])} are outside the readable ranges")
                if not done:
                    said.append("the rest of the readable lines did not fit in this reply")
                if cut_note:
                    said.append(cut_note)
                item["reason"] = "; ".join(said) + "."
            item["returned"] = [span(*p) for p in sent]
            if self.unavailable:
                item["unavailable"] = [span(*p) for p in self.unavailable]
            passages = []
            for a, b in sent:
                piece: dict[str, Any] = {"lines": span(a, b)}
                if title := self.section(a):
                    piece["section"] = title
                piece["text"] = self.text(a, b)
                passages.append(piece)
            item["passages"] = passages
        if cut:
            item["cut"] = [{"line": n, "bytes": nbytes} for n, nbytes in cut]
        if nxt:
            item["next"] = nxt
        return item


def _and(parts: list[str]) -> str:
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def _cut(line: str) -> str:
    data = line.encode("utf-8")
    if len(data) <= LINE_MAX:
        return line
    return data[:LINE_MAX].decode("utf-8", "ignore") + f" … [line cut: {len(data)} bytes]"


class Evidence:
    """一个读者会话的放行名单与来源。"""

    def __init__(self, allowlist: Path, library: Path, log: Path | None = None, session: str = "") -> None:
        data = allowlist.read_bytes()
        digest = allowlist.with_name(allowlist.name + ".sha256").read_text(encoding="utf-8").split()[0]
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError(f"{allowlist} does not match its .sha256")
        doc = json.loads(data)
        self.digest, self.log, self.session = digest, log, session
        self.meta = {"arm": doc["arm"], "checkpoint": doc["checkpoint"], "version": doc["version"], "rule": doc["rule"]}
        self.passages = {k: [tuple(x) for x in v] for k, v in doc["passages"].items()}
        self.readable = {k: [tuple(x) for x in v] for k, v in doc["readable"].items()}
        self.sources = Sources(library, doc["inputs"]["sources"])  # 逐个核对哈希，不符即停
        self._sections: dict[str, list[tuple[int, str]]] = {}

    def keys(self, head: str) -> list[str]:
        return sorted(k for k in self.readable if k == head or k.startswith(head + "::"))

    def listing(self, head: str) -> list[str]:
        """来源能读的行段：论文为 ``起:止``，代码为 ``<文件>::<起>:<止>``。"""
        out = []
        for key in self.keys(head):
            prefix = key[len(head) + 2:] + "::" if key != head else ""
            out += [f"{prefix}{span(a, b)}" for a, b in self.readable[key]]
        return out

    def plan(self, given: Any) -> Plan | dict[str, Any]:
        """一条引用 → :class:`Plan`，或最终的拒绝结果。"""
        ref = given if isinstance(given, str) else json.dumps(given, ensure_ascii=False)
        ref = ref.strip()
        ref = ref if len(ref) <= ECHO_MAX else ref[:ECHO_MAX] + "…"
        text = normalize(given) if isinstance(given, str) else ""
        head = text.partition("::")[0]
        if not SOURCE_ID.fullmatch(head) or not self.keys(head):
            return {"ref": ref, "status": "refused", "reason": NO_LINES, "readable": []}
        parsed = parse(given)
        if not isinstance(parsed, Ref) or parsed.start < 1 or parsed.start > parsed.end:
            reason = GIVE_LINES if parsed == "no-locator" else FORMAT
            return {"ref": ref, "status": "refused", "reason": reason, "readable": self.listing(head)}
        parsed = Ref(parsed.source, parsed.file.removeprefix("./") if parsed.file else None, parsed.start, parsed.end)
        key = parsed.key
        readable = self.readable.get(key, [])
        s, e = parsed.start, parsed.end
        containing = [(a, b) for a, b in self.passages.get(key, []) if a <= s and e <= b]
        pieces = [(max(s, a), min(e, b)) for a, b in readable if a <= e and b >= s]
        if not containing and not pieces:
            return {"ref": ref, "status": "refused", "reason": OUTSIDE, "readable": self.listing(head)}
        lines = self.sources.lines(parsed)
        if isinstance(lines, str):  # 名单与来源目录不一致：名单生成时核对过，这里不该发生
            raise RuntimeError(f"{key}: {lines}")
        sections = None if CODE_SOURCE.fullmatch(parsed.source) else self._headings(parsed.source, lines)
        if containing:
            block = min(containing, key=lambda x: (x[1] - x[0], x[0]))
            plan = Plan(ref, head, parsed, lines, [block], block, sections)
            whole = plan.render(plan.total)
            if plan.total > MAX_LINES or size([whole]) > LIMIT:  # 块本身超过限制：不扩块，只给请求的子区间
                plan = Plan(ref, head, parsed, lines, [(s, e)], block, sections)
            return plan
        return Plan(ref, head, parsed, lines, pieces, None, sections)

    def _headings(self, source: str, lines: list[str]) -> list[tuple[int, str]]:
        if source not in self._sections:
            out = []
            for n, line in enumerate(lines, 1):
                if m := _HEADING.fullmatch(line.strip()):
                    out.append((n, m["title"]))
            self._sections[source] = out
        return self._sections[source]

    def read(self, refs: list[Any]) -> tuple[list[dict[str, Any]], str]:
        """一次调用：（各条结果，回复的 YAML）。

        每一步都按“已定的结果 + 这一条 + 其后全部记为未读”的字节数判断，所以回复总在 ``LIMIT`` 之内；全部记为未读
        也放不下时（引用很多且很长）整次调用报错，见 :class:`TooLong`。只有本次第一条交付正文的引用可以分页（给
        ``next``）；之后的引用要么整条交付，要么整条未读。"""
        plans = [self.plan(r) for r in refs]
        echo = [p["ref"] if isinstance(p, dict) else p.ref for p in plans]
        if (floor := size([_not_read(r) for r in echo])) > LIMIT:
            raise TooLong(TOO_LONG.format(n=len(refs), size=floor))
        items: list[dict[str, Any]] = []
        started = False  # 本次已有引用交付正文：之后的放不下就整条未读
        for i, plan in enumerate(plans):
            rest = [_not_read(r) for r in echo[i + 1:]]

            def fits(item: dict[str, Any], rest: list[dict[str, Any]] = rest) -> bool:
                return size([*items, item, *rest]) <= LIMIT

            if isinstance(plan, dict):
                items.append(plan if fits(plan) else _not_read(plan["ref"]))
                continue
            # 先试整块；整块放不下时只交付请求的子区间（不分页整块，续读位置才总在请求之内）
            tries = [plan, *([plan.narrow()] if plan.block and plan.pieces == [plan.block] else [])]
            chosen = None
            for p in tries:
                item = p.render(min(p.total, MAX_LINES))
                if fits(item) and not (started and "next" in item):
                    chosen = item
                    break
            if chosen is None and not started:  # 第一条交付正文的引用：放得下多少行就交付多少行，给 next
                last = tries[-1]
                lo, hi = 0, min(last.total, MAX_LINES)
                while lo < hi:
                    mid = (lo + hi + 1) // 2
                    if fits(last.render(mid)):
                        lo = mid
                    else:
                        hi = mid - 1
                chosen = last.render(lo) if lo else None  # 一行也放不下（前面的拒绝占了位置）：整条未读
            if chosen is None:
                items.append(_not_read(plan.ref))
                continue
            items.append(chosen)
            started = True
        return items, dump(items)

    def call(self, arguments: Any) -> tuple[str, bool]:
        """一次 tools/call：（回复正文，是否出错），并记一行。"""
        refs = arguments.get("refs") if isinstance(arguments, dict) else None
        if isinstance(refs, str):  # sglang 有时把数组参数作为 JSON 字符串传来
            try:
                refs = json.loads(refs)
            except json.JSONDecodeError:
                refs = [refs]
        record: dict[str, Any] = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "session": self.session,
                                  "allowlist": self.digest, "refs": refs}  # fmt: skip
        if not isinstance(refs, list) or not refs:
            text, error = "error: refs is a list of references <source id>::<start>:<end>\n", True
        elif len(refs) > MAX_REFS:
            text, error = f"error: at most {MAX_REFS} references per call\n", True
        else:
            try:
                items, text = self.read(refs)
                error = False
                record["items"] = [_summary(it) for it in items]
            except TooLong as exc:
                text, error = str(exc), True
        record |= {"error": error, "bytes": len(text.encode("utf-8"))}
        if self.log is not None:
            with open(self.log, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return text, error


class TooLong(Exception):
    """全部引用都记为未读，回复也超过 ``LIMIT``：整次调用报错，不返回超限的回复。"""


def _not_read(ref: str) -> dict[str, Any]:
    return {"ref": ref, "status": "not read", "reason": NOT_READ}


def _summary(item: dict[str, Any]) -> dict[str, Any]:
    keys = ("ref", "status", "reason", "passage", "lines", "returned", "unavailable", "cut", "next")
    out = {k: item[k] for k in keys if k in item}
    out["bytes"] = len(dump([item]).encode("utf-8"))
    return out


def handle(evidence: Evidence, msg: dict[str, Any]) -> dict[str, Any] | None:
    """一条 JSON-RPC 消息 → 回复；通知没有回复。"""
    method, msg_id = msg.get("method"), msg.get("id")
    if msg_id is None:
        return None
    if method == "initialize":
        asked = (msg.get("params") or {}).get("protocolVersion") or PROTOCOL
        result: dict[str, Any] = {
            "protocolVersion": asked,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "Evidence", "version": "1"},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": [TOOL]}
    elif method == "tools/call":
        params = msg.get("params") or {}
        if params.get("name") != TOOL["name"]:
            return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32602, "message": f"unknown tool {params.get('name')}"}}
        text, error = evidence.call(params.get("arguments") or {})
        result = {"content": [{"type": "text", "text": text}], "isError": error}
    else:
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def serve(evidence: Evidence, stdin=sys.stdin, stdout=sys.stdout) -> None:
    for line in stdin:
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            reply: dict[str, Any] | None = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            reply = handle(evidence, msg) if isinstance(msg, dict) else None
        if reply is not None:
            stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            stdout.flush()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--allowlist", type=Path, required=True, help="the archived allowlist of this arm and checkpoint")
    parser.add_argument("--library", type=Path, required=True, help="the arm's opened sources")
    parser.add_argument("--log", type=Path)
    parser.add_argument("--session", default="")
    args = parser.parse_args(argv)
    serve(Evidence(args.allowlist, args.library, args.log, args.session))


if __name__ == "__main__":
    main()


__all__ = ["DESCRIPTION", "LIMIT", "MAX_LINES", "TOOL", "Evidence", "handle", "main", "serve"]
