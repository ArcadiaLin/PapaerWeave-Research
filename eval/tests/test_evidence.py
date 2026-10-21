"""逐题的依据材料（docs/designs/v3/evaluation.md §10.1）：锚点展开、D 材料不含答案与指认、封闭世界补表、出错即停。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from pweval.protocol.evidence import Evidence, build, judge_material, merge, reader_material

PAPER = "1234.56789v1"
OTHER = "2222.22222v2"
TEXT = (
    "Title: Old title\n\nA full paragraph starts here.\nWindow = 512.\nThe same paragraph ends here.\n\n"
    "Table 1: main results\n| Model | MSE |\n| --- | --- |\n| A | 0.2 |\n\nOther text.\n"
)


@pytest.fixture
def ev(tmp_path: Path) -> Evidence:
    bank, papers, code = tmp_path / "bank", tmp_path / "papers", tmp_path / "code"
    for p in (bank / "facts/papers", bank / "probes", bank / "tasks", papers / PAPER, papers / OTHER,
              code / "repo@abcdef12"):  # fmt: skip
        p.mkdir(parents=True)
    (papers / PAPER / "paper.md").write_text(TEXT)
    (papers / OTHER / "paper.md").write_text("Title: B\n\nTable 3: later results\n| Model | MSE |\n| B | 0.3 |\n")
    (code / "repo@abcdef12/run.py").write_text("".join(f"line {i}\n" for i in range(1, 31)))
    aliases = {"papers": {"1234.56789": {"title": "New title", "proposes": "A"},
                          "2222.22222": {"title": "Later paper", "proposes": "B"}}}  # fmt: skip
    (bank / "facts/aliases.yml").write_text(yaml.safe_dump(aliases))
    dates = {"1234.56789": {"1": "Mon, 01 Jan 2024"}, "2222.22222": {"1": "Mon, 01 Jul 2024"}}
    (bank / "facts/arxiv_versions.json").write_text(json.dumps(dates))
    (bank / "facts/tables.csv").write_text(f"table,arxiv,first,last,number\n{PAPER}:T7,{PAPER},7,10,1\n"
                                           f"{OTHER}:T3,{OTHER},3,5,3\n")  # fmt: skip
    (bank / "facts/own.yml").write_text("[]\n")
    for paper, table in ((PAPER, "T7"), (OTHER, "T3")):
        fact = {"tables": [{"table": f"{paper}:{table}", "role": "main", "variate": "multivariate"}]}
        (bank / f"facts/papers/{paper}.yml").write_text(yaml.safe_dump(fact))
    (bank / "tasks/reader.yml").write_text(yaml.safe_dump({"seed_papers": [PAPER]}))
    (bank / "tasks/plan.yml").write_text(yaml.safe_dump([{"type": "build", "paper": OTHER},
                                                         {"type": "checkpoint", "papers": 30}]))  # fmt: skip
    return Evidence(bank, papers, code)


def probe(**changes: object) -> dict:
    base = {"id": "M-example", "template": "T2", "question": "Which input window?", "requires": [PAPER],
            "slots": {"P": PAPER}, "refs": {"P": {"text": "the named paper"}}, "evidence": [f"{PAPER}:4"],
            "gold": {"points": [{"id": "a", "text": "GOLD-SECRET", "anchor": f"{PAPER}:4"}]},
            "scoring": "Mean over points."}  # fmt: skip
    return base | changes


def test_anchors_expand_to_paragraphs_tables_and_code_context(ev: Evidence) -> None:
    assert ev.expand(f"{PAPER}:4") == (PAPER, 3, 5)
    assert ev.expand(f"{PAPER}:10") == (PAPER, 7, 10)  # 表内的行扩展为整表
    assert ev.expand(f"{PAPER}:T7") == (PAPER, 7, 10)
    assert ev.expand("repo@abcdef1234:run.py:15") == ("repo@abcdef1234:run.py", 7, 23)
    with pytest.raises(ValueError, match="outside"):
        ev.expand(f"{PAPER}:999")
    assert merge([(3, 5), (4, 7), (10, 12)]) == [(3, 7), (10, 12)]


def test_reader_material_has_no_answer_no_pointer_and_keeps_line_numbers(ev: Evidence) -> None:
    reader, judge = reader_material(ev, probe()), judge_material(ev, probe())
    assert "GOLD-SECRET" not in reader and "Mean over points." not in reader and "the named paper" not in reader
    assert "    4\tWindow = 512." in reader and "New title (arXiv 1234.56789v1)" in reader
    assert "Later paper (arXiv 2222.22222v2; first arXiv version Mon, 01 Jul 2024)" in reader
    assert "GOLD-SECRET" in judge and "Mean over points." in judge and "题面中的“the named paper”指这篇论文" in judge


def test_set_questions_get_every_main_table_but_judges_do_not(ev: Evidence) -> None:
    t5 = probe(template="T5", gold={"beaten": [], "later_papers": {}}, evidence=[f"{PAPER}:T7"])
    assert "| B | 0.3 |" in reader_material(ev, t5)  # 封闭世界：库中每篇论文的主结果表
    assert "| B | 0.3 |" not in judge_material(ev, t5)
    assert "| B | 0.3 |" not in reader_material(ev, probe())  # 单篇题不补


def test_judge_only_background_stays_out_of_the_reader(ev: Evidence) -> None:
    p = probe()
    p["gold"]["notes"] = [{"text": "background", "anchor": f"{PAPER}:12"}]
    assert "Other text." not in reader_material(ev, p) and "Other text." in judge_material(ev, p)


def test_unresolvable_evidence_stops_instead_of_giving_partial_material(ev: Evidence) -> None:
    bad = probe(evidence=[f"{PAPER}:999", "unsupported.json"])
    assert len(ev.material(bad).errors) == 2
    with pytest.raises(ValueError):
        reader_material(ev, bad)


def test_build_is_reproducible_and_refuses_a_used_directory(ev: Evidence, tmp_path: Path) -> None:
    (ev.bank / "probes/auto.yml").write_text("[]\n")
    (ev.bank / "probes/manual-rendered.yml").write_text(yaml.safe_dump([probe()]))
    (ev.bank / "probes/sample.yml").write_text(yaml.safe_dump([{"id": "M-example"}]))
    one, two = tmp_path / "one", tmp_path / "two"
    build(ev, one)
    build(ev, two)
    assert {p.relative_to(one): p.read_bytes() for p in one.rglob("*") if p.is_file()} == {
        p.relative_to(two): p.read_bytes() for p in two.rglob("*") if p.is_file()}
    with pytest.raises(ValueError, match="must be empty"):
        build(ev, one)
