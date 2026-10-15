"""Resolve 的解析视图：引用带名称、别名与说明的开头，近似对象在 similar 中，匹配过程不进入视图。"""

from __future__ import annotations

from typing import Any

import pytest

from paperweave.operators.db import resolve

ROWS = {
    "method_0003": {
        "labels": ["Concept", "Method"],
        "name": "DLinear",
        "about": "x" * 300,
        "raws": ["DLinear", "D-Linear"],
    },
    "method_0001": {"labels": ["Concept", "Method"], "name": "Linear model", "about": "Linear maps.", "raws": []},
}


@pytest.fixture(autouse=True)
def rows(monkeypatch: pytest.MonkeyPatch) -> None:
    def q(cypher: str, ids: list[str]) -> list[dict[str, Any]]:
        return [{"id": i, **ROWS[i]} for i in ids if i in ROWS]

    monkeypatch.setattr(resolve, "q", q)


def result(status: str, refs: list[str], trace: list[dict[str, Any]], channels: dict[str, str]) -> dict[str, Any]:
    return {
        "stage": "alias",
        "status": status,
        "refs": refs,
        "match_trace": trace,
        "states": {"issues": []},
        "coverage": {"channels": channels},
    }


def test_refs_carry_names_and_the_trace_stays_out() -> None:
    near = {"stage": "semantic", "role": "dedup", "candidates": [{"id": "method_0001", "rrf": 0.1}]}
    trace = [{"stage": "alias", "key": "DLinear|Method|global", "hits": ["method_0003"]}, near]
    out = resolve.view(result("resolved", ["method_0003"], trace, {"semantic": "ok (5)"}))
    assert list(out) == ["status", "refs", "similar"]
    ref = out["refs"][0]
    assert ref["name"] == "DLinear" and ref["kind"] == "Method" and ref["aliases"] == ["D-Linear"]
    assert ref["about"].endswith("…") and len(ref["about"].encode()) <= resolve.ABOUT_BYTES
    assert out["similar"] == [{"id": "method_0001", "kind": "Method", "name": "Linear model", "about": "Linear maps."}]


def test_semantic_results_are_refs_and_failed_channels_are_reported() -> None:
    top = {"stage": "semantic", "role": "result", "candidates": [{"id": "method_0001"}]}
    channels = {"lexical_name": "ok (1)", "semantic": "error: ConnectError: refused"}
    out = resolve.view(result("candidates", ["method_0001"], [top], channels))
    assert [r["id"] for r in out["refs"]] == ["method_0001"] and "similar" not in out
    assert out["failed"] == {"semantic": "error: ConnectError: refused"}
