"""草稿文件：Extract、MatrixConstruct 的 ``payload_file`` 与 Commit 的 ``doc_file``（docs/designs/v2/draft_files.md）。

内容来自文件与写在参数里得到同一个产物；被拒时报错指向文件的行；提交记下草稿的路径与哈希。模块内的测试按顺序
共享写入：art_0001 是经文件写入的 Extract，art_0002 是行数多的 Extract，art_0003 是经文件写入的
MatrixConstruct。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import AT, EXTRACT, KEYS, SOURCE

from e09.draft import Workdir
from e09.operators import OPERATORS, Context
from e09.store import Store

EXTRACT_CSV = f"""method,dataset,horizon,mse,source
method_0003,dataset_0001,96,0.375,{SOURCE}
method_0003,dataset_0002,96,0.176,{SOURCE}
"""


@pytest.fixture(scope="module")
def work(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("work")


def call(store: Store, work: Path, op: str, request: dict[str, Any]) -> dict[str, Any]:
    ctx = Context(store, at=AT, session="s-draft", formed_by="claude", workdir=Workdir(work, "/work"))
    return OPERATORS[op].call(ctx, request).details


def by_file(path: str) -> dict[str, Any]:
    """conftest 的 EXTRACT，行改由文件给出。"""
    return {k: EXTRACT[k] for k in ("title", "abs", "inputs", "params")} | {"payload_file": path}


def test_params_alone_give_the_template(store: Store, work: Path) -> None:
    head = store.graph.head()
    out = call(store, work, "Extract", {"params": EXTRACT["params"]})
    assert out["status"] == "template" and store.graph.head() == head
    assert out["header"] == "method,dataset,horizon,mse,split,source"  # 声明的字段加 source
    assert out["example"] == "<id>,<id>,96,0.375,<text>,<material id>::<section>::<start>:<end>"
    bad = call(store, work, "Extract", {"params": {"schema": {"fields": {"source": "string"}, "key": ["source"]}}})
    assert bad["status"] == "rejected" and bad["errors"][0]["at"] == "params.schema.fields.source"
    (work / "any.csv").write_text("x\n", encoding="utf-8")
    undeclared = {"schema": {"fields": {"mse": "number"}, "key": ["method"]}}  # 声明的问题先于表头报告
    for extra in ({}, {"payload_file": "any.csv"}):
        bad = call(store, work, "Extract", {"params": undeclared} | extra)
        assert [e["at"] for e in bad["errors"]] == ["params.schema.key", "params.schema.key"]


def test_rows_from_a_file_write_the_same_artifact_as_inline_rows(store: Store, work: Path) -> None:
    (work / "rows.csv").write_text(EXTRACT_CSV, encoding="utf-8")
    out = call(store, work, "Extract", by_file("/work/rows.csv"))
    assert out["status"] == "created" and out["artifact"] == "art_0001"
    assert "| method_0003-dataset_0001-96 | [method_0003] | [dataset_0001] | 96 | 0.375 | — |" in out["render"]
    record = store.graph.history()[-1]
    sha = hashlib.sha256(EXTRACT_CSV.encode("utf-8")).hexdigest()
    assert record.meta["draft"] == {"path": "/work/rows.csv", "sha256": sha}
    assert yaml.safe_load(record.input)["draft"] == EXTRACT_CSV  # 提交记下调用参数与草稿原文

    many = EXTRACT_CSV + "".join(f"method_0003,dataset_0001,{h},0.4,{SOURCE}\n" for h in range(200, 250))
    (work / "many.csv").write_text(many, encoding="utf-8")
    long = call(store, work, "Extract", by_file("many.csv") | {"title": "Many rows"})
    assert long["status"] == "created" and long["render"].count("\n") == 40  # 回执只给开头几行
    assert long["render"].endswith(f"… 14 more lines, all kept in the document of {long['artifact']}")

    (work / "rows.csv").write_text("changed later\n", encoding="utf-8")  # 草稿之后再改不影响产物
    inline = {k: v for k, v in EXTRACT.items() if k not in ("session", "formed_by", "op")}
    again = call(store, work, "Extract", inline)
    assert again["status"] == "existing" and again["artifact"] == "art_0001"  # 幂等键只看解析后的内容
    assert [k for k in KEYS if f"| {k} |" in again["render"]] == KEYS


def test_rejected_rows_point_at_file_lines(store: Store, work: Path) -> None:
    text = (
        "method,dataset,horizon,mse,source\n"
        f"method_0003,dataset_0001,96,0.4x,{SOURCE}\n"
        f'method_0003,dataset_0002,96,0.2,"{SOURCE.replace("10:12", "50:52")}"\n'
        f"method_0003,dataset_0001,96,0.3,{SOURCE}\n"
    )
    (work / "bad.csv").write_text(text, encoding="utf-8")
    head = store.graph.head()
    out = call(store, work, "Extract", by_file("bad.csv"))
    assert out["status"] == "rejected" and store.graph.head() == head
    assert [(e["at"], e["msg"].split(" is not")[0]) for e in out["errors"]] == [
        ("bad.csv:2 (mse)", "not a number: '0.4x'"),
        ("bad.csv:4", "key 'method_0003-dataset_0001-96' repeats line 2"),
        ("bad.csv:3 (source)", "paper_0001::5.2 Comparison::50:52"),  # 不在 inputs 的行范围内
    ]


def test_file_and_inline_rows_are_not_both_given(store: Store, work: Path) -> None:
    out = call(store, work, "Extract", by_file("rows.csv") | {"payload": {"rows": []}})
    assert out["status"] == "rejected" and out["errors"][0]["at"] == "payload.rows"
    (work / "header.csv").write_text("method,dataset,horizon,mse,source\n", encoding="utf-8")
    empty = call(store, work, "Extract", by_file("header.csv"))
    assert empty["errors"] == [
        {"rule": "schema", "at": "payload.note", "msg": "an empty result needs a note: what was read and why nothing was found"}
    ]
    bad = "".join(f"method_0003,dataset_0001,{h},x,{SOURCE}\n" for h in range(40))
    (work / "bad40.csv").write_text("method,dataset,horizon,mse,source\n" + bad, encoding="utf-8")
    out = call(store, work, "Extract", by_file("bad40.csv"))
    assert len(out["errors"]) == 31  # 每行都错时只列前 30 条
    assert out["errors"][-1] == {
        "rule": "more",
        "at": "",
        "msg": "10 more errors not shown (schema x10); fix the ones above, then call again",
    }
    out = call(store, work, "Extract", by_file("../outside.csv"))
    assert out["errors"][0]["at"] == "payload_file"


MATRIX = {
    "title": "DLinear across datasets",
    "abs": "DLinear MSE at horizon 96 on two datasets, for the drafts test.",
    "inputs": ["method_0003", "art_0001"],
    "params": {
        "rows": {"dlinear": "method_0003"},
        "columns": {"etth1": {"text": "ETTh1 MSE"}, "weather": {"text": "Weather MSE"}},
        "cell": {"type": "number"},
    },
}


def test_matrix_cells_come_from_a_long_csv(store: Store, work: Path) -> None:
    template = call(store, work, "MatrixConstruct", {"params": MATRIX["params"]})
    assert template["header"] == "row,col,value,basis,note"
    assert template["example"].startswith("dlinear,etth1,0.375,")
    a, b = (f"art_0001#{k}" for k in KEYS)
    text = f'row,col,value,basis,note\ndlinear,etth1,0.375,{a},\ndlinear,weather,,"{a}; {b}",not reported\n'
    (work / "m.csv").write_text(text, encoding="utf-8")
    out = call(store, work, "MatrixConstruct", MATRIX | {"payload_file": "m.csv"})
    assert out["status"] == "created" and out["artifact"] == "art_0003"
    assert "| dlinear | 0.375 [art_0001#method_0003-dataset_0001-96] |" in out["render"]
    assert "`dlinear~weather`: not reported" in out["render"]

    (work / "m2.csv").write_text("row,col,value\ndlinear,etth1,x\nlinear,weather,1\n", encoding="utf-8")
    out = call(store, work, "MatrixConstruct", MATRIX | {"payload_file": "m2.csv"})
    assert [(e["at"], e["msg"]) for e in out["errors"]] == [
        ("m2.csv:2 (value)", "not a number: 'x'"),
        ("m2.csv:3 (row)", "not a declared row: 'linear'"),
        ("m2.csv", "missing cells: dlinear~weather"),
    ]


DOC = """graph-doc: v0.1
nodes:
  $obs:
    kind: Observation
    text: DLinear's MSE on Weather is lower than on ETTh1.
    ABOUT: [method_0003]
    FROM:
      - to: art_0003
  $bad:
    kind: Gadget
    name: x
"""


def test_commit_reads_a_doc_file_and_applies_when_nothing_blocks(store: Store, work: Path) -> None:
    (work / "doc.yml").write_text(DOC, encoding="utf-8")
    head = store.graph.head()
    out = call(store, work, "Commit", {"doc_file": "doc.yml", "message": "an observation"})
    assert out["status"] == "blocked" and store.graph.head() == head
    assert [e["at"] for e in out["errors"]] == ["doc.yml:10 (nodes.$bad.kind)"]

    fixed = DOC[: DOC.index("  $bad:")]
    (work / "doc.yml").write_text(fixed, encoding="utf-8")
    out = call(store, work, "Commit", {"doc_file": "doc.yml", "message": "an observation"})  # 不加 apply 即提交
    assert out["status"] == "committed"
    record = store.graph.history()[-1]
    assert record.input == fixed and record.meta["draft"]["path"] == "doc.yml"

    preview = call(store, work, "Commit", {"doc": fixed.replace("lower", "much lower"), "apply": False})
    assert preview["status"] == "ready"  # apply: false 只预览
    assert store.graph.history()[-1].id == record.id
    both = call(store, work, "Commit", {"doc": fixed, "doc_file": "doc.yml"})
    assert both["status"] == "rejected" and both["errors"][0]["at"] == "doc"
    (work / "broken.yml").write_text("nodes:\n  $a: {kind: Task\n  $b: 1\n", encoding="utf-8")
    broken = call(store, work, "Commit", {"doc_file": "broken.yml"})
    assert broken["status"] == "rejected" and broken["errors"][0]["at"].startswith("broken.yml:")
