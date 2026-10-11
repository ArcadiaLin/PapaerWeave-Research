"""MCP 入口与实验目录：按 server.yml 装配工具，列出与调用，错误结果标为 isError；实验目录只能建在仓库之外。

不连库：这里的调用都在执行前被拒绝。经 MCP 在测试实例上的写入由真实客户端检验。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from mcp.shared.memory import create_connected_server_and_client_session

from e09.config import REPO
from e09.mcp import SPEC, SpecError, load, serve
from e09.tools import TOOLS as OPERATORS
from e09.workspace import main as workspace

NO_STORE: Any = None  # 被拒绝的请求不会用到库


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def _tools(monkeypatch: pytest.MonkeyPatch, commit: bool) -> dict[str, Any]:
    if commit:
        monkeypatch.setenv("E09_ENABLE_COMMIT", "1")
    else:
        monkeypatch.delenv("E09_ENABLE_COMMIT", raising=False)
    server = serve(NO_STORE, session="s-test", formed_by="test/model", sync=None)
    async with create_connected_server_and_client_session(server) as client:
        return {t.name: t for t in (await client.list_tools()).tools}


@pytest.mark.anyio
async def test_each_operator_is_a_tool_and_commit_is_listed_only_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    tools = await _tools(monkeypatch, commit=False)
    assert list(tools) == [n for n in OPERATORS if n != "Commit"]
    assert all(_bare(tools[n].inputSchema) == _admitted(OPERATORS[n].parameters) for n in tools)  # 结构来自算子
    assert tools["Check"].inputSchema["properties"]["payload"]["type"] == ["object", "string"]
    assert all(
        tools[n].description and all("description" in p for p in tools[n].inputSchema["properties"].values())
        for n in tools
    )
    assert tools["Search"].annotations.readOnlyHint is True
    assert tools["Extract"].annotations.readOnlyHint is False and tools["Extract"].annotations.idempotentHint is True
    commit = (await _tools(monkeypatch, commit=True))["Commit"].annotations
    assert commit.destructiveHint is True and commit.idempotentHint is False


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("name", "arguments", "at"),
    [
        ("Search", {"type": "Entity", "nope": 1}, "nope"),  # 未知参数
        (
            "Summarize",
            {"abs": "a", "inputs": [], "params": {"focus": "f"}, "payload": {"text": "t"}, "session": "x"},
            "session",
        ),  # 调用环境不是参数
        ("Commit", {"doc": "graph-doc: v0.1", "source": "t"}, "tool"),  # 没有启用
    ],
)
async def test_rejected_calls_are_errors_with_the_unified_shape(
    monkeypatch: pytest.MonkeyPatch, name: str, arguments: dict[str, Any], at: str
) -> None:
    monkeypatch.delenv("E09_ENABLE_COMMIT", raising=False)
    server = serve(NO_STORE, session="s-test", formed_by="test/model", sync=None)
    async with create_connected_server_and_client_session(server) as client:
        result = await client.call_tool(name, arguments)
    assert result.isError is True
    out = yaml.safe_load(result.content[0].text)
    assert out["status"] == "rejected"
    assert [(e["rule"], e["at"]) for e in out["errors"]] == [("format", at)]


def _admitted(schema: dict[str, Any]) -> dict[str, Any]:
    """算子的 schema，顶层的对象与数组参数也接受字符串（交给服务端修复）。"""
    out = json.loads(json.dumps(schema))
    for prop in out["properties"].values():
        if prop.get("type") in ("object", "array"):
            prop["type"] = [prop["type"], "string"]
    return out


def _bare(schema: Any) -> Any:
    """去掉说明后的 schema。"""
    if isinstance(schema, dict):
        return {k: _bare(v) for k, v in schema.items() if k != "description"}
    return [_bare(v) for v in schema] if isinstance(schema, list) else schema


def test_server_yml_describes_every_operator() -> None:
    spec = load()
    assert spec.name == "PaperWeave" and list(spec.tools) == list(OPERATORS)
    check = spec.tools["Check"].inputSchema["properties"]
    assert check["payload"]["properties"]["judgments"]["items"]["properties"]["basis"]["description"]
    assert check["params"]["properties"]["pairs"]["anyOf"][1]["items"]["items"] == {
        "type": "string"
    }  # 不串到共用的字典


@pytest.mark.parametrize(
    ("edit", "problem"),
    [
        (lambda d: d["tools"].pop("Search"), "tools.Search: missing"),
        (lambda d: d["tools"]["Search"]["parameters"].update({"wher": "x"}), "tools.Search.parameters.wher: no such"),
        (lambda d: d["tools"]["Search"]["parameters"].pop("budget"), "tools.Search.parameters.budget: no description"),
        (lambda d: d["tools"].update({"Rank": {}}), "tools.Rank: no such operator"),
    ],
)
def test_server_yml_must_match_the_operators(tmp_path: Path, edit: Any, problem: str) -> None:
    doc = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    edit(doc)
    path = tmp_path / "server.yml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    with pytest.raises(SpecError) as exc:
        load(path)
    assert any(p.startswith(problem) for p in exc.value.problems)


def test_workspace_is_refused_inside_the_repository(capsys: pytest.CaptureFixture[str]) -> None:
    assert workspace([str(REPO / "experiments/e09/runs/w"), "--user", "u@lab.example"]) == 1
    assert "inside the repository" in capsys.readouterr().err
    assert not (REPO / "experiments/e09/runs/w").exists()


def test_workspace_registers_the_server(tmp_path: Path) -> None:
    target = tmp_path / "w"
    args = ["--user", "u@lab.example", "--agent", "pi/p/m", "--neo4j-uri", "bolt://localhost:7688"]
    assert workspace([str(target), *args]) == 0
    files = [p.relative_to(target).as_posix() for p in sorted(target.rglob("*"))]
    assert files == [".pi", ".pi/mcp.json", ".pi/settings.json", "pi.sh"]
    assert json.loads((target / ".pi/settings.json").read_text(encoding="utf-8")) == {"sessionDir": ".pi/sessions"}
    server = json.loads((target / ".pi/mcp.json").read_text(encoding="utf-8"))["mcpServers"]["PaperWeave"]
    assert server["args"] == ["-m", "e09.mcp"] and server["exposure"] == "direct"
    log = str(target / ".pi/paperweave.log")  # 服务启动后才写
    env = {"E09_NEO4J_URI": "bolt://localhost:7688", "E09_USER": "u@lab.example", "E09_AGENT": "pi/p/m"}
    assert server["env"] == env | {"E09_MCP_LOG": log}
    assert workspace([str(target), "--user", "u@lab.example"]) == 1  # 已存在且不空
