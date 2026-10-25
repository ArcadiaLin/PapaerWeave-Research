"""A4 的 Graphiti MCP 服务（eval/baselines/a4/serve.py）相对官方服务的改动（f3 设计第 5 节）：不列出 clear_graph，加按 UUID
取 episode 原文的 get_episodes_by_uuid，读者不隐藏它。

服务在 Graphiti 自己的 Python 环境中运行（serve.py 文档串），所以这里用那个环境的 python 跑子进程；本机没有这个环境时跳过。
Neo4j 用替身：替换 EpisodicNode.get_by_uuids，不连库。
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from pweval.harness.timeline import A4_WRITE_TOOLS

ROOT = Path(__file__).resolve().parents[2]
SERVE = ROOT / "eval/baselines/a4/serve.py"
PYTHON = Path(os.environ.get("GRAPHITI_ENV", ROOT / "tmps/pilot/graphiti/.venv")) / "bin/python"

pytestmark = pytest.mark.skipif(not PYTHON.exists(), reason="Graphiti 的 Python 环境不在本机")

SCRIPT = """
import asyncio, json, runpy, sys
from datetime import datetime, timezone
from types import SimpleNamespace
sys.argv = ["serve.py"]
serve = runpy.run_path(%(serve)r, run_name="test")
server = sys.modules["graphiti_mcp_server"]
from graphiti_core.nodes import EpisodeType, EpisodicNode

def episode(uuid, group):
    return EpisodicNode(uuid=uuid, name=f"name {uuid}", group_id=group, source=EpisodeType.text,
                        source_description="seed", content=f"body of {uuid} [2205.13504v2::1:2]",
                        valid_at=datetime(2026, 10, 23, tzinfo=timezone.utc), created_at=datetime(2026, 10, 23, tzinfo=timezone.utc))

STORE = {"a": episode("a", "formal"), "b": episode("b", "formal"), "x": episode("x", "other")}
asked = []

async def get_by_uuids(cls, driver, uuids):
    asked.append(list(uuids))
    return [STORE[u] for u in uuids if u in STORE]

EpisodicNode.get_by_uuids = classmethod(get_by_uuids)

class Service:
    async def get_client(self):
        return SimpleNamespace(driver=SimpleNamespace(clone=lambda database: None))

async def main():
    out = {"tools": sorted(t.name for t in await server.mcp.list_tools())}
    out["uninitialized"] = await serve["get_episodes_by_uuid"](["a"])
    server.graphiti_service = Service()
    server.config = SimpleNamespace(graphiti=SimpleNamespace(group_id="formal"))
    server._driver_for_group = lambda client, group: client.driver
    reply = await server.mcp.call_tool("get_episodes_by_uuid", {"episode_uuids": ["b", "nope", "a", "b", "x"]})
    out["reply"] = json.loads(reply.content[0].text)
    out["other"] = await serve["get_episodes_by_uuid"](["x"], group_id="other")
    out["empty"] = await serve["get_episodes_by_uuid"]([])
    out["asked"] = asked
    print(json.dumps(out))

asyncio.run(main())
""" % {"serve": str(SERVE)}


@pytest.fixture(scope="module")
def result() -> dict:
    done = subprocess.run([str(PYTHON), "-I", "-c", SCRIPT], capture_output=True, text=True, timeout=120, check=False)
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_tools_drop_clear_graph_and_add_episode_text(result: dict) -> None:
    assert "clear_graph" not in result["tools"]
    assert "get_episodes_by_uuid" in result["tools"]
    assert {"add_memory", "search_memory_facts", "get_episodes", "get_episode_entities"} <= set(result["tools"])


def test_readers_keep_the_new_tool() -> None:
    """新工具只读，读者能用；隐藏的只有写入与删除（设计第 6.1 节的读者工具表）。"""
    assert "mcp__Graphiti__get_episodes_by_uuid" not in A4_WRITE_TOOLS


def test_episodes_come_back_in_request_order_with_missing_listed(result: dict) -> None:
    reply = result["reply"]
    assert [e["uuid"] for e in reply["episodes"]] == ["b", "a"]  # 去重，按请求顺序；别的组的不返回
    assert reply["episodes"][0] == {
        "uuid": "b", "name": "name b", "content": "body of b [2205.13504v2::1:2]", "created_at": "2026-10-23T00:00:00+00:00",
        "source": "text", "source_description": "seed", "group_id": "formal",
    }  # fmt: skip  与官方 get_episodes 的字段相同
    assert reply["message"] == "Retrieved 2 of 4 episode(s); not found: nope, x"
    assert result["asked"][0] == ["b", "nope", "a", "b", "x"]


def test_group_and_errors(result: dict) -> None:
    assert [e["uuid"] for e in result["other"]["episodes"]] == ["x"]
    assert result["empty"] == {"error": "episode_uuids must contain at least one UUID"}
    assert result["uninitialized"] == {"error": "Graphiti service not initialized"}


# ---------------------------------------------------------------- 读者模式（--read-only，10-25）

READ_ONLY = """
import asyncio, io, json, logging, runpy, sys
from types import SimpleNamespace
sys.argv = ["serve.py"]
serve = runpy.run_path(%(serve)r, run_name="test")
server = sys.modules["graphiti_mcp_server"]
log = io.StringIO()
logging.getLogger("pilot.usage").addHandler(logging.StreamHandler(log))
serve["read_only"]()
from graphiti_core.graph_queries import get_fulltext_indices, get_range_indices
from graphiti_core.driver.driver import GraphProvider
from graphiti_core.graphiti import Graphiti
from openai import AsyncOpenAI

def fake(states):
    async def execute_query(query, **kwargs):
        assert query == "SHOW INDEXES YIELD name, state"
        return [{"name": n, "state": s} for n, s in states.items()], None, None
    return SimpleNamespace(driver=SimpleNamespace(execute_query=execute_query))

async def main():
    out = {"tools": sorted(t.name for t in await server.mcp.list_tools())}
    client = AsyncOpenAI(api_key="x", base_url="http://127.0.0.1:9/v1")
    out["llm"] = []
    for call in (lambda: client.chat.completions.create(model="m", messages=[]),
                 lambda: client.chat.completions.parse(model="m", messages=[]),
                 lambda: client.responses.create(model="m", input="x"),
                 lambda: client.responses.parse(model="m", input="x")):
        try:
            await call()
            out["llm"].append("called")
        except Exception as e:
            out["llm"].append(f"{type(e).__name__}: {e}")
    for stream in (lambda: client.chat.completions.stream(model="m", messages=[]),
                   lambda: client.responses.stream(model="m", input="x")):
        try:
            async with stream() as s:  # SDK 的正常用法
                out["llm"].append("streamed")
        except Exception as e:
            out["llm"].append(f"{type(e).__name__}: {e}")
    names = [q.split()[2] if "FULLTEXT" not in q else q.split()[3] for q in
             get_range_indices(GraphProvider.NEO4J) + get_fulltext_indices(GraphProvider.NEO4J)]
    online = {n: "ONLINE" for n in names} | {"index_extra": "ONLINE"}
    await Graphiti.build_indices_and_constraints(fake(online))
    out["missing"] = out["populating"] = None
    for key, states in (("missing", {n: s for n, s in online.items() if n != "episode_content"}),
                        ("populating", online | {"entity_uuid": "POPULATING"})):
        try:
            await Graphiti.build_indices_and_constraints(fake(states))
        except RuntimeError as e:
            out[key] = str(e)
    out["expected"] = len(names)
    out["log"] = log.getvalue()
    print(json.dumps(out))

asyncio.run(main())
""" % {"serve": str(SERVE)}


@pytest.fixture(scope="module")
def read_only() -> dict:
    done = subprocess.run([str(PYTHON), "-I", "-c", READ_ONLY], capture_output=True, text=True, timeout=120, check=False)
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_read_only_lists_exactly_the_readers_tools(read_only: dict) -> None:
    """读者模式的工具表就是读者运行器预期的（store_readers.A4_TOOLS），撤掉的正是 timeline.A4_WRITE_TOOLS。"""
    from pweval.harness.store_readers import A4_TOOLS

    assert set(read_only["tools"]) == A4_TOOLS["Graphiti"]
    assert {f"mcp__Graphiti__{t}" for t in A4_TOOLS["Graphiti"]}.isdisjoint(A4_WRITE_TOOLS)


def test_read_only_blocks_the_internal_llm_and_logs_every_attempt(read_only: dict) -> None:
    from pweval.harness.store_readers import A4_BLOCKED

    assert len(read_only["llm"]) == 6  # create、parse 与 async with stream()，对话与 responses 两个入口
    assert all(r.startswith("RuntimeError: ") and "is blocked" in r for r in read_only["llm"]), read_only["llm"]
    assert read_only["log"].count(A4_BLOCKED) == 6  # 每次尝试各记一行，读者运行器核对为零
    for name in ("chat.completions.stream", "responses.stream", "chat.completions.parse", "responses.create"):
        assert f"{A4_BLOCKED}: {name}" in read_only["log"]


def test_read_only_checks_the_restored_indexes_instead_of_building_them(read_only: dict) -> None:
    from pweval.harness.store_readers import A4_INDEXES

    assert read_only["expected"] == 31  # graphiti-core 0.31.1 对 Neo4j 建的 27 个范围索引与 4 个全文索引
    assert A4_INDEXES.search(read_only["log"])[1] == "31"
    assert "episode_content" in read_only["missing"] and "entity_uuid" in read_only["populating"]
