"""兜底修复：参数按算子的 schema 修成声明的形状，来源引用按规范写法解析；修复只记在 Result.repairs 中。不连库。"""

from __future__ import annotations

from typing import Any

import pytest

from paperweave.model.refs import normalize_ref, parse_ref
from paperweave.operators import OPERATORS
from paperweave.operators.base import STRING, Operator, Result, one_or_many, schema
from paperweave.operators.repair import repair

# 嵌套的三值判断：取自已下线的旧版 Check 的参数形状，用来检验修复沿 schema 深入对象与数组
JUDGMENT = schema({"value": {"enum": ["T", "F", "U"]}, "basis": one_or_many(STRING), "reason": STRING})
CHECK = schema(
    {
        "abs": STRING,
        "params": schema({"items": {"type": "object"}}),
        "payload": schema({"judgments": {"type": "array", "items": JUDGMENT}}),
    }
)
SEARCH = OPERATORS["Search"].parameters


def test_json_text_is_parsed_into_the_declared_type() -> None:
    payload = '{"judgments": [{"pair": ["a", "b"], "dimension": "d", "value": "T", "basis": ["x"]}]'  # 少了 }
    out, notes = repair(CHECK, {"payload": payload, "params": '```json\n{"items": {}}\n```', "abs": "[not json"})
    assert out["payload"]["judgments"][0]["pair"] == ["a", "b"]
    assert out["params"] == {"items": {}}
    assert out["abs"] == "[not json"  # 声明为字符串的参数不动
    assert notes == ["payload: JSON text parsed", "params: JSON text parsed"]  # 按请求中的顺序


def test_text_that_is_not_json_is_left_for_the_operator() -> None:
    out, notes = repair(SEARCH, {"type": "Entity", "kinds": "Paper", "query": "PatchTST"})
    assert out == {"type": "Entity", "kinds": "Paper", "query": "PatchTST"} and notes == []


@pytest.mark.parametrize(
    ("request_", "expected", "note"),
    [
        ({"type": "content"}, {"type": "Content"}, "type: 'content' read as 'Content'"),
        ({"budget": "15"}, {"budget": 15}, "budget: '15' read as integer"),
        ({"kinds": '["Paper", "Dataset"]'}, {"kinds": ["Paper", "Dataset"]}, "kinds: JSON text parsed"),
    ],
)
def test_scalars_enums_and_arrays(request_: dict[str, Any], expected: dict[str, Any], note: str) -> None:
    assert repair(SEARCH, request_) == (expected, [note])


def test_judgment_values_and_nested_one_or_many() -> None:
    payload = {
        "judgments": [
            {"pair": ["a", "b"], "dimension": "d", "value": True, "basis": '["x", "y"]'},
            {"pair": ["a", "b"], "dimension": "e", "value": "u", "reason": "r"},
        ]
    }
    out, notes = repair(CHECK, {"payload": payload})
    first, second = out["payload"]["judgments"]
    assert first["value"] == "T" and first["basis"] == ["x", "y"] and second["value"] == "U"
    assert notes == [
        "payload.judgments[0].value: True read as T",
        "payload.judgments[0].basis: JSON text parsed",
        "payload.judgments[1].value: 'u' read as 'U'",
    ]


def test_the_operator_runs_on_the_repaired_request_and_keeps_the_notes() -> None:
    op = Operator("Echo", "db", SEARCH, lambda ctx, request: dict(request))
    result = op.call(None, {"type": "Entity", "kinds": '["Paper"'})  # type: ignore[arg-type]
    assert isinstance(result, Result) and result.details == {"type": "Entity", "kinds": ["Paper"]}
    assert result.repairs == ("kinds: JSON text parsed",) and "repaired" not in result.text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("material_1ec346c934e6::5.1 Setup::174:196", "material_1ec346c934e6::5.1 Setup::174:196"),
        (" `material_1ec346c934e6 :: 5.1 Setup :: 174-196` ", "material_1ec346c934e6::5.1 Setup::174:196"),
        ("[paper_0001::5.1 Setup::L174–L196]", "paper_0001::5.1 Setup::174:196"),
        ("paper_0001::5.1 Setup::lines 174 - 196", "paper_0001::5.1 Setup::174:196"),
        ("paper_0001::5.1 Setup::174", "paper_0001::5.1 Setup::174:174"),
        ("'exp_0012'", "exp_0012"),
        ("art_0003#dlinear-etth1-96", "art_0003#dlinear-etth1-96"),
    ],
)
def test_source_references_are_normalized(text: str, expected: str) -> None:
    assert normalize_ref(text) == expected
    ref = parse_ref(text)
    assert ref is not None and ref.text == expected
