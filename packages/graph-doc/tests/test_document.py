"""语法层：v0.2 的三节、关系的映射写法、文档内引用与 YAML 标量。"""

from __future__ import annotations

import pytest

from graph_doc import DocError, parse


def problems(text: str) -> list[str]:
    with pytest.raises(DocError) as err:
        parse(text)
    return err.value.problems


PAPER_FORM = """
graph-doc: v0.2
create:
  $paper:
    kind: Paper
    name: "A Time Series is Worth 64 Words: Long-term Forecasting with Transformers"
    identities: [arxiv:2211.14730]
    year: 2023
    extra:
      venue: ICLR 2023
      authors: [Yuqi Nie, Nam H. Nguyen]
    CITES:
      paper_0005:
        description: |
          DLinear numbers in Table 3 are copied from this paper.
        anchor: [330:331]
  $patchtst:
    kind: Method
    name: PatchTST
  $exp:
    kind: Experiment
    paper: $paper
    anchor: [318:342, 655:690]
    figures: [S4.T3]
    ON_TASK: [task_0001]
    EVALUATES:
      $patchtst:
        role: target
      method_0021:
        role: baseline
        result: cited
  method_0036:
    RELATES_TO:
      method_0040:
        description: uses it as a component
confirm:
  $patchtst:
    distinct_from: [method_0007]
"""


def test_paper_form() -> None:
    doc = parse(PAPER_FORM)
    assert doc.version == "v0.2"
    assert doc.temp_refs() == ["$paper", "$patchtst", "$exp"]
    exp = doc.create["$exp"]
    assert exp.props["anchor"] == ["318:342", "655:690"]  # 行号范围保持字符串
    assert exp.rels["ON_TASK"]["task_0001"].props == {}
    assert exp.rels["EVALUATES"]["method_0021"].props == {"role": "baseline", "result": "cited"}
    assert doc.create["$paper"].props["extra"] == {"venue": "ICLR 2023", "authors": ["Yuqi Nie", "Nam H. Nguyen"]}
    assert doc.create["method_0036"].props == {}
    assert doc.confirm == {"$patchtst": {"distinct_from": ["method_0007"]}}


def test_set_delete_and_readonly_fields() -> None:
    doc = parse(
        """
graph-doc: v0.2
set:
  exp_0042:
    kind: Experiment
    description: |
      New text.
    _edges_in: {SUPPORTS: 2}
    USES:
      dataset_0004:
        role: training_data
        _formed_by: someone
delete:
  exp_0042:
    USES: [dataset_0012]
  claim_0107:
"""
    )
    assert doc.set["exp_0042"].props == {"kind": "Experiment", "description": "New text.\n"}
    assert doc.set["exp_0042"].rels["USES"]["dataset_0004"].props == {"role": "training_data"}
    assert doc.delete == {"exp_0042": {"USES": ["dataset_0012"]}, "claim_0107": None}
    assert doc.deleted_nodes() == ["claim_0107"]


def test_change_an_edge_target_in_one_file() -> None:
    doc = parse(
        """
graph-doc: v0.2
delete:
  exp_0042:
    USES: [dataset_0003]
create:
  exp_0042:
    USES:
      dataset_0005:
        role: evaluation_data
"""
    )
    assert doc.refs() == ["exp_0042"]


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("create: {}", "graph-doc: the format version is required"),
        ("graph-doc: v0.1\n", "unsupported version"),
        ("graph-doc: v0.2\nnodes: {}\n", "v0.2 uses create, set and delete"),
        ("graph-doc: v0.2\nmessage: hi\n", "message: unknown top-level key"),
        ("graph-doc: v0.2\nset:\n  $x:\n    name: X\n", "set changes existing nodes"),
        ("graph-doc: v0.2\ncreate:\n  method_0001:\n    name: X\n", "only takes new relationships"),
        ("graph-doc: v0.2\ndelete:\n  $x:\n", "cannot be deleted"),
        ("graph-doc: v0.2\ncreate:\n  $a:\n    kind: Method\n    BROADER: [$b]\n", "$b is not defined under create"),
        (
            "graph-doc: v0.2\ncreate:\n  $a:\n    kind: Method\n    BROADER:\n      - {to: method_0001}\n",
            "write the target as a key",
        ),
        (
            "graph-doc: v0.2\ncreate:\n  $a:\n    kind: Method\n    BROADER:\n      method_0001:\n        to: x\n",
            "do not write to",
        ),
        ("graph-doc: v0.2\nset:\n  method_0001:\n    name: X\ndelete:\n  method_0001:\n", "is deleted in this file"),
        (
            "graph-doc: v0.2\nset:\n  exp_1:\n    USES:\n      d_1: {role: x}\ndelete:\n  exp_1:\n    USES: [d_1]\n",
            "this edge also appears under",
        ),
        ("graph-doc: v0.2\ndelete:\n  exp_1:\n    name: x\n", "lists only relationship types"),
        ("graph-doc: v0.2\nset:\n  m_1:\n    Name: x\n", "field names are lowercase"),
        ("graph-doc: v0.2\nset:\n  m_1:\n    extra: {a: {b: 1}}\n", "one level deep"),
        ("graph-doc: v0.2\nset:\n  m_1:\n    name: a\n    name: b\n", "duplicate key"),
    ],
)
def test_problems(text: str, problem: str) -> None:
    found = problems(text)
    assert any(problem in p for p in found), found


def test_yaml_scalars_stay_strings() -> None:
    doc = parse("graph-doc: v0.2\nset:\n  m_1:\n    a: 52:58\n    b: yes\n    c: 012\n    d: 2026-10-04\n    e: 3\n")
    assert doc.set["m_1"].props == {"a": "52:58", "b": "yes", "c": 12, "d": "2026-10-04", "e": 3}
