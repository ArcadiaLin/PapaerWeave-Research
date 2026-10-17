"""get：按 id 读出节点的全部字段与出边（docs/designs/v3/tools.md）。

    get(ids, offset?: 0, limit?: 30) -> 带注释的 YAML：id → 节点，形状与 commit 中 set 下的节点相同

原样贴进 ``set`` 没有改动；改其中几个值就是修改。入边只给各类的条数（``_edges_in``），要看就用 ``traverse``。
产物给出类型、标题、摘要、``_stale`` 与 ``_uses``（用到的节点，按在文档中的位置分组）；全文用 ``checkout`` 取成
文件，用 agent 自己的读文件工具读（翻页也由它做），改完 ``commit``。

**分页**（与 pi 的 ``read`` 同一用法）：每种出边按终点 id 排序，只列第 ``offset`` 起的 ``limit`` 条；还有剩余时，
结尾的注释给出下一页的参数。返回超过 :data:`BUDGET` 时按整节点截短，剩下的 id 也在结尾给出。同样的参数与库状态
返回同样的一页。分页的节点贴回 ``set`` 也安全：``set`` 只改写列出的边。
"""

from __future__ import annotations

from typing import Any

from ...artifact.stale import readonly
from ...query.read import get_view
from ...store.store import ContractError, Store
from ..base import BUDGET, STRINGS, Rendered, db_operator, schema

MAX_IDS = 20
DEFAULT_LIMIT = 30
MAX_LIMIT = 100


def get(store: Store, ids: list[str] | str, offset: int = 0, limit: int = DEFAULT_LIMIT) -> Rendered:
    wanted = [ids] if isinstance(ids, str) else ids
    if not isinstance(wanted, list) or not wanted or not all(isinstance(i, str) for i in wanted):
        raise ContractError([{"at": "ids", "msg": "a list of node ids, such as [method_0021]"}])
    if len(wanted) > MAX_IDS:
        raise ContractError([{"at": "ids", "msg": f"at most {MAX_IDS} ids per call"}])
    if not isinstance(offset, int) or offset < 0:
        raise ContractError([{"at": "offset", "msg": "0 or more: edges of each type to skip"}])
    if not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        raise ContractError([{"at": "limit", "msg": f"1-{MAX_LIMIT}: edges of each type to list"}])
    wanted = list(dict.fromkeys(i.strip() for i in wanted))
    arts = [i for i in wanted if i.startswith("art_")]
    extra: dict[str, dict[str, Any]] = {}
    if arts:
        for art_id, info in readonly(store, arts).items():
            extra[art_id] = {"_stale": info["_stale"]} if info.get("_stale") else {}
            extra[art_id]["_document"] = (
                "checkout this id to get the document as a file; read it with your read tool, edit it and commit to save"
            )
    view, missing = get_view(store, wanted, extra, (offset, limit))
    header = []
    if missing:
        header.append(f"not in the store: {', '.join(missing)}")
    if view.data:
        header.append("fields and outgoing edges; paste a node under set to change it, add edges under create")
    shown = list(view.data)
    while len(shown) > 1 and len(view.subset(shown).text(header).encode()) > BUDGET:
        shown.pop()
    rest = [i for i in view.data if i not in shown]
    page = view.subset(shown)
    footer, more = _continuation(page.edge_totals, offset, limit)
    if rest:
        footer.append(
            f"[Showing {len(shown)} of {len(view.data)} nodes ({BUDGET // 1024} KB limit). "
            f"Get the rest with ids=[{', '.join(rest)}].]"
        )
    text = page.text(header) + "".join(f"# {line}\n" for line in footer)
    return Rendered({"nodes": page.data, "missing": missing, "more": more, "rest": rest}, text)


def _continuation(totals: dict[str, dict[str, int]], offset: int, limit: int) -> tuple[list[str], dict[str, dict[str, int]]]:
    """还有下一页的关系：每条一句“显示了第几到第几条，共几条”，最后一句给出下一页的参数。"""
    more = {
        node: {rel: n for rel, n in rels.items() if n > offset + limit}
        for node, rels in totals.items()
        if any(n > offset + limit for n in rels.values())
    }
    lines = [
        f"[{node} {rel}: showing {offset + 1}-{offset + limit} of {n}]" for node, rels in more.items() for rel, n in rels.items()
    ]
    if more:
        lines.append(f"[Use offset={offset + limit} with ids=[{', '.join(more)}] to continue.]")
    return lines, more


GET = db_operator(
    name="get",
    parameters=schema({"ids": STRINGS, "offset": {"type": "integer"}, "limit": {"type": "integer"}}, ["ids"]),
    run=get,
)

__all__ = ["GET", "get"]
