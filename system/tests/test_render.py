"""读取工具的带注释 YAML：去掉注释后仍是同样的数据。不连库。"""

from __future__ import annotations

from graph_doc import load
from paperweave.query.render import render


def test_a_list_of_mappings_renders_as_blocks_and_reads_back() -> None:
    data = {"art_0001": {"_stale": [{"ref": "paper_0004", "reason": "uncovered"}, {"ref": "exp_0001", "reason": "revised"}]}}
    text = render(data, {"paper_0004": "TimeMachine"})
    assert "    - ref: paper_0004" in text and "# TimeMachine" in text
    assert load(text) == data


def test_comments_follow_the_value_without_column_padding() -> None:
    data = {"exp_0016": {"kind": "Experiment", "EVALUATES": {"method_0001": {"role": "baseline"}}}}
    text = render(data, {"exp_0016": "Full ETT benchmark", "method_0001": "Informer"})
    assert "exp_0016:  # Full ETT benchmark\n" in text
    assert "    method_0001:  # Informer\n" in text
    assert load(text) == data
