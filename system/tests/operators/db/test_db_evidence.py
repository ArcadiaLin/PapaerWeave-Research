"""ReadEvidence：按来源引用读行；材料缺失、文件改动与越界都不返回文本。命令行入口的请求检查。"""

from __future__ import annotations

import dataclasses
import shutil
from pathlib import Path

import pytest
from conftest import AT, MATERIAL

from paperweave.operators import Context
from paperweave.operators.db.read_evidence import read_evidence
from paperweave.operators.db.traverse import traverse
from paperweave.store import Store
from paperweave.tools import call


def material_id(store: Store) -> str:
    return traverse(store, ["paper_0001"])["nodes"]["paper_0001"]["_material"]


def test_reads_numbered_lines_by_material_or_paper(store: Store) -> None:
    material = material_id(store)
    out = read_evidence(store, [f"{material}::5.2 Comparison::10:12", "paper_0001::5.1::21:21"])
    first, second = out["items"]
    assert first["state"] == "available" and first["path"] == MATERIAL
    assert first["text"] == "10| line 10\n11| line 11\n12| line 12\n"
    assert second["material"] == material and second["text"] == "21| line 21\n"
    assert out["coverage"] == {"requested": 2, "available": 2, "missing": 0, "error": 0}


def test_source_refs_from_a_view_can_be_read_back(store: Store) -> None:
    refs = traverse(store, ["exp_0001"])["meta"]["source_refs"]
    out = read_evidence(store, refs)
    assert [item["state"] for item in out["items"]] == ["available", "available"]


def test_at_resolves_references_in_a_past_state(store: Store) -> None:
    refs = ["paper_0001::5.1::21:21"]
    first = store.graph.history()[0].id  # 种子：那时还没有论文
    now = read_evidence(store, refs, at="main")
    assert now["items"] == read_evidence(store, refs)["items"] and now["coverage"]["at"] == store.graph.head()
    assert read_evidence(store, refs, at=first)["missing"] == refs


def test_unreadable_references(store: Store, tmp_path: Path) -> None:
    material = material_id(store)
    out = read_evidence(store, ["garbage", "material_nope::a::1:2", f"{material}::a::59:61"])
    assert [item["state"] for item in out["items"]] == ["missing", "missing", "error"]
    assert "text" not in out["items"][2]
    assert out["missing"] == ["garbage", "material_nope::a::1:2"]

    changed = tmp_path / "root"
    shutil.copytree(store.material_root, changed)
    (changed / MATERIAL).write_text("edited\n" * 60, encoding="utf-8")
    item = read_evidence(dataclasses.replace(store, material_root=changed), [f"{material}::a::1:2"])["items"][0]
    assert item["state"] == "error" and "sha256" in item["reason"] and "text" not in item

    gone = read_evidence(dataclasses.replace(store, material_root=tmp_path / "empty"), [f"{material}::a::1:2"])
    assert gone["items"][0]["state"] == "missing"


@pytest.mark.parametrize(
    ("request_", "at"),
    [
        ({"op": "Get"}, ["op"]),
        ({"op": "Traverse"}, ["start"]),
        ({"op": "Traverse", "start": ["exp_0001"], "hops": []}, ["hops"]),
        ({"op": "ReadEvidence", "source_refs": []}, ["source_refs"]),
    ],
)
def test_requests_are_checked(store: Store, request_: dict, at: list[str]) -> None:
    out = call(Context(store, AT), request_)
    assert out.details["status"] == "rejected" and [p["at"] for p in out.details["errors"]] == at


def test_call_dispatches_to_the_operator(store: Store) -> None:
    out = call(Context(store, AT), {"op": "Search", "type": "Entity", "kinds": ["Paper"]})
    assert not out.is_error and [r["id"] for r in out.details["results"]] == ["paper_0001"]
