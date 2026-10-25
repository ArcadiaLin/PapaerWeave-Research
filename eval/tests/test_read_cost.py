import json

from pweval.measure.read_cost import allocate, bash_category, parse, rows, tool_name, Session


def test_bash_category():
    assert bash_category("grep -rl x /work/store | head") == "bash:search"
    assert bash_category("cd /work/store/nodes && for f in *.yaml; do head -12 $f; done") == "bash:read"
    assert bash_category("ls /work/store/artifacts/ | wc -l") == "bash:list"
    assert bash_category("LC_ALL=C python3 - <<'EOF'\nprint(1)\nEOF") == "bash:script"
    assert bash_category("git log --oneline | head") == "bash:git"
    assert bash_category("echo hi") == "bash:other"


def test_tool_name():
    assert tool_name("mcp__PaperWeave__search") == "search"
    assert tool_name("mcp__Evidence__read_evidence") == "read_evidence"
    assert tool_name("bash") == "bash"


def _assistant(inp, cache, out, calls=()):
    content = [{"type": "toolCall", "id": i, "name": n, "arguments": {"command": "grep x"}} for i, n in calls]
    return {"type": "message_end", "message": {"role": "assistant", "content": content, "stopReason": "toolUse",
                                               "usage": {"input": inp, "cacheRead": cache, "output": out}}}


def _result(i, text):
    return {"type": "message_end", "message": {"role": "toolResult", "toolCallId": i, "toolName": "bash",
                                               "content": json.dumps([{"type": "text", "text": text}])}}


def test_parse_allocate_and_occupancy(tmp_path):
    events = [
        {"type": "message_end", "message": {"role": "user", "content": [{"type": "text", "text": "question"}]}},
        _assistant(100, 0, 10, [("a", "bash"), ("b", "mcp__Evidence__read_evidence")]),
        _result("a", "x" * 30),
        _result("b", "y" * 10),
        _assistant(20, 100, 5, [("c", "bash")]),  # 提示 120 = 100 + 10（输出）+ 10（两次返回）
        _result("c", "z" * 8),
        {"type": "compaction_end", "reason": "overflow", "aborted": False},
        _assistant(50, 0, 7),
    ]
    path = tmp_path / "events.jsonl"
    path.write_text("".join(json.dumps(e) + "\n" for e in events))
    trace = parse(path)
    assert [c.later for c in trace.calls] == [1, 0, 0]  # 第三次调用之前压缩过
    assert trace.compactions == 1 and trace.question_chars == len("question")
    assert allocate(trace) == (40, 10)
    assert [t.step_tokens for t in trace.tools] == [7.5, 2.5, None]
    record = {"probe": "p", "template": "T1", "seconds": 1, "stop": "stop"}
    _, tools, row = rows(Session("r", "A0", 10, record, trace), ratio=2.0)
    assert [(t["est_tokens"], t["token_source"]) for t in tools] == [(8, "step"), (2, "step"), (4, "ratio")]
    assert row["calls_before_evidence"] == 0
    assert row["prompt_total"] == 100 + 120 + 50
    assert row["occ_prefix"] == 100 * 3 and row["occ_output"] == 10 and row["occ_tools"] == 10
    assert row["occ_residual"] == 270 - 300 - 10 - 10
