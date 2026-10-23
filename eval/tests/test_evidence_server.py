"""读者的 read_evidence（f3 设计 §6.2）：判断顺序、最小块、跨块交集、分页与 next、多条引用的“未读”、章节名、
大小上限、名单与来源的核对。"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from pweval.harness.evidence_server import DESCRIPTION, LIMIT, MAX_LINES, NO_LINES, Evidence, size
from pweval.protocol.allowlist import InputError, tree_sha256, write

P = "2205.13504v2"
Q = "2106.13008v5"  # 两个相邻的块
U = "2403.01673v1"  # 未开放
C = "repo@abcdef12"


def paper_lines() -> list[str]:
    """640 行：引言段 5–24，大表 28–627（600 行，没有空行），结尾段 631–640。"""
    lines = ["# Paper", "", "## Intro", ""]
    lines += [f"intro line {i}" for i in range(5, 25)]
    lines += ["", "## Big table", ""]
    lines += [f"| row {i} | " + "x" * 50 + " |" for i in range(28, 628)]
    lines += ["", "## Tail", ""]
    lines += [f"tail line {i}" for i in range(631, 641)]
    assert len(lines) == 640
    return lines


@pytest.fixture
def ev(tmp_path: Path) -> Evidence:
    library = tmp_path / "sources"
    texts = {P: "\n".join(paper_lines()) + "\n", Q: "".join(f"q {i}\n" for i in range(1, 11)),
             "2310.09751v3": "unused\n"}  # fmt: skip
    for source, text in texts.items():
        (library / source).mkdir(parents=True)
        (library / source / "paper.md").write_text(text)
    (library / C / "src").mkdir(parents=True)
    (library / C / "src/model.py").write_text("".join(f"# comment {i}\n" for i in range(1, 31)))
    (library / C / "src/big.py").write_text("short\n" + "a" * 10000 + "\nshort\n")
    opened = {s: hashlib.sha256(t.encode()).hexdigest() for s, t in texts.items()} | {C: tree_sha256(library / C)}
    passages = {P: [[5, 24], [10, 24], [28, 627], [631, 640]], Q: [[1, 5], [6, 10]],
                f"{C}::src/model.py": [[1, 12]], f"{C}::src/big.py": [[1, 3]]}  # fmt: skip
    readable = {P: [[5, 24], [28, 627], [631, 640]], Q: [[1, 10]], f"{C}::src/model.py": [[1, 12]],
                f"{C}::src/big.py": [[1, 3]]}  # fmt: skip
    result = {"arm": "A3", "checkpoint": 1, "version": "commit_000001", "rule": "test", "passages": passages,
              "readable": readable, "inputs": {"sources": opened}}  # fmt: skip
    path = write(result, tmp_path / "allowlists")
    return Evidence(path, library, tmp_path / "evidence.jsonl", "s1")


def one(ev: Evidence, ref: str) -> dict:
    items, text = ev.read([ref])
    assert len(text.encode()) <= LIMIT and yaml.safe_load(text) == items
    return items[0]


def lines_of(text: str) -> list[int]:
    return [int(line.split("|", 1)[0]) for line in text.splitlines()]


def returned(item: dict) -> list[int]:
    return lines_of(item["text"]) if "text" in item else [n for p in item["passages"] for n in lines_of(p["text"])]


def read_all(ev: Evidence, ref: str, readable: set[int]) -> list[dict]:
    """跟着 next 读到底：每个 next 都在原请求之内、起点尚未返回过；每页都有新行，新行整体向前推进；最后读全
    ``readable``（原请求中的可读行）。"""
    end = int(ref.rsplit(":", 1)[1])
    pages, seen = [], set()
    item = ev.read([ref])[0][0]
    while True:
        got = set(returned(item))
        new = got - seen
        assert new and (not seen or min(new) > max(seen & readable, default=0)), (item.get("next"), sorted(new)[:3])
        seen |= got
        pages.append(item)
        if "next" not in item:
            break
        start, stop = map(int, item["next"].rsplit("::", 1)[1].split(":"))
        assert start <= stop == end and start not in seen and start in readable
        item = ev.read([item["next"]])[0][0]
        assert len(pages) < 50
    assert readable <= seen
    return pages


# ---------------------------------------------------------------- 判断顺序


@pytest.mark.parametrize("ref", [f"{U}::1:5", "paper_0001::1:2", "2310.09751v3::1:1", "not a ref", f"{U}"])
def test_sources_without_readable_ranges_are_refused_alike(ev: Evidence, ref: str) -> None:
    assert one(ev, ref) == {"ref": ref, "status": "refused", "reason": NO_LINES, "readable": []}


def test_known_sources_tell_missing_lines_from_outside_and_list_what_can_be_read(ev: Evidence) -> None:
    listing = ["5:24", "28:627", "631:640"]
    assert one(ev, P) == {"ref": P, "status": "refused", "reason": "give lines: <source id>::<start>:<end>",
                          "readable": listing}  # fmt: skip
    assert one(ev, f"{P}::Intro")["reason"].startswith("give lines")  # 只到章节
    assert one(ev, f"{P}::1:3") | {"readable": None} == {"ref": f"{P}::1:3", "status": "refused",
                                                          "reason": "these lines are outside the readable ranges",
                                                          "readable": None}  # fmt: skip
    assert one(ev, f"{P}::25:27")["readable"] == listing  # 落在两块之间的空行
    assert one(ev, f"{P}::9:3")["reason"].startswith("write it as")  # 起大于止
    # 代码：列出各文件能读的行段；只到文件按“没写行号”；没有放行的文件按“范围外”
    code = one(ev, f"{C}::src/model.py")
    assert code["reason"].startswith("give lines") and code["readable"] == ["src/big.py::1:3", "src/model.py::1:12"]
    assert one(ev, f"{C}::src/other.py::1:2")["reason"] == "these lines are outside the readable ranges"


# ---------------------------------------------------------------- 单块与跨块


def test_a_contained_request_gets_the_smallest_whole_block(ev: Evidence) -> None:
    small = one(ev, f"{P}::12:14")
    assert (small["status"], small["passage"], small["section"]) == ("available", "10:24", "Intro")
    assert lines_of(small["text"]) == list(range(10, 25)) and "lines" not in small
    assert one(ev, f"{P}::6:14")["passage"] == "5:24"  # 只有大的那块完整包含它
    assert one(ev, f"{P}::Wrong hint::6:14")["section"] == "Intro"  # 引用中的章节提示不作为返回的章节名


def test_a_request_across_blocks_returns_the_intersection(ev: Evidence) -> None:
    item = one(ev, f"{P}::20:30")
    assert item["status"] == "partial"
    assert item["returned"] == ["20:24", "28:30"] and item["unavailable"] == ["25:27"]
    assert item["reason"] == "Only lines 20:24 and 28:30 are returned; lines 25:27 are outside the readable ranges."
    assert [(p["lines"], p["section"]) for p in item["passages"]] == [("20:24", "Intro"), ("28:30", "Big table")]
    assert lines_of(item["passages"][1]["text"]) == [28, 29, 30]  # 不扩到整张表
    assert "next" not in item
    # 跨两个相邻的块、中间没有不可读的行：全部返回
    adjacent = one(ev, f"{Q}::3:8")
    assert adjacent["status"] == "available" and adjacent["returned"] == ["3:8"] and "unavailable" not in adjacent
    assert "section" not in adjacent["passages"][0]  # 没有标题
    # 起点在可读范围之前
    early = one(ev, f"{P}::1:6")
    assert early["returned"] == ["5:6"] and early["unavailable"] == ["1:4"]


# ---------------------------------------------------------------- 分页与大小


def test_an_oversized_block_gives_the_requested_lines_only(ev: Evidence) -> None:
    item = one(ev, f"{P}::30:32")
    assert item["status"] == "available" and item["passage"] == "28:627" and item["lines"] == "30:32"
    assert lines_of(item["text"]) == [30, 31, 32]


def test_paging_continues_from_the_first_line_not_returned(ev: Evidence) -> None:
    first = one(ev, f"{P}::28:627")
    assert first["status"] == "partial" and first["passage"] == "28:627"
    got = lines_of(first["text"])
    assert got[0] == 28 and len(got) < MAX_LINES  # 先撞上字节上限
    assert first["next"] == f"{P}::{got[-1] + 1}:627"
    second = one(ev, first["next"])
    assert lines_of(second["text"])[0] == got[-1] + 1  # 不从块的开头重来
    assert second["passage"] == "28:627"
    pages = read_all(ev, f"{P}::28:627", set(range(28, 628)))
    assert all(p["passage"] == "28:627" for p in pages)
    across = read_all(ev, f"{P}::20:640", set(range(20, 25)) | set(range(28, 628)) | set(range(631, 641)))
    # 每页如实列出它自己的请求中不可读的缺口（续读的引用从表中开始，只剩 628:630）
    assert across[0]["unavailable"] == ["25:27", "628:630"]
    assert all(p["unavailable"] == ["628:630"] for p in across[1:])


def test_a_block_that_does_not_fit_this_reply_gives_the_request_not_the_block(ev: Evidence, monkeypatch) -> None:
    """块本身不超限、但本次回复放不下时，也只交付请求的子区间：next 总在原请求之内（不会出现 16:14 这样的引用），
    请求的行全部返回时就是 available。"""
    import pweval.harness.evidence_server as server

    whole = size([one(ev, f"{P}::12:14")])
    monkeypatch.setattr(server, "LIMIT", whole - 1)
    item = ev.read([f"{P}::12:14"])[0][0]
    assert (item["status"], item["passage"], item["lines"]) == ("available", "10:24", "12:14") and "next" not in item
    narrow = ev.plan(f"{P}::12:20").narrow()
    monkeypatch.setattr(server, "LIMIT", size([narrow.render(2)]))  # 放得下两行一页，放不下整段 12:20
    assert size([narrow.render(narrow.total)]) > server.LIMIT
    pages = read_all(ev, f"{P}::12:20", set(range(12, 21)))
    assert pages[0]["status"] == "partial" and pages[0]["passage"] == "10:24"
    assert all(size([p]) <= server.LIMIT for p in pages)
    monkeypatch.setattr(server, "LIMIT", size([narrow.render(1)]) - 1)  # 一行也放不下：整条未读，不硬塞一行
    assert ev.read([f"{P}::12:20"])[0][0]["status"] == "not read"


def test_the_line_cap_holds_even_when_bytes_would_allow(ev: Evidence, monkeypatch) -> None:
    import pweval.harness.evidence_server as server

    monkeypatch.setattr(server, "LIMIT", 10**7)
    item = ev.read([f"{P}::28:627"])[0][0]
    assert len(lines_of(item["text"])) == MAX_LINES and item["next"] == f"{P}::{28 + MAX_LINES}:627"


def test_next_skips_unreadable_gaps(ev: Evidence) -> None:
    plan = ev.plan(f"{P}::20:30")
    item = plan.render(5)  # 正好交付完 20–24
    assert item["returned"] == ["20:24"] and item["next"] == f"{P}::28:30"
    assert "did not fit" in item["reason"] and "25:27 are outside" in item["reason"]


def test_later_references_that_do_not_fit_are_not_read(ev: Evidence) -> None:
    items, text = ev.read([f"{P}::28:627", f"{P}::5:24"])
    assert items[0]["status"] == "partial" and items[1] == {"ref": f"{P}::5:24", "status": "not read",
                                                             "reason": "this reply is full; request it again"}  # fmt: skip
    assert len(text.encode()) <= LIMIT
    items, _ = ev.read([f"{P}::5:24", f"{P}::28:627"])  # 先交付了一条：后面的大块不截断，整条未读
    assert items[0]["status"] == "available" and items[1]["status"] == "not read"
    items, _ = ev.read([f"{P}::5:24", f"{Q}::1:2", f"{U}::1:1"])  # 都放得下
    assert [i["status"] for i in items] == ["available", "available", "refused"]


def test_a_later_reference_over_the_line_cap_is_not_read(ev: Evidence, monkeypatch) -> None:
    """之后的引用要么整条交付，要么整条未读：超过 400 行时即使字节放得下也不分页、不给 next。"""
    import pweval.harness.evidence_server as server

    monkeypatch.setattr(server, "LIMIT", 10**7)
    items, _ = ev.read([f"{Q}::1:2", f"{P}::28:627"])
    assert items[0]["status"] == "available" and items[1]["status"] == "not read" and "next" not in items[1]
    items, _ = ev.read([f"{U}::1:1", f"{P}::28:627"])  # 前面只有拒绝：它仍是第一条交付正文的引用，可以分页
    assert items[1]["status"] == "partial" and items[1]["next"] == f"{P}::{28 + MAX_LINES}:627"


def test_references_too_long_to_list_fail_the_call(ev: Evidence, tmp_path: Path) -> None:
    """全部记为未读也超过上限时整次调用报错（50 条约 300 字的引用），不返回超限的回复。"""
    refs = [f"{P}::{'4.2 Results ' * 24}::{i}:{i}" for i in range(5, 55)]
    text, error = ev.call({"refs": refs})
    assert error and text.startswith("error: these 50 references do not fit in one reply") and len(text) < 300
    last = json.loads((tmp_path / "evidence.jsonl").read_text().splitlines()[-1])
    assert last["error"] and "items" not in last


def test_no_reply_exceeds_the_limit_and_only_the_first_text_reference_pages(ev: Evidence) -> None:
    import random

    pool = [f"{P}::28:627", f"{P}::5:24", f"{P}::20:640", f"{P}::12:14", f"{Q}::1:10", f"{U}::1:1", f"{P}",
            f"{P}::700:710", f"{C}::src/model.py::2:3", f"{C}::src/big.py::2:2", f"{P}::{'x ' * 140}::30:31"]  # fmt: skip
    rng = random.Random(0)
    for _ in range(60):
        refs = [rng.choice(pool) for _ in range(rng.randint(1, 50))]
        text, error = ev.call({"refs": refs})
        assert len(text.encode()) <= LIMIT
        if error:
            continue
        items = yaml.safe_load(text)
        assert len(items) == len(refs)
        texts = [i for i, it in enumerate(items) if "text" in it or "passages" in it]
        assert all("next" not in items[i] for i in texts[1:])  # 只有第一条交付正文的引用可以分页


def test_metadata_is_counted_in_the_limit(ev: Evidence) -> None:
    refs = [f"{P}::28:627"] + [f"{U}::{i}:{i}" for i in range(1, 40)]
    items, text = ev.read(refs)
    assert len(text.encode()) <= LIMIT and size(items) == len(text.encode())
    assert len(items) == 40


def test_code_has_no_section(ev: Evidence) -> None:
    code = one(ev, f"{C}::./src/model.py::2:3")
    assert code["passage"] == "1:12" and "section" not in code  # # 注释不当标题；./ 前缀可以


def test_a_cut_line_makes_the_reference_partial_and_says_the_rest_cannot_be_read(ev: Evidence) -> None:
    big = one(ev, f"{C}::src/big.py::2:2")
    assert big["status"] == "partial" and big["cut"] == [{"line": 2, "bytes": 10000}]
    assert big["reason"] == ("line 2 (10000 bytes) is cut to the first 4000 bytes; the rest of it cannot be read "
                             "through this tool.")  # fmt: skip
    assert "next" not in big  # 余下部分没有续读的办法，不给 next
    whole = one(ev, f"{C}::src/big.py::1:1")  # 请求的行没被截断，但返回的整块含截断行：同样 partial 并标出
    assert whole["status"] == "partial" and whole["passage"] == "1:3" and whole["cut"] == [{"line": 2, "bytes": 10000}]


# ---------------------------------------------------------------- 核对与服务


def test_the_allowlist_and_the_sources_are_verified(ev: Evidence, tmp_path: Path) -> None:
    path = tmp_path / "allowlists/A3/k1.json"
    path.write_text(path.read_text().replace('"test"', '"other"'))
    with pytest.raises(ValueError, match="sha256"):
        Evidence(path, tmp_path / "sources")
    path.write_text(path.read_text().replace('"other"', '"test"'))
    (tmp_path / "sources" / Q / "paper.md").write_text("changed\n")
    with pytest.raises(InputError, match="sha256"):
        Evidence(path, tmp_path / "sources")


def test_calls_accept_json_strings_log_and_cap_the_count(ev: Evidence, tmp_path: Path) -> None:
    text, error = ev.call({"refs": json.dumps([f"{Q}::1:2"])})
    assert not error and yaml.safe_load(text)[0]["status"] == "available"
    text, error = ev.call({"refs": [f"{U}::1:1"] * 51})
    assert error and "at most 50" in text
    records = [json.loads(line) for line in (tmp_path / "evidence.jsonl").read_text().splitlines()]
    assert records[0]["items"][0]["status"] == "available" and records[0]["bytes"] > 0 and records[1]["error"]
    assert records[0]["session"] == "s1" and len(records[0]["allowlist"]) == 64


def test_the_stdio_server_answers_mcp(ev: Evidence, tmp_path: Path) -> None:
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "read_evidence", "arguments": {"refs": [f"{P}::12:14"]}}}]  # fmt: skip
    out = subprocess.run(
        [sys.executable, "-m", "pweval.harness.evidence_server", "--allowlist", str(tmp_path / "allowlists/A3/k1.json"),
         "--library", str(tmp_path / "sources")],
        input="".join(json.dumps(m) + "\n" for m in msgs), capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    replies = [json.loads(line) for line in out.splitlines()]
    assert replies[0]["result"]["serverInfo"]["name"] == "Evidence"
    (tool,) = replies[1]["result"]["tools"]
    assert tool["name"] == "read_evidence" and tool["description"] == DESCRIPTION
    assert list(tool["inputSchema"]["properties"]) == ["refs"]
    assert tool["inputSchema"]["properties"]["refs"]["maxItems"] == 50
    assert tool["inputSchema"]["properties"]["refs"]["description"] == "List of references <source id>::<start>:<end>."
    assert yaml.safe_load(replies[2]["result"]["content"][0]["text"])[0]["passage"] == "10:24"


def test_a_continuation_inside_a_nested_block_returns_that_whole_block(ev: Evidence, monkeypatch) -> None:
    """续读的引用也按第 3 步取最小完整块：它落在嵌套的小块里时，从小块的开头返回，前面几行重复；但每页的新行都向前
    推进，读得完（真实名单中 A3 k30 有 2 处：8 行与 34 行重复）。"""
    import pweval.harness.evidence_server as server

    monkeypatch.setattr(server, "LIMIT", 400)
    pages = read_all(ev, f"{P}::5:24", set(range(5, 25)))
    assert pages[0]["passage"] == "5:24" and pages[0]["status"] == "partial"
    assert pages[-1]["passage"] == "10:24"
