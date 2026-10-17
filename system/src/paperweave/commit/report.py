"""返回给 Agent 的两种文档：dry_run 的 graph-plan 与 apply 的 graph-result（commit.md §4）。

都是普通 dict，可直接转成 YAML 或 JSON。节点用文档中的引用指称：dry_run 中新节点就是 ``$`` 引用，
apply 后另给 ``$`` 引用到 id 的映射。
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from graph_vc import Changeset, CommitRecord, ConflictError

from ..model.schema import kind_of
from .problems import Problem
from .reader import Reader
from .submit import Prepared

# 各类阻塞项的改法提示；{ref} 是出问题的节点引用
FIXES = {
    "dedup": "one is the same thing: use its id instead of {ref}; none is: confirm: {{{ref}: {{distinct_from: [<ids>]}}}}",
    "name-taken": "the name already belongs to the node shown: use that id instead of a new node, or pick another name",
    "identity-taken": "the identity already belongs to the node shown: use that id instead of a new node",
    "exp-taken": "this experiment is already recorded: change the existing record (set) instead of creating it again",
    "exists": "the edge is already there: leave it out, or move it under set to change its properties",
    "revision": (
        "re-read the paper lines (read_evidence); if the record misstates the paper, add confirm.{ref}.revise with "
        "reason and anchor (the supporting line ranges); otherwise leave the record unchanged"
    ),
}
CONFLICT_FIX = "the store changed after your dry run; read the affected nodes again (get) and resubmit"


def plan(prepared: Prepared, reader: Reader) -> dict[str, Any]:
    """dry_run 的返回：状态、将要做的修改、阻塞项 ``errors``（带候选与改法）与提示 ``warnings``。"""
    if prepared.errors:
        status = "blocked"
    elif not prepared.changeset:
        status = "noop"
    else:
        status = "ready"
    out: dict[str, Any] = {"status": status}
    ref = _ref_of(prepared)
    if prepared.changeset:
        out["changes"] = summarize(prepared.changeset, ref)
    errors = [p for p in prepared.problems if p.severity == "error"]
    warnings = [p for p in prepared.problems if p.severity == "warning"]
    described = _describe_candidates(errors + warnings, reader)
    if errors:
        out["errors"] = _grouped([_problem(p, described) for p in errors])
    if warnings:
        out["warnings"] = _grouped([_problem(p, described) for p in warnings])
    return out


def _grouped(problems: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """同一条消息（规则、消息与改法都相同，没有候选）只列一次，``at`` 是各处位置的列表。"""
    out: list[dict[str, Any]] = []
    first: dict[tuple[str, ...], dict[str, Any]] = {}
    for p in problems:
        key = (p["rule"], p["msg"], p.get("fix", ""))
        if "candidates" in p:
            out.append(p)
            continue
        if key not in first:
            first[key] = p
            out.append(p)
            continue
        seen = first[key]
        seen["at"] = [*seen["at"], p["at"]] if isinstance(seen["at"], list) else [seen["at"], p["at"]]
    return out


def result(prepared: Prepared, record: CommitRecord, names: dict[str, str] | None = None) -> dict[str, Any]:
    """apply 成功后的返回：提交 id、``$`` 名到 id 的映射（附名称）与计数。"""
    assert prepared.changeset is not None
    names = names or {}
    summary = summarize(prepared.changeset, _ref_of(prepared))  # 与 dry_run 的 changes 同一口径：不算名称键与材料
    out: dict[str, Any] = {
        "status": "committed",
        "commit": record.id,
        "ids": {ref: f"{node_id} ({names[ref]})" if names.get(ref) else node_id for ref, node_id in prepared.ids.items()},
        "counts": {
            "nodes": {"create": len(summary["create"]), "update": len(summary["update"]), "delete": len(summary["delete"])},
            "edges": summary["edges"],
        },
    }
    warnings = [p for p in prepared.problems if p.severity == "warning"]
    if warnings:
        out["warnings"] = _grouped([_problem(p, {}) for p in warnings])
    return out


def conflict(error: ConflictError) -> dict[str, Any]:
    """提交时改前状态与库中当前状态不一致（dry_run 之后库被改动）：整批未写入，需重新读取后再交。"""
    return {
        "status": "conflict",
        "errors": [{"rule": "conflict", "at": c.target, "msg": c.reason, "fix": CONFLICT_FIX} for c in error.conflicts],
    }


def summarize(changeset: Changeset, ref: dict[str, str]) -> dict[str, Any]:
    """按模型节点列出新建、修改（改了哪些字段与关系键）与删除；名称与材料单独计数。"""
    create, delete = [], []
    update: dict[str, set[str]] = {}
    names: Counter[str] = Counter()
    materials = []
    for n in changeset.nodes:
        labels = n.labels_after or n.labels_before or frozenset()
        name = ref.get(n.id, n.id)
        if "NameKey" in labels:
            names[n.op] += 1
        elif "Material" in labels:
            if n.op == "create":
                materials.append((n.after or {}).get("path"))
        elif kind_of(labels) is None:
            continue
        elif n.op == "create":
            create.append(name)
        elif n.op == "delete":
            delete.append(name)
        else:
            fields = set(n.after or {})
            if n.labels_before != n.labels_after:
                fields.add("kind")
            update.setdefault(name, set()).update(fields)
    created = set(create)
    deleted = set(delete)
    edges: Counter[str] = Counter()
    for e in changeset.edges:
        if e.key.type == "MATERIAL_OF":
            continue
        if e.key.type == "NAMES":  # 名称或别名有增删：记在被命名的节点上
            owner = ref.get(e.key.dst, e.key.dst)
            if owner not in created and owner not in deleted:
                update.setdefault(owner, set()).add("names")
            continue
        edges[e.op] += 1
        src = ref.get(e.key.src, e.key.src)
        if src not in created and src not in deleted:
            update.setdefault(src, set()).add(e.key.type)
    out: dict[str, Any] = {
        "create": create,
        "update": {k: sorted(v) for k, v in update.items()},
        "delete": delete,
        "edges": {op: edges.get(op, 0) for op in ("create", "update", "delete")},
    }
    if names:
        out["names"] = {op: names[op] for op in ("create", "update", "delete") if names[op]}
    if materials:
        out["materials"] = materials
    return out


def _problem(problem: Problem, described: dict[str, dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {"rule": problem.rule, "at": problem.at, "msg": problem.msg}
    if problem.candidates:  # 一个候选一行：id → kind、名称、描述开头与命中的通道
        out["candidates"] = {
            c: _one_line(described.get(c, {}), problem.evidence.get(c, ())) for c in problem.candidates
        }
    if problem.severity == "error" and problem.rule in FIXES:
        parts = problem.at.split(".")
        node = parts[1] if len(parts) > 1 and parts[0] in ("create", "set", "delete", "confirm") else parts[0]
        out["fix"] = FIXES[problem.rule].format(ref=node)
    return out


def _describe_candidates(problems: list[Problem], reader: Reader) -> dict[str, dict[str, Any]]:
    ids = sorted({c for p in problems for c in p.candidates})
    if not ids:
        return {}
    state = reader.local_state(ids)
    described = {}
    for node_id in ids:
        node = state.nodes.get(node_id)
        if node is None:
            continue
        info: dict[str, Any] = {"kind": kind_of(node.labels)}
        if "name" in node.props:
            info["name"] = node.props["name"]
        if node.props.get("stub") is True:
            info["stub"] = True
        description = node.props.get("description")
        if isinstance(description, str):
            info["description"] = description
        described[node_id] = info
    return described


def _one_line(info: dict[str, Any], channels: tuple[str, ...] | list[str]) -> str:
    text = " ".join(str(info.get(k, "")) for k in ("kind", "name") if info.get(k))
    if info.get("stub"):
        text += " (stub)"
    description = " ".join(str(info.get("description", "")).split())
    if description:
        text += ": " + (description if len(description) <= 100 else description[:100].rstrip() + " …")
    return f"{text} [{', '.join(channels)}]" if channels else text


def _ref_of(prepared: Prepared) -> dict[str, str]:
    return {node_id: ref for ref, node_id in prepared.ids.items()}


__all__ = ["conflict", "plan", "result", "summarize"]
