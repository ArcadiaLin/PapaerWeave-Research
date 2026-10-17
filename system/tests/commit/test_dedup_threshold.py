"""查重近似候选的向量阈值：不设在已有的桩上（桩的向量只来自名称，分数偏低）。用假的库，不连 Neo4j。"""

from __future__ import annotations

from typing import Any

from paperweave.query.dedup import VECTOR_MIN, SearchDeduper


class FakeStore:
    """全文一路没有命中；向量一路按给定的分数返回；``stubs`` 是桩。"""

    def __init__(self, scores: dict[str, float], stubs: set[str]) -> None:
        self.scores, self.stubs = scores, stubs

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] for _ in texts]

    def query(self, cypher: str, **params: Any) -> list[dict[str, Any]]:
        if "vector.queryNodes" in cypher:
            return [{"id": i, "score": s} for i, s in sorted(self.scores.items(), key=lambda x: -x[1])]
        if "n.stub = true" in cypher:
            return [{"id": i} for i in params["ids"] if i in self.stubs]
        return []


def test_stub_candidates_skip_the_vector_threshold() -> None:
    low = VECTOR_MIN - 0.05
    store = FakeStore({"dataset_0001": low, "dataset_0002": low}, stubs={"dataset_0002"})
    found = SearchDeduper(store).lookup(  # type: ignore[arg-type]
        "Dataset", name="Electricity", identities=[], description="Hourly load of 321 clients.", stub=False
    )
    assert [c.id for c in found.candidates] == ["dataset_0002"]  # 桩 ECL 留下，分数同样低的非桩被滤掉
