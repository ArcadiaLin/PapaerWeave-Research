"""语义阶段的召回参数、分词与 RRF 融合。精确阶段（标识、name/alias）不参与融合，也不计分。"""

import re

POOL = 20      # 每个通道召回的条数
RRF_K = 10     # 每路只有 POOL 条，常用的 60 会让名次几乎不起作用
TOP_N = 5


def tokens(s: str) -> list[str]:
    """查询词：小写字母与数字串。结果不含 Lucene 特殊字符，可以直接拼进全文查询。"""
    return re.findall(r"[a-z0-9]+", s.lower())


def fuse(channels: dict[str, list[dict]], k=RRF_K) -> list[dict]:
    """RRF：只用名次，不比较量纲不同的原始分数。返回 [{id, rrf, evidence: {通道: {rank, score}}}]，同分按 id 排。"""
    evidence = {}
    for ch, rows in channels.items():
        for rank, r in enumerate(rows, 1):
            evidence.setdefault(r["id"], {})[ch] = {"rank": rank, "score": round(r["score"], 4)}
    rrf = {i: sum(1 / (k + e["rank"]) for e in ev.values()) for i, ev in evidence.items()}
    return [{"id": i, "rrf": round(rrf[i], 4), "evidence": evidence[i]} for i in sorted(evidence, key=lambda i: (-rrf[i], i))]
