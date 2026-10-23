"""A2（同 schema 的裸图）：关掉机制的 PaperWeave MCP 服务。按 PAPERWEAVE_ABLATE（逗号分隔）关掉机制后照常启动
服务，不改 system/ 的代码（先导 tmps/pilot/ablate_mcp.py 移来，2026-10-19）。

- dedup：新建 Entity / Concept 不查重（deduper 为 None）。
- revision：Content 的修订不要求理由与锚点（丢掉 rule 为 revision 的问题；写了 revise 仍照常记下）。
- stale：读视图（get、search）中产物的 _stale 恒为空；记录的 _anchor_version（锚点写在论文旧版本上，f3 新增）也不给。
- affected：提交后不给 related_artifacts 与 affected_artifacts。

A2 = 四项全关。工具说明不变（文字对等），只去掉执行。

这是基线的实现，不属于 pweval 包：它导入被测系统，由运行框架（:mod:`pweval.harness.sandbox`）在系统的 .venv 中
以子进程启动，pweval 不导入它（tests/test_imports.py）。
"""

from __future__ import annotations

import os
import sys

from paperweave.artifact import stale as stale_mod
from paperweave.commit import submit
from paperweave.mcp import server
from paperweave.operators.db import commit as commit_op
from paperweave.query import read as read_mod

OFF = set(filter(None, os.environ.get("PAPERWEAVE_ABLATE", "").split(",")))
KNOWN = {"dedup", "revision", "stale", "affected"}
if OFF - KNOWN:
    sys.exit(f"unknown ablation: {sorted(OFF - KNOWN)}")

if "dedup" in OFF:
    commit_op.SearchDeduper = lambda store: None

if "revision" in OFF:
    _check = submit.check_revisions

    def check_revisions(*args, **kwargs):
        problems, revisions = _check(*args, **kwargs)
        return [p for p in problems if p.rule != "revision"], revisions

    submit.check_revisions = check_revisions

if "stale" in OFF:
    stale_mod.stale = lambda store, ids: {i: [] for i in ids}
    read_mod.anchor_versions = lambda store, ids: {}

if "affected" in OFF:
    commit_op.related = lambda store, commit: None
    commit_op._watch = lambda out, fn: {}
    commit_op._affected = lambda store, out, part, before: None

if __name__ == "__main__":
    sys.exit(server.main())
