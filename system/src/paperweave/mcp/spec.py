"""按 ``server.yml`` 装配 MCP 暴露：服务名与版本、``instructions``、每个算子的工具（标题、说明、带参数说明的
``inputSchema``）。结构来自 :data:`paperweave.tools.TOOLS`，文字只在 ``server.yml`` 中。

装配时严格核对，任一不过即拒绝（服务不启动）：顶层键、``server`` 的键、工具与算子一一对应、每个工具的键、参数路径
都能在算子的 ``parameters`` 中找到、每个顶层参数都有说明。

工具的 ``inputSchema`` 中，顶层的对象与数组参数写成 ``type: [object|array, string]``：模型偶尔输出不合法的 JSON
（如少写最后的括号），工具调用解析器就把它交成字符串；客户端（如 pi）按 schema 先行校验时会直接拒绝，
服务端的兜底修复（:mod:`paperweave.operators.repair`）就用不上。声明的第一个类型仍是对象或数组，解析器照常解析合法的
JSON（sglang 解析 qwen 的工具调用时已验证）。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import mcp.types as types
import yaml

from ..operators import Operator
from ..tools import TOOLS

SPEC = Path(__file__).with_name("server.yml")
TOP = {"server", "instructions", "shared", "tools"}
SERVER = {"name", "version"}
TOOL = {"title", "description", "parameters"}


class SpecError(ValueError):
    """``server.yml`` 与算子对不上。``problems`` 逐条列出。"""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("server.yml: " + "; ".join(problems))
        self.problems = problems


@dataclass(frozen=True, slots=True)
class Spec:
    """装配好的暴露。``digest`` 是 ``server.yml`` 内容的哈希（前 12 位），记入日志以追溯所用的文字。"""

    name: str
    version: str
    instructions: str
    tools: dict[str, types.Tool]
    digest: str


def load(path: Path = SPEC, operators: Mapping[str, Operator] = TOOLS) -> Spec:
    """读 ``server.yml`` 并装配全部算子的工具。

    Raises:
        SpecError: 文件与算子对不上。
    """
    text = path.read_text(encoding="utf-8")
    doc = yaml.safe_load(text)
    problems: list[str] = []
    if not isinstance(doc, dict):
        raise SpecError(["not a mapping"])
    problems += [f"unknown key {k}" for k in sorted(set(doc) - TOP)]
    problems += [f"missing key {k}" for k in sorted(TOP - {"shared"} - set(doc))]
    server, tools = doc.get("server") or {}, doc.get("tools") or {}
    if set(server) != SERVER:
        problems.append(f"server takes exactly {sorted(SERVER)}")
    problems += [f"tools.{n}: no such operator" for n in sorted(set(tools) - set(operators))]
    problems += [f"tools.{n}: missing" for n in operators if n not in tools]
    built: dict[str, types.Tool] = {}
    for name, op in operators.items():
        entry = tools.get(name)
        if not isinstance(entry, dict):
            continue
        if set(entry) != TOOL:
            problems.append(f"tools.{name} takes exactly {sorted(TOOL)}")
            continue
        schema, missed = _described(op.parameters, entry["parameters"] or {})
        _admit_text(schema)
        problems += [f"tools.{name}.parameters.{p}" for p in missed]
        built[name] = types.Tool(
            name=name,
            title=entry["title"],
            description=entry["description"].strip(),
            inputSchema=schema,
            annotations=annotations(op, entry["title"]),
        )
    if problems:
        raise SpecError(problems)
    return Spec(
        name=server["name"],
        version=str(server["version"]),
        instructions=doc["instructions"].strip(),
        tools=built,
        digest=hashlib.sha256(text.encode("utf-8")).hexdigest()[:12],
    )


def annotations(op: Operator, title: str) -> types.ToolAnnotations:
    """MCP 的行为提示：读取算子与读取接口只读；CheckIn 只追加版本，相同内容重交不再写入；Commit 可修改与删除。"""
    if not op.writes:
        return types.ToolAnnotations(title=title, readOnlyHint=True, openWorldHint=False)
    appends = not op.destructive
    return types.ToolAnnotations(
        title=title, readOnlyHint=False, destructiveHint=not appends, idempotentHint=appends, openWorldHint=False
    )


def _described(parameters: Mapping[str, Any], texts: Mapping[str, str]) -> tuple[dict[str, Any], list[str]]:
    """把参数说明按路径填进 ``parameters`` 的副本。返回副本与问题（找不到的路径、缺少说明的顶层参数）。"""
    schema = json.loads(json.dumps(parameters))  # 逐处独立的副本：同一个 schema 字典可能被多处引用
    missed: list[str] = []
    for path, text in texts.items():
        node = _node(schema, path)
        if node is None or not isinstance(text, str) or not text.strip():
            missed.append(f"{path}: no such parameter" if node is None else f"{path}: empty")
        else:
            node["description"] = text.strip()
    missed += [f"{k}: no description" for k, v in schema["properties"].items() if "description" not in v]
    return schema, missed


def _admit_text(schema: dict[str, Any]) -> None:
    """顶层的对象与数组参数也接受字符串，交给服务端修复。"""
    for prop in schema["properties"].values():
        if prop.get("type") in ("object", "array"):
            prop["type"] = [prop["type"], "string"]


def _node(schema: dict[str, Any], path: str) -> dict[str, Any] | None:
    """路径所指的 schema 节点：``.`` 连接属性名，``[]`` 表示数组的元素；一个值或一组值（``anyOf``）时进入相应的分支。"""
    node: dict[str, Any] | None = schema
    for part in path.split("."):
        name, items = part.removesuffix("[]"), part.endswith("[]")
        node = _branch(node, lambda n, name=name: name in n.get("properties", {}))
        node = node["properties"][name] if node is not None else None
        if items and node is not None:
            node = _branch(node, lambda n: "items" in n)
            node = node["items"] if node is not None else None
        if node is None:
            return None
    return node


def _branch(node: dict[str, Any] | None, has: Any) -> dict[str, Any] | None:
    if node is None or has(node):
        return node
    return next((b for b in node.get("anyOf", []) if isinstance(b, dict) and has(b)), None)


__all__ = ["SPEC", "Spec", "SpecError", "annotations", "load"]
