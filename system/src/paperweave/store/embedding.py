"""向量服务：Qwen3-Embedding-8B（vLLM 的 ``/v1/embeddings``）。写入侧不加任务说明，查询侧由检索加。"""

from __future__ import annotations

import hashlib
import os

import httpx

EMBED_URL = os.environ.get("EMBED_URL", "http://192.168.163.112:8002/v1/embeddings")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "qwen3-embedding-8b")
EMBED_DIM = 4096
EMBED_BATCH = 32


def embed(texts: list[str]) -> list[list[float]]:
    out: list[list[float]] = []
    for i in range(0, len(texts), EMBED_BATCH):
        r = httpx.post(EMBED_URL, json={"model": EMBED_MODEL, "input": texts[i : i + EMBED_BATCH]}, timeout=120)
        r.raise_for_status()
        out += [d["embedding"] for d in sorted(r.json()["data"], key=lambda d: d["index"])]
    if any(len(v) != EMBED_DIM for v in out):
        raise ValueError(f"embedding dimension is not {EMBED_DIM}")
    return out


def embedding_key(text: str) -> str:
    """向量的版本键：模型与输入文本的哈希。文本或模型变了就重算。"""
    return hashlib.sha1(f"{EMBED_MODEL}\n{text}".encode()).hexdigest()[:16]


__all__ = ["EMBED_DIM", "EMBED_MODEL", "EMBED_URL", "embed", "embedding_key"]
