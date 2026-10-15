"""Resolve：把一个说法解析为已存对象的引用（intents_decompose.md §4.1，graph_model_v2.md §2.4）。

    resolve(query={identifier?, mention?, text?}, *, kind, scope="global", mode="read")
      -> {stage: id | alias | semantic, status: resolved | ambiguous | candidates | none | unprocessed,
          refs, match_trace, states, coverage, execution: ok | partial | error}

query 也可以直接给一个字符串，即 mention。三级逐级解析，type 由 kind 推出（单次调用一个合法 kind）：

1. **id**：`identifier` 在本 kind 对象的 identifiers 中精确匹配。唯一命名空间单个命中即 resolved；
   非唯一命名空间（url）的命中只缩小候选、不单独确定身份：多重命中返回 ambiguous 及全部命中，不静默落到下一级；
   单个命中返回 candidates。
2. **alias**：`mention` 经 name-key-v1 规范化后查 NameKey（`规范化名称|kind|scope`）。active 键唯一命中即 resolved；
   已隔离为 ambiguous 的键返回 ambiguous。与 id 级同时有结果时取交集：交集唯一 resolved，
   仍不唯一或为空保留 ambiguous 交外部 A_pred；名称命中了对象、交集却为空时另记 resolution=conflicting。
3. **semantic**：名称词面（NameKey.raw 全文）、文本（description / definition 全文）、向量三路召回，按 RRF 融合；
   只给候选，value=U，由外部 A_pred 确认。没有阈值：只要本 kind 有对象，向量通道总会给出近邻。

read 模式前两级 resolved 即停止；ambiguous 时仍跑语义阶段，结果记入 match_trace 供外部判断。
write 模式前两级命中后仍跑语义查重，近邻记入 match_trace；非唯一标识的多重命中只作查重候选（candidates），不直接复用。
三级都没有引用时返回 none、access=empty、resolution=missing（missing_in=store）。
通道执行失败记入 execution（partial / error）；因失败而没有引用时 status=unprocessed、access=unprocessed，不当作 none。
states 的维度与取值沿用 intents_decompose.md §4.3.2.1。
"""

from ..store.embedding import EMBED_MODEL, VECTOR_INDEXES, embed
from .fusion import POOL, RRF_K, TOP_N, fuse, tokens
from ..store.graph import q
from ..model.namekey import NORMALIZER, name_key
from ..model.schema import FAMILY, NAMESPACES

INSTRUCT = {   # 查询侧的任务说明（Qwen3-Embedding 的 Instruct 格式）；写入侧不加
    "Entity": "Instruct: Given a mention of a dataset, model, benchmark or other resource in a research paper, "
              "retrieve the entry that refers to the same object\nQuery: ",
    "Concept": "Instruct: Given a mention of a method, task or metric in a research paper, "
               "retrieve the entry that refers to the same concept\nQuery: ",
}
TEXT_INDEX = {"Entity": "entity_texts", "Concept": "concept_texts"}
VECTOR_INDEX = {label: name for name, label in VECTOR_INDEXES.items()}
OVERFETCH = 5   # 向量索引先取 POOL × OVERFETCH 再按 kind 过滤；近似召回后过滤可能漏掉可行候选，记入 coverage


# ── 第三级的三个通道：各自返回本 kind 内的有序 [{id, score}] ──

def _lexical_name(mention, kind, scope):
    """名称词面：NameKey.raw 的全文索引，每个词取原词、前缀与模糊三种写法；同一对象多个键取最高分。"""
    query = " ".join(f"{t} {t}* {t}~" for t in tokens(mention))
    if not query:
        return []
    return q("""CALL db.index.fulltext.queryNodes('namekey_raw', $query) YIELD node, score
                WHERE node.kind = $kind AND node.scope = $scope
                MATCH (node)-[:NAMES]->(o)
                RETURN o.id AS id, max(score) AS score ORDER BY score DESC, id LIMIT $pool""",
             query=query, kind=kind, scope=scope, pool=POOL)


def _lexical_text(text, family, kind):
    query = " ".join(tokens(text))
    if not query:
        return []
    return q(f"""CALL db.index.fulltext.queryNodes('{TEXT_INDEX[family]}', $query) YIELD node, score
                 WHERE $kind IN labels(node)
                 RETURN node.id AS id, score ORDER BY score DESC, id LIMIT $pool""",
             query=query, kind=kind, pool=POOL)


def _semantic(query_text, family, kind):
    v = embed([INSTRUCT[family] + query_text])[0]
    return q(f"""CYPHER 25
                 MATCH (node) SEARCH node IN (VECTOR INDEX {VECTOR_INDEX[family]} FOR $v LIMIT $k) SCORE AS score
                 WITH node, score WHERE $kind IN labels(node)
                 RETURN node.id AS id, score ORDER BY score DESC, id LIMIT $pool""",
             v=v, k=POOL * OVERFETCH, kind=kind, pool=POOL)


def recall_channels(mention, text, family, kind, scope, channels=None) -> tuple[dict, dict]:
    """返回 (各通道的有序结果, 各通道状态)。缺少输入或未被 channels 选中的通道关闭；执行失败记为 error，不吞掉。"""
    plan = {
        "lexical_name": (lambda: _lexical_name(mention, kind, scope)) if mention else None,
        "lexical_text": (lambda: _lexical_text(text, family, kind)) if text else None,
        "semantic": (lambda: _semantic(f"{mention}: {text}" if mention and text else mention or text, family, kind))
                    if mention or text else None,
    }
    results, status = {}, {}
    for ch, run in plan.items():
        if channels is not None and ch not in channels:
            run = None
        if run is None:
            status[ch] = "disabled"
            continue
        try:
            results[ch] = run()
            status[ch] = f"ok ({len(results[ch])})"
        except Exception as e:   # 服务不可用、索引缺失等
            status[ch] = f"error: {type(e).__name__}: {e}"
    return results, status


# ── Resolve ──

def _id_stage(identifier, family, kind):
    ns = identifier.partition(":")[0]
    if ns not in NAMESPACES:
        raise ValueError(f"未声明的命名空间 {ns!r}：{sorted(NAMESPACES)}")
    hits = [r["id"] for r in q(f"MATCH (o:{family}:{kind}) WHERE $i IN o.identifiers RETURN o.id AS id ORDER BY id",
                               i=identifier)]
    return {"stage": "id", "identifier": identifier, "unique_namespace": NAMESPACES[ns], "hits": hits}


def _alias_stage(mention, kind, scope):
    key = name_key(mention, kind, scope)
    rows = q("MATCH (k:NameKey {key: $key}) OPTIONAL MATCH (k)-[:NAMES]->(o) "
             "RETURN k.status AS status, collect(o.id) AS hits", key=key)
    status, hits = (rows[0]["status"], sorted(rows[0]["hits"])) if rows else (None, [])
    return {"stage": "alias", "key": key, "key_status": status, "hits": hits, "normalizer_ref": NORMALIZER}


def resolve(query: dict | str, *, kind: str, scope: str = "global", mode: str = "read", n: int = TOP_N,
            channels: set[str] | None = None) -> dict:
    """channels 限定语义阶段使用的通道（lexical_name / lexical_text / semantic），默认全开；
    关闭的通道在 coverage.channels 中记为 disabled。Commit 对桩节点查重只开名称词面（commit_contract.md §4）。"""
    query = {"mention": query} if isinstance(query, str) else dict(query)
    if unknown := set(query) - {"identifier", "mention", "text"}:
        raise ValueError(f"query 只接受 identifier、mention、text，不接受 {sorted(unknown)}")
    mention, identifier, text = query.get("mention"), query.get("identifier"), query.get("text")
    if kind not in FAMILY:
        raise ValueError(f"未知 kind {kind!r}")
    if FAMILY[kind] not in INSTRUCT:
        raise ValueError(f"Resolve 只解析 Entity 与 Concept，{kind!r} 属于 {FAMILY[kind]}")
    if mode not in ("read", "write"):
        raise ValueError(f"mode 只能是 read / write，不是 {mode!r}")
    if not (mention or identifier or text):
        raise ValueError("mention、identifier、text 至少给一个")
    family = FAMILY[kind]
    trace, issues = [], []
    result = None   # (stage, status, refs)：前两级的主解析结果

    # 1–2. 精确阶段
    ids = _id_stage(identifier, family, kind) if identifier else None
    names = _alias_stage(mention, kind, scope) if mention else None
    trace += [s for s in (ids, names) if s]
    H = ids["hits"] if ids else []
    A = names["hits"] if names else []
    alias_ok = bool(names) and names["key_status"] == "active" and len(A) == 1   # 唯一键 active 且只指向一个对象
    if names and names["key_status"] == "active" and len(A) > 1:
        issues.append({"rule": "key-multi-target", "key": names["key"], "refs": A})   # 唯一键指向多个对象：数据不一致

    if H:
        unique = ids["unique_namespace"]
        if unique and len(H) > 1:
            issues.append({"rule": "unique-identifier-duplicated", "identifier": identifier, "refs": H})
        if mode == "write" and not unique:
            # 写入模式：非唯一标识的命中只作查重候选；名称唯一命中仍是精确身份
            result = ("alias", "resolved", A) if alias_ok else ("id", "candidates", H)
        elif A:
            inter = sorted(set(H) & set(A))
            if len(inter) == 1 and (alias_ok or names["key_status"] == "ambiguous" or unique):
                result = ("alias" if not unique else "id", "resolved", inter)
            else:
                if not inter:
                    issues.append({"rule": "id-name-disjoint", "identifier": identifier, "id_refs": H,
                                   "key": names["key"], "name_refs": A})
                result = ("id", "ambiguous", H)
        elif unique and len(H) == 1:
            result = ("id", "resolved", H)
        else:
            # 非唯一标识：多个命中为 ambiguous；单个命中只缩小候选，不单独确定身份
            result = ("id", "ambiguous" if len(H) > 1 else "candidates", H)
    elif names and names["key_status"] == "ambiguous":
        result = ("alias", "ambiguous", A)
    elif alias_ok:
        result = ("alias", "resolved", A)
    elif names and len(A) > 1:
        result = ("alias", "ambiguous", A)

    # 3. 语义阶段：read 模式已 resolved 则不跑；其余情况都跑，作为主结果或记入 trace
    coverage = {"kind": kind, "scope": scope, "mode": mode, "pool": POOL, "rrf_k": RRF_K, "top_n": n,
                "vector": {"model": EMBED_MODEL, "overfetch": POOL * OVERFETCH, "filter": "kind after index"},
                "channels": {}, "truncated": False}
    errors = []
    if not (mode == "read" and result and result[1] == "resolved"):
        channels, coverage["channels"] = recall_channels(mention, text, family, kind, scope, channels)
        errors = [f"{ch}: {s}" for ch, s in coverage["channels"].items() if s.startswith("error")]
        fused = fuse(channels)
        exact = set(result[2]) if result else set()
        if result:   # 已有精确或标识结果：语义候选只作参考（read 的 ambiguous）或查重（write）
            if channels or errors:   # 三个通道都因缺少输入而关闭时，不记空的语义步骤
                near = [c for c in fused if c["id"] not in exact][:n]
                trace.append({"stage": "semantic", "role": "dedup" if mode == "write" else "for A_pred", "candidates": near})
        else:
            coverage["truncated"] = len(fused) > n
            top = fused[:n]
            trace.append({"stage": "semantic", "role": "result", "candidates": top})
            if top:
                result = ("semantic", "candidates", [c["id"] for c in top])
            elif errors:
                result = ("semantic", "unprocessed", [])
            else:
                result = ("semantic", "none", [])
    else:
        coverage["channels"] = {"lexical_name": "skipped", "lexical_text": "skipped", "semantic": "skipped"}

    stage, status, refs = result
    resolution = {"resolved": "resolved", "ambiguous": "ambiguous", "candidates": "unresolved",
                  "none": "missing", "unprocessed": "unresolved"}[status]
    if issues and status != "resolved":
        resolution = "conflicting"   # 标识与名称指向不同对象，或唯一键/唯一标识指向多个对象
    states = {"access": "matched" if refs else ("unprocessed" if status == "unprocessed" else "empty"),
              "resolution": resolution, "value": "T" if status == "resolved" else "U",
              "origin": "rule", "issues": issues, "errors": errors}
    if resolution == "missing":
        states["missing_in"] = "store"
    execution = "ok" if not errors else ("error" if status == "unprocessed" else "partial")
    return {"stage": stage, "status": status, "refs": refs, "match_trace": trace, "states": states,
            "coverage": coverage, "execution": execution}
