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

PLAN_VERSION = "v0.1"
RESULT_VERSION = "v0.1"

# 各类阻塞项的改法提示；{ref} 是出问题的节点引用
FIXES = {
    "dedup": "same object: replace {ref} with the candidate id; different: list it in confirm.{ref}.distinct_from",
    "name-taken": "if it is the same object, edit the existing node by id; otherwise use a different name",
    "identifier-taken": "if it is the same object, edit the existing node by id; otherwise correct the identifier",
    "key-taken": "the record already exists; edit it by id instead of creating it again",
    "material": "check the material path; changing a registered material is not supported yet",
    "revision": (
        "re-read the paper (ReadEvidence); if the record misstates it, add confirm.{ref}.revise with reason and "
        "anchor (<section>::<start>:<end> of the supporting lines); otherwise leave the record unchanged"
    ),
    "coexist": "leave their record unchanged; state your own view in a new Observation (or OPPOSES between claims)",
}
CONFLICT_FIX = "the database changed after the dry run; read the affected nodes again and resubmit"


def plan(prepared: Prepared, reader: Reader) -> dict[str, Any]:
    """dry_run 的返回：状态、将要做的修改、阻塞项 ``errors``（带候选与改法）与提示 ``warnings``。"""
    if prepared.errors:
        status = "blocked"
    elif not prepared.changeset:
        status = "noop"
    else:
        status = "ready"
    out: dict[str, Any] = {"graph-plan": PLAN_VERSION, "status": status}
    ref = _ref_of(prepared)
    if prepared.changeset:
        out["changes"] = summarize(prepared.changeset, ref)
    errors = [p for p in prepared.problems if p.severity == "error"]
    warnings = [p for p in prepared.problems if p.severity == "warning"]
    described = _describe_candidates(errors + warnings, reader)
    if errors:
        out["errors"] = [_problem(p, described) for p in errors]
    if warnings:
        out["warnings"] = [_problem(p, described) for p in warnings]
    return out


def result(prepared: Prepared, record: CommitRecord) -> dict[str, Any]:
    """apply 成功后的返回：提交 id、``$`` 引用到 id 的映射与计数。"""
    assert prepared.changeset is not None
    counts = Counter(f"nodes_{n.op}d" for n in prepared.changeset.nodes)
    counts.update(f"edges_{e.op}d" for e in prepared.changeset.edges)
    out: dict[str, Any] = {
        "graph-result": RESULT_VERSION,
        "status": "committed",
        "commit": record.id,
        "ids": dict(prepared.ids),
        "counts": {
            key: counts.get(key, 0)
            for key in (
                "nodes_created",
                "nodes_updated",
                "nodes_deleted",
                "edges_created",
                "edges_updated",
                "edges_deleted",
            )
        },
    }
    warnings = [p for p in prepared.problems if p.severity == "warning"]
    if warnings:
        out["warnings"] = [_problem(p, {}) for p in warnings]
    return out


def conflict(error: ConflictError) -> dict[str, Any]:
    """提交时改前状态与库中当前状态不一致（dry_run 之后库被改动）：整批未写入，需重新读取后再交。"""
    return {
        "graph-result": RESULT_VERSION,
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
    if problem.candidates:
        out["candidates"] = [
            {
                "ref": c,
                **described.get(c, {}),
                **({"channels": list(problem.evidence[c])} if c in problem.evidence else {}),
            }
            for c in problem.candidates
        ]
    if problem.severity == "error" and problem.rule in FIXES:
        node = problem.at.split(".")[1] if problem.at.startswith("nodes.") else problem.at
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
        for key in ("name", "text"):
            if key in node.props:
                info[key] = node.props[key]
                break
        if node.props.get("stub") is True:
            info["stub"] = True
        described[node_id] = info
    return described


def _ref_of(prepared: Prepared) -> dict[str, str]:
    return {node_id: ref for ref, node_id in prepared.ids.items()}


__all__ = ["conflict", "plan", "result", "summarize"]
