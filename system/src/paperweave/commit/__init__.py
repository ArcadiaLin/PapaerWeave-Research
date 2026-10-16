"""graph-doc 的写入管线：graph-doc → 物理目标状态 → 变更集 → graph-vc 提交（Commit 算子的执行）。

设计见 docs/designs/v3/tools.md（graph-doc v0.2）与 data_model.md。通用部分在 packages/graph-doc（解析与求差）与
packages/graph-vc（变更集与版本记录）；这里只放 PaperWeave 数据模型相关的翻译与检查。
"""

from .checks import check_state, touched
from .problems import Problem
from .reader import MemoryReader, Neo4jReader, Reader
from .report import conflict, plan, result, summarize
from .review import Candidate, Deduper, Lookup, delete_impact, review
from .submit import Prepared, allocate_ids, apply, prepare
from .translate import Context, Translation, translate

__all__ = [
    "Candidate",
    "Context",
    "Deduper",
    "Lookup",
    "MemoryReader",
    "Neo4jReader",
    "Prepared",
    "Problem",
    "Reader",
    "Translation",
    "allocate_ids",
    "apply",
    "check_state",
    "conflict",
    "delete_impact",
    "plan",
    "prepare",
    "result",
    "review",
    "summarize",
    "touched",
    "translate",
]
