"""Search 的结果视图：每个结果只给识别字段与检索字段的开头摘录，整份结果控制在容量上限之内。

MCP 客户端会截断过长的工具结果（pi 为 20 KB，截掉中间部分），所以结果的大小由这里控制，而不是交给客户端：

1. 先放下每个结果的识别字段与 ``meta``；放不下时从末尾去掉结果，续取位置随之前移；
2. 余下的容量平均分给各个结果的摘录；某个结果的摘录本来就短，省下的部分再平均分给其余结果；
3. 一个结果内按字段顺序分配（Content 先 ``text`` 后 ``note``）；
4. 超出份额的字段在 UTF-8 字符边界截断，末尾写 ``…``，并在其后给出原文长度 ``<字段>_bytes``。

大小按 YAML 的字节数计（与返回给 Agent 的文本相同）；折行带来的额外字节在超限时再扣减重算。
结果不带关系；对象的全部关系与完整字段用 Traverse 读取（``path`` 为空），原文用 ReadEvidence 读取。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from graph_vc import GraphState

from ..model.schema import ARTIFACT, kind_of
from ..yamlfmt import dump
from .view import source_refs_of

LIMIT = 16 * 1024  # 字节；低于 pi 的 20 KB，给 YAML 与客户端的提示留出余量
ELLIPSIS = "…"
EXCERPTS = {  # 各类别摘录的字段，即该类别全文与向量检索的字段；Content 另带 note（原文中的问题常写在这里）
    "Entity": ("description",),
    "Concept": ("definition", "text"),
    "Content": ("text", "note"),
    ARTIFACT: ("abs",),
}


def results(
    type_: str,
    state: GraphState,
    ids: list[str],
    offset: int,
    matched: int,
    extra: Mapping[str, Any] | None = None,
    artifacts: Mapping[str, Mapping[str, Any]] | None = None,
    limit: int = LIMIT,
) -> dict[str, Any]:
    """第 ``offset`` 名起 ``ids`` 的结果视图 ``{results, meta}``。``meta`` 为 ``returned``、``matched``、
    ``continuation``、``extra`` 中的字段与 ``size``；``artifacts`` 是 Artifact 的 ``_document`` 与 ``_stale``
    （:func:`paperweave.artifact.stale.readonly`）。"""
    artifacts = artifacts or {}
    heads = [_head(type_, i, state, artifacts.get(i, {})) for i in ids]
    texts = [{f: v for f in EXCERPTS[type_] if isinstance(v := state.nodes[i].props.get(f), str) and v} for i in ids]
    while True:  # 识别字段放不下时从末尾去掉结果
        end = offset + len(heads)
        meta = {"returned": len(heads), "matched": matched, "continuation": end if end < matched else None}
        meta.update(extra or {}, size={"limit": limit, "used": limit, "cut": 2 * len(heads)})  # 占位：位数不少于实际
        allowance = limit - _bytes(_view(heads, [{f: "" for f in t} for t in texts], meta))
        if allowance >= 0 or len(heads) <= 1:
            break
        heads, texts = heads[:-1], texts[:-1]
    while True:
        shares = _shares([sum(_len(v) for v in t.values()) for t in texts], allowance)
        excerpts = [_excerpt(t, share) for t, share in zip(texts, shares, strict=True)]
        view = _view(heads, excerpts, meta)
        used = _bytes(view)
        if used <= limit or allowance <= 0:
            break
        allowance -= used - limit
    cut = sum(k.endswith("_bytes") for e in excerpts for k in e)
    view["meta"]["size"] = {"limit": limit, "used": used, "cut": cut}
    for _ in range(2):  # 写入 used 本身后的大小；第二次计入位数的变化
        view["meta"]["size"]["used"] = _bytes(view)
    return view


def _head(type_: str, node_id: str, state: GraphState, artifact: Mapping[str, Any]) -> dict[str, Any]:
    props = state.nodes[node_id].props
    if type_ == ARTIFACT:
        head = {"id": node_id, "op": props.get("op"), "title": props.get("title"), "document": artifact.get("_document")}
        if artifact.get("_stale"):
            head["stale"] = artifact["_stale"]
        return head
    head = {"id": node_id, "kind": kind_of(state.nodes[node_id].labels)}
    head.update((k, props[k]) for k in ("name", "year") if props.get(k) is not None)
    if type_ == "Content":
        papers = sorted(k.dst for k in state.edges if k.src == node_id and k.type == "FROM")
        head["paper"] = papers[0] if len(papers) == 1 else papers
        if props.get("anchors"):
            head["anchors"] = props["anchors"]
        if artifact.get("_revised"):
            head["revised"] = artifact["_revised"]
        head["source_refs"] = list(dict.fromkeys(source_refs_of(node_id, state)))
    return head


def _view(heads: list[dict[str, Any]], excerpts: list[dict[str, Any]], meta: dict[str, Any]) -> dict[str, Any]:
    entries = []
    for head, excerpt in zip(heads, excerpts, strict=True):
        refs = {"source_refs": head["source_refs"]} if "source_refs" in head else {}
        entries.append({**{k: v for k, v in head.items() if k != "source_refs"}, **excerpt, **refs})
    return {"results": entries, "meta": {**meta, "size": dict(meta["size"])}}


def _shares(demands: list[int], total: int) -> list[int]:
    """把 ``total`` 字节平均分给各项；需求低于平均份额的项只拿它需要的，余下的再平均分给其余项。"""
    shares = [0] * len(demands)
    left = max(total, 0)
    pending = sorted(range(len(demands)), key=lambda i: demands[i])
    while pending:
        each = left // len(pending)
        if demands[pending[0]] > each:
            for i in pending:
                shares[i] = each
            break
        i = pending.pop(0)
        shares[i] = demands[i]
        left -= demands[i]
    return shares


def _excerpt(texts: dict[str, str], share: int) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for field, text in texts.items():
        size = _len(text)
        if size <= share:
            out[field] = text
            share -= size
            continue
        out[field] = cut(text, share)
        out[f"{field}_bytes"] = size
        share = 0
    return out


def cut(text: str, size: int) -> str:
    """截到 ``size`` 字节以内（UTF-8 字符边界），末尾写 ``…``。"""
    head = text.encode("utf-8")[: max(size - _len(ELLIPSIS), 0)].decode("utf-8", "ignore").rstrip()
    return head + ELLIPSIS


def _len(text: str) -> int:
    return len(text.encode("utf-8"))


def _bytes(view: dict[str, Any]) -> int:
    return _len(dump(view))


__all__ = ["EXCERPTS", "LIMIT", "cut", "results"]
