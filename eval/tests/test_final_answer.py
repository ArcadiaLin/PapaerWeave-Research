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
        # 并列时 method 与 paper 各自排序，成对的关系取自 ranking 中最优值的各行
        rows = [(r["method"], r["paper"]) for r in gold.get("ranking", []) if r["mse"] == gold["mse"]]
        rows = rows or list(zip(gold["method"], gold["paper"], strict=True))
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


def test_t7_own_and_not_stated_may_carry_a_note() -> None:
    text = 'Final answer\n2405.11470 | own (App. A.3: "All the baselines are reproduced")\nPatchTST | not stated. See Table 3\n'
    assert parse("T7", text) == {"entries": [{"paper": "2405.11470", "provenance": "own"},
                                             {"paper": "PatchTST", "provenance": "not stated"}]}  # fmt: skip
    assert parse("T7", "Final answer\nPatchTST | owner of the code\n") is None


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
        reader_prompt("X", probe)


def test_originals_prompt_says_where_the_papers_are_and_that_the_network_is_cut() -> None:
    from pweval.harness.refs import CITE_OUTSIDE_FORMAT, P_NOTE

    text = reader_prompt("P", auto("T1", {}))
    assert text.startswith("Q?\n\n") and P_NOTE in text and FORMATS["T1"] in text
    from pweval.harness.sandbox import ENV_NOTE

    assert "papers/<arXiv id with version>/paper.md" in P_NOTE
    assert text.rstrip().endswith(ENV_NOTE) and "PyYAML" in ENV_NOTE  # 共用的环境说明在末尾（§7 第 5 条）
    assert ENV_NOTE not in reader_prompt("C", auto("T1", {}))
    assert "Cite the papers and lines your answer rests on." in P_NOTE  # §7 第 3 条的说明句
    # 引用放在正文、Final answer 段只放字段：紧接在格式要求之前；要点题没有格式，也就没有这一句
    assert text.index(CITE_OUTSIDE_FORMAT) < text.index("End your reply with")
    manual = {"id": "M-T2-x", "template": "T2", "gold": {"points": []}, "question": "Q?"}
    assert "Cite the papers" in reader_prompt("P", manual) and CITE_OUTSIDE_FORMAT not in reader_prompt("P", manual)
    assert CITE_OUTSIDE_FORMAT not in reader_prompt("C", auto("T1", {}))


# f3 写者组读者的说明句（10-23 用户定稿），逐字写在这里，不从实现中取
STORE_NOTE_FINAL = (
    "Answer only from what the shared store records. The papers and code themselves are not available; "
    "read_evidence reads the source lines at the anchors the store records. Cite the ids, files or anchors "
    "your answer rests on. Do not change the store."
)
# 各组的 TOOLS（tasks/hints.yml，与写者同一句）
STORE_TOOLS = {
    "A3": "Use the PaperWeave tools.",
    "A2": "Use the PaperWeave tools.",
    "A0": "Use the shared repository in this directory.",
    "A4": "Use the Graphiti memory tools.",
}


def test_store_group_prompt_is_question_note_tools_format_env() -> None:
    from pweval.harness.refs import CITE_OUTSIDE_FORMAT
    from pweval.harness.sandbox import ENV_NOTE, PUBLISH_NOTE, WRITER_NOTE

    fmt = format_for(auto("T1", {}))
    manual = {"id": "M-T2-x", "template": "T2", "gold": {"points": []}, "question": "Q?"}
    for group, tools in STORE_TOOLS.items():
        text = reader_prompt(group, auto("T1", {}), tools=tools)
        assert text == "\n\n".join(["Q?", f"{STORE_NOTE_FINAL} {tools}", CITE_OUTSIDE_FORMAT, fmt, ENV_NOTE]) + "\n"
        assert WRITER_NOTE not in text and PUBLISH_NOTE not in text  # 读者没有 read_source，也不发布
        # 要点题：同时省去引用位置说明与 Final answer 段，末尾仍是环境说明
        assert reader_prompt(group, manual, tools=tools) == "\n\n".join(
            ["Q?", f"{STORE_NOTE_FINAL} {tools}", ENV_NOTE]) + "\n"
    # 四组去掉各自的 TOOLS 后逐字相同
    bare = {reader_prompt(g, auto("T1", {}), tools=t).replace(t, "<TOOLS>") for g, t in STORE_TOOLS.items()}
    assert len(bare) == 1
    for bad in (None, "", "   "):
        with pytest.raises(ValueError):
            reader_prompt("A3", auto("T1", {}), tools=bad)


@pytest.mark.skipif(not (PROBES_REPO / "tasks/hints.yml").exists(), reason="题库仓库不在本机")
def test_store_tools_match_hints() -> None:
    import yaml

    hints = yaml.safe_load((PROBES_REPO / "tasks/hints.yml").read_text(encoding="utf-8"))
    assert {g: hints[g.lower()]["TOOLS"] for g in STORE_TOOLS} == STORE_TOOLS


@pytest.mark.skipif(not (PROBES_REPO / "probes/sample.yml").exists(), reason="题库仓库不在本机")
def test_paragraph_group_prompt_puts_material_between_question_and_format() -> None:
    from pweval.harness.refs import D_NOTE, D_SCOPE
    from pweval.harness.timeline import load_timeline
    from pweval.protocol.evidence import Evidence

    timeline, ev = load_timeline(PROBES_REPO), Evidence(PROBES_REPO)
    t5 = next(p for p in timeline.probes if p["template"] == "T5")
    text = reader_prompt("D", t5, ev)
    order = [text.index(t5["question"].strip()), text.index("Passages from these papers"), text.index(D_NOTE),
             text.index(D_SCOPE), text.index("Final answer")]  # fmt: skip
    assert order == sorted(order) and "GOLD" not in text
    t2 = next(p for p in timeline.probes if p["template"] == "T2")
    assert D_SCOPE not in reader_prompt("D", t2, ev) and "Final answer" not in reader_prompt("D", t2, ev)


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
