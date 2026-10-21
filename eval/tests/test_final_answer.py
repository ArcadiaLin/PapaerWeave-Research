"""Final answer 段：按题型生成格式要求，用正则解析回结构化字段（docs/designs/v3/evaluation.md §7 第 3 条）。

由金标准渲染出“标准答案”的 Final answer 段，解析后应还原出计分所需的字段：格式覆盖了每个题型的计分依据。
题库仓库在本机时，对 200 道主题逐题检查；不在时跳过这一项。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pweval.harness.refs import C_NOTE, reader_prompt
from pweval.protocol.final_answer import FORMATS, format_for, parse, section

PROBES_REPO = Path("~/pw-lab/probes").expanduser()


def auto(template: str, gold: dict) -> dict:
    return {"id": f"{template}-x", "template": template, "answer_type": "value", "gold": gold, "question": "Q?"}


def render(template: str, gold: dict) -> str:
    """金标准对应的 Final answer 段（论文写 arXiv 编号）。"""
    if template == "T1":
        body = [f"MSE: {gold['mse']}", f"MAE: {gold['mae']}", f"Location: Table {gold['table']}"]
    elif template == "T3":
        rows = zip(gold["method"], gold["paper"], strict=False)
        body = [f"{m} | {p} | {gold['mse']} | {gold['lookback']}" for m, p in rows]
    elif template in ("T4", "T6"):
        body = list(gold["methods" if template == "T4" else "dropped"]) or ["none"]
    elif template == "T5":
        pairs = [f"{b} | {p}" for b, ps in gold["later_papers"].items() for p in ps]
        body = ["Beaten:", *(gold["beaten"] or ["none"]), "Later papers:", *(pairs or ["none"])]
    elif template == "T7":
        said = {"cited": "cited: {from}", "not stated": "not stated"}
        body = [f"{e['paper']} | {said.get(e['source'], 'own').format(**e)}" for e in gold["entries"]]
    else:
        body = [f"{p} | {g['mse']}" for g in gold["groups"] for p in g["papers"]]
    return "Some reasoning first.\n\n## Final answer\n" + "\n".join(body) + "\n"


def expected(template: str, gold: dict) -> dict:
    """解析结果中与计分对应的部分。"""
    if template == "T1":
        return {"mse": float(gold["mse"]), "mae": float(gold["mae"])}
    if template == "T3":
        return {"methods": sorted(gold["method"]), "mse": float(gold["mse"])}
    if template in ("T4", "T6"):
        return {"methods": sorted(gold["methods" if template == "T4" else "dropped"])}
    if template == "T5":
        pairs = sorted((b, p) for b, ps in gold["later_papers"].items() for p in ps)
        return {"beaten": sorted(gold["beaten"]), "pairs": pairs}
    if template == "T7":
        return {"papers": sorted(e["paper"] for e in gold["entries"])}
    return {"pairs": sorted((p, float(g["mse"])) for g in gold["groups"] for p in g["papers"])}


def observed(template: str, parsed: dict) -> dict:
    if template == "T1":
        return {"mse": float(parsed["mse"]), "mae": float(parsed["mae"])}
    if template == "T3":
        return {"methods": sorted(r["method"] for r in parsed["best"]), "mse": float(parsed["best"][0]["mse"])}
    if template in ("T4", "T6"):
        return {"methods": sorted(parsed["methods"])}
    if template == "T5":
        pairs = sorted((p["baseline"], p["paper"]) for p in parsed["later_papers"])
        return {"beaten": sorted(parsed["beaten"]), "pairs": pairs}
    if template == "T7":
        return {"papers": sorted(e["paper"] for e in parsed["entries"])}
    return {"pairs": sorted((p["paper"], float(p["mse"])) for p in parsed["pairs"])}


def test_every_auto_template_has_a_format_and_manual_probes_have_none() -> None:
    for template in FORMATS:
        text = format_for(auto(template, {}))
        assert text is not None and "Final answer" in text and FORMATS[template] in text
    manual = {"id": "M-T2-x", "template": "T2", "gold": {"points": [{"id": "a", "text": "t"}]}, "question": "Q?"}
    assert format_for(manual) is None
    assert format_for(auto("T9", {})) is None


def test_the_last_final_answer_heading_wins_and_fences_are_dropped() -> None:
    text = "Final answer\nMSE: 1\n\nMore thinking.\n\n**Final answer:**\n```\nMSE: 0.37\nMAE: 0.4\n```\n"
    assert section(text) == "MSE: 0.37\nMAE: 0.4"
    assert section("no heading here") is None
    assert parse("T1", text) == {"mse": "0.37", "mae": "0.4", "location": None}


def test_each_template_parses_its_rendered_gold() -> None:
    golds = {
        "T1": {"mse": 0.577, "mae": 0.549, "table": 2},
        "T3": {"method": ["SCINet"], "paper": ["2106.09305v3"], "mse": 0.408, "lookback": "336"},
        "T4": {"methods": ["DLinear", "RLinear"]},
        "T5": {"beaten": ["PatchTST", "GPT4TS"], "later_papers": {"PatchTST": ["2406.03751v2", "2406.09009v4"]}},
        "T6": {"dropped": []},
        "T7": {"entries": [{"paper": "2211.14730v2", "source": "cited", "from": "DLinear"},
                           {"paper": "2403.01673v1", "source": "not stated", "from": ""},
                           {"paper": "2310.09751v3", "source": "run", "from": ""}]},
        "T8": {"groups": [{"mse": 0.342, "papers": ["2406.03751v2"]},
                          {"mse": 0.412, "papers": ["2412.17323v3", "2501.19065v3"]}]},
    }  # fmt: skip
    for template, gold in golds.items():
        parsed = parse(template, render(template, gold))
        assert parsed is not None, template
        assert observed(template, parsed) == expected(template, gold), template
    t7 = parse("T7", render("T7", golds["T7"]))["entries"]
    assert [e["provenance"] for e in t7] == ["cited", "not stated", "own"] and t7[0]["from"] == "DLinear"


def test_list_markers_bold_and_none_are_tolerated() -> None:
    assert parse("T4", "Final answer\n- **DLinear**\n- `RLinear`\n") == {"methods": ["DLinear", "RLinear"]}
    assert parse("T6", "### Final answer\nnone\n") == {"methods": []}
    assert parse("T8", "Final answer\n1. PatchTST paper | 0.370 | Table 3\n") == {
        "pairs": [{"paper": "PatchTST paper", "mse": "0.370", "table": "Table 3"}]
    }


def test_malformed_sections_do_not_parse() -> None:
    assert parse("T1", "Final answer\nThe MSE is 0.37.") is None
    assert parse("T5", "Final answer\nBeaten:\nPatchTST\n") is None  # 缺 Later papers
    assert parse("T7", "Final answer\nPatchTST | maybe\n") is None
    assert parse("T3", "Final answer\nSCINet\n") is None


def test_closed_book_prompt_has_question_note_and_format() -> None:
    probe = auto("T1", {})
    text = reader_prompt("C", probe)
    assert text.startswith("Q?\n\n") and C_NOTE in text and FORMATS["T1"] in text and "{" not in text
    manual = {"id": "M-T2-x", "template": "T2", "gold": {"points": []}, "question": "Q?"}
    assert "Final answer" not in reader_prompt("C", manual)
    with pytest.raises(NotImplementedError):
        reader_prompt("P", probe)


@pytest.mark.skipif(not (PROBES_REPO / "probes/sample.yml").exists(), reason="题库仓库不在本机")
def test_gold_of_every_sampled_auto_probe_round_trips() -> None:
    from pweval.harness.timeline import load_timeline

    timeline = load_timeline(PROBES_REPO)
    autos = [p for p in timeline.probes if format_for(p)]
    assert len(autos) == 160 and all(format_for(p) is None for p in timeline.probes if p not in autos)
    for probe in autos:
        template, gold = probe["template"], probe["gold"]
        parsed = parse(template, render(template, gold))
        assert parsed is not None and observed(template, parsed) == expected(template, gold), probe["id"]
