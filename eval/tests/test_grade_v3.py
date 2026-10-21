"""V3 判分：名称归一与按题型计分（docs/designs/v3/evaluation.md §5.4；tmps/probes/grading-plan.md 第 9 节）。

金标准自洽：由金标准渲染的 Final answer 段，补上待判条目的“正确”判定后，每道自动题都得 1；去掉一项、加一项错项时，
得分按 ``scoring`` 的规则下降。题库仓库在本机时对 200 道主题逐题检查。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from test_final_answer import render

from pweval.measure.grade_v3 import f1, grade, same
from pweval.measure.names import NOT_METHOD, Names, Tables, key

PROBES_REPO = Path("~/pw-lab/probes").expanduser()
HAS_REPO = (PROBES_REPO / "probes/sample.yml").exists()

METHODS = ["PatchTST", "DLinear", "RLinear", "SCINet", "Autoformer", "Informer", "LogTrans", "TimesNet"]
NAMES = Names(
    methods={key(m): m for m in METHODS} | {key("PatchTST/64"): "PatchTST", key("IMP"): NOT_METHOD},
    by_table={},
    papers={key("PatchTST"): "2211.14730", key("SCINet"): "2106.09305", key("Autoformer"): "2106.13008"},
    present={"2211.14730": "2211.14730v2", "2106.09305": "2106.09305v3", "2106.13008": "2106.13008v5"},
)
CELL = {"dataset": "etth1", "horizon": "96", "header": "SCINet"}
TABLES = Tables(
    numbered={("2106.09305v3", 2): [{"table": "P:T2", "first": "100", "last": "130"}],
              ("2106.09305v3", 9): [{"table": "P:T9", "first": "900", "last": "950"}],
              ("2106.09305v3", 1): [{"table": "P:T1", "first": "50", "last": "80"}]},
    rows={"2106.09305v3": [{"table": "P:T2", "first": "100", "last": "130"},
                           {"table": "P:T9", "first": "900", "last": "950"},
                           {"table": "P:T1", "first": "50", "last": "80"}]},
    cells={"P:T9": [CELL | {"metric": "mse", "value": "0.4"}, CELL | {"metric": "mae", "value": "0.5"},
                    CELL | {"metric": "mse", "value": "0.37"}]},
)  # fmt: skip


def record(text: str, probe: str = "X") -> dict:
    return {"arm": "C", "checkpoint": None, "rep": 1, "probe": probe, "answer": text, "exit": 0, "stop": "stop"}


def score(probe: dict, text: str, judged: dict | None = None, names: Names = NAMES, tables: Tables = TABLES) -> dict:
    return grade(record(text, probe["id"]), probe, names, tables, judged or {})


def auto(template: str, gold: dict) -> dict:
    return {"id": f"{template}-x", "template": template, "answer_type": "value", "gold": gold}


def fa(*lines: str) -> str:
    return "Reasoning.\n\nFinal answer\n" + "\n".join(lines) + "\n"


def test_values_and_sets() -> None:
    assert same("0.370", 0.37) and not same("0.371", 0.37) and not same(None, 0.37)
    assert f1(set(), set()) == 1.0 and f1({"a"}, {"a", "b"}) == pytest.approx(2 / 3)


def test_names_resolve_variants_versions_and_outside_papers() -> None:
    assert NAMES.method("**PatchTST/64**") == "PatchTST" and NAMES.method("IMP") == NOT_METHOD
    assert NAMES.method("DLinear (Zeng et al., 2023)") == "DLinear" and NAMES.method("GRU") is None
    assert NAMES.paper("2211.14730") == "2211.14730v2" and NAMES.paper("arXiv 2211.14730v1") == "2211.14730v1"
    assert NAMES.paper("2111.09020") == "outside:2111.09020" and NAMES.paper("the SCINet paper") == "2106.09305v3"
    assert NAMES.paper("Autoformer: Decomposition Transformers ...") == "2106.13008v5"


def test_t1_values_and_location() -> None:
    probe = auto("T1", {"mse": 0.4, "mae": 0.5, "table": 2, "location": "2106.09305v3:110", "also_at": []})
    assert score(probe, fa("MSE: 0.400", "MAE: 0.5", "Location: Table 2"))["score"] == 1.0
    assert score(probe, fa("MSE: 0.4", "MAE: 0.5", "Location: lines 112-113"))["score"] == 1.0
    assert score(probe, fa("MSE: 0.4", "MAE: 0.5", "Location: Table 9 (appendix)"))["score"] == 1.0  # 同值的另一张表
    assert score(probe, fa("MSE: 0.4", "MAE: 0.5", "Location: Table 1"))["score"] == 0.5
    assert score(probe, fa("MSE: 0.4", "MAE: 0.6", "Location: Table 2"))["score"] == 0.5
    assert score(probe, fa("MSE: 0.3", "MAE: 0.6", "Location: Table 2"))["score"] == 0.0


def test_t3_ties_values_and_lookback() -> None:
    # 题库中并列的 method 与 paper 两个列表各自排序（这里故意不对位），成对的关系只在 ranking 中
    ranking = [{"method": "SCINet", "paper": "2106.09305v3", "mse": 0.37},
               {"method": "PatchTST/64", "paper": "2211.14730v2", "mse": 0.37},
               {"method": "DLinear", "paper": "2211.14730v2", "mse": 0.41}]  # fmt: skip
    gold = {"method": ["PatchTST/64", "SCINet"], "paper": ["2106.09305v3", "2211.14730v2"], "mse": 0.37,
            "lookback": "336", "ranking": ranking}
    probe = auto("T3", gold)
    both = ["SCINet | 2106.09305 | 0.370 | 336", "PatchTST | 2211.14730v2 | 0.37 | L = 336"]
    assert score(probe, fa(*both))["score"] == 1.0
    repeated = ["SCINet | 2106.09305 | 0.370 | 336 (input length T = 336)", both[1]]
    assert score(probe, fa(*repeated))["score"] == 1.0  # 同一个数写两次不算错
    assert score(probe, fa("SCINet | 2106.09305 | 0.370 | 336 (searched in 96, 336)", both[1]))["score"] == 0.5
    assert score(probe, fa(both[0]))["score"] == 0.5  # 并列没列全
    assert score(probe, fa(both[0], "SCINet | 2106.09305 | 0.370 | 96"))["score"] == 0.5
    assert score(probe, fa(*both, "DLinear | 2211.14730 | 0.37 | 336"))["score"] == 0.0
    text = probe | {"gold": gold | {"lookback": "not stated in the paper"}}
    pending = score(text, fa(*both))
    assert pending["score"] is None and [p["item"] for p in pending["pending"]] == ["t3-lookback"]
    assert score(text, fa(*both), {"t3-lookback": False})["score"] == 0.5
    wrong_value = ["SCINet | 2106.09305 | 0.4 | x", "PatchTST | 2211.14730v2 | 0.37 | y"]
    assert score(text, fa(*wrong_value))["pending"] == []  # 值已经错了，不再问 look-back


def test_set_templates() -> None:
    probe = auto("T4", {"methods": ["DLinear", "RLinear"]})
    assert score(probe, fa("DLinear", "RLinear"))["score"] == 1.0
    assert score(probe, fa("DLinear", "IMP"))["score"] == pytest.approx(2 / 3)  # 不是方法的列不计入
    assert score(auto("T6", {"dropped": []}), fa("none"))["score"] == 1.0
    t5 = auto("T5", {"beaten": ["PatchTST", "DLinear"], "later_papers": {"PatchTST": ["2106.09305v3"]}})
    full = fa("Beaten:", "PatchTST", "DLinear", "Later papers:", "PatchTST | SCINet")
    assert score(t5, full)["score"] == 1.0
    assert score(t5, fa("Beaten:", "PatchTST", "DLinear", "Later papers:", "none"))["score"] == 0.5


def test_unknown_names_wait_for_a_judgment() -> None:
    probe = auto("T4", {"methods": ["DLinear"]})
    row = score(probe, fa("DLinear", "GRU"))
    assert row["score"] is None and row["unknown"] == [{"kind": "method", "name": "GRU"}]
    names = Names(NAMES.methods, {}, NAMES.papers, NAMES.present, judged={("method", "GRU"): "GRU"})
    assert score(probe, fa("DLinear", "GRU"), names=names)["score"] == pytest.approx(2 / 3)


def test_t7_provenance_credit() -> None:
    entries = [
        {"paper": "2211.14730v2", "source": "cited", "from": "DLinear 论文"},
        {"paper": "2106.09305v3", "source": "not stated", "from": "", "match": "2211.14730v2:T169"},
        {"paper": "2106.13008v5", "source": "run", "from": ""},
    ]
    probe = auto("T7", {"entries": entries})
    lines = ["2211.14730 | cited: DLinear paper", "2106.09305 | not stated", "Autoformer | own"]
    row = score(probe, fa(*lines))
    assert row["score"] is None and [p["item"] for p in row["pending"]] == ["t7-source:2211.14730v2"]
    assert score(probe, fa(*lines), {"t7-source:2211.14730v2": True})["score"] == 1.0
    half = {"t7-source:2211.14730v2": False}  # 出处不对：这篇得一半
    assert score(probe, fa(*lines), half)["score"] == pytest.approx(2 * 2.5 / 6)
    matched = [lines[0], "2106.09305 | cited: PatchTST paper", lines[2]]
    judged = {"t7-source:2211.14730v2": True, "t7-match:2106.09305v3": True}
    assert score(probe, fa(*matched), judged)["score"] == pytest.approx(2 * 2.5 / 6)
    assert score(probe, fa(lines[0]), {"t7-source:2211.14730v2": True})["score"] == pytest.approx(2 * 1 / 4)


def test_t8_pairs_extra_tables_and_declaring_one_value_correct() -> None:
    gold = {"groups": [{"mse": 0.4, "papers": ["2106.09305v3"], "entries": [{"header": "SCINet", "table": "P:T2"}]},
                       {"mse": 0.45, "papers": ["2211.14730v2"], "entries": [{"header": "SCINet", "table": "Q:T1"}]}]}
    probe = auto("T8", gold)
    lines = ["SCINet paper | 0.400 | Table 2", "2211.14730 | 0.45"]
    assert score(probe, fa(*lines))["pending"][0]["item"] == "t8-declares"
    assert score(probe, fa(*lines), {"t8-declares": False})["score"] == 1.0
    assert score(probe, fa(*lines), {"t8-declares": True})["score"] == 0.0
    extra = [*lines, "SCINet paper | 0.37 | Table 9"]  # 同一论文另一张表中确有此值：不算错
    assert score(probe, fa(*extra), {"t8-declares": False})["score"] == 1.0
    wrong = [*lines, "SCINet paper | 0.38 | Table 9"]
    assert score(probe, fa(*wrong), {"t8-declares": False})["score"] == pytest.approx(0.8)
    assert score(probe, fa("SCINet paper | 0.5"))["score"] == 0.0  # F1 为 0 时不再问


def test_points_and_extraction_fallback() -> None:
    manual = {"id": "M-T2-x", "template": "T2", "gold": {"points": [{"id": "a"}, {"id": "b"}], "must_not": "x"}}
    assert score(manual, "free text")["pending"][0]["item"] == "points"
    assert score(manual, "t", {"points": {"points": {"a": 1, "b": 0.5}, "must_not": False}})["score"] == 0.75
    assert score(manual, "t", {"points": {"points": {"a": 1, "b": 1}, "must_not": True}})["score"] == 0.0
    probe = auto("T4", {"methods": ["DLinear"]})
    row = score(probe, "I think DLinear.")
    assert row["score"] is None and row["flags"] == ["no-final-answer"] and row["pending"][0]["item"] == "extract"
    assert score(probe, "I think DLinear.", {"extract": "DLinear"})["score"] == 1.0
    assert score(probe, "I don't know.", {"extract": ""})["score"] == 0.0
    empty = score(probe, "  \n")
    assert empty["score"] == 0.0 and empty["flags"] == ["empty-answer"] and empty["pending"] == []
    assert score(manual, "")["pending"] == []


def test_runaway_answers_score_zero_and_keep_a_content_score() -> None:
    probe = auto("T4", {"methods": ["DLinear"]})
    for capped in ({"exit": "timeout"}, {"exit": "tool-limit"}, {"stop": "length"}):
        row = grade(record(fa("DLinear")) | capped, probe, NAMES, TABLES, {})
        assert row["score"] == 0.0 and row["content_score"] == 1.0 and row["flags"][0] == "runaway"
    row = grade(record("cut off") | {"exit": "timeout"}, probe, NAMES, TABLES, {})
    assert row["score"] == 0.0 and row["content_score"] is None and row["pending"] == []  # 不交给子代理
    assert score(probe, fa("DLinear"))["flags"] == []


def test_probes_repo_must_match_the_run(tmp_path: Path) -> None:
    import subprocess

    import yaml

    from pweval.measure.grade_v3 import check_probes

    repo = tmp_path / "probes"
    repo.mkdir()
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.org"]
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "a.yml").write_text("x: 1\n")
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "freeze"], check=True)
    head = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    run = tmp_path / "run"
    run.mkdir()

    def invoked(*probes: dict) -> None:
        (run / "run.yml").write_text(yaml.safe_dump({"invocations": [{"probes": p} for p in probes]}))

    invoked({"commit": head, "dirty": False})
    assert check_probes(run, repo) == []
    (repo / "new.yml").write_text("y: 2\n")  # 未跟踪的文件也算改动
    assert check_probes(run, repo) and "untracked" in check_probes(run, repo)[0]
    (repo / "new.yml").unlink()
    invoked({"commit": head, "dirty": False}, {"commit": head, "dirty": True})
    assert check_probes(run, repo) == ["invocation 1 ran with uncommitted changes in the probes repo"]
    invoked({"commit": "0" * 40, "dirty": False})
    assert "used probes 0000000" in check_probes(run, repo)[0]


@pytest.mark.skipif(not HAS_REPO, reason="题库仓库不在本机")
def test_rendered_gold_scores_one_on_every_sampled_auto_probe() -> None:
    from pweval.harness.timeline import load_timeline, papers_at
    from pweval.measure.grade_v3 import papers_at as papers_at_v3
    from pweval.measure.names import load, load_tables
    from pweval.protocol.final_answer import format_for

    timeline = load_timeline(PROBES_REPO)
    for k in (10, 20, 30):
        assert papers_at_v3(PROBES_REPO, k) == papers_at(timeline, k)
    names, tables = load(PROBES_REPO, papers_at(timeline, 30)), load_tables(PROBES_REPO)
    right = {"t3-lookback": True, "t7-source": True, "t7-note": True, "t7-match": True, "t8-declares": False}
    autos = [p for p in timeline.probes if format_for(p)]
    for probe in autos:
        template, gold = probe["template"], probe["gold"]
        text = render(template, gold)
        if template == "T1":
            text = text.replace(f"Table {gold['table']}", f"Table {gold['table']} ({gold['location']})")
        row = score(probe, text, names=names, tables=tables)
        judged = {p["item"]: right[p["item"].split(":")[0]] for p in row["pending"]}
        row = score(probe, text, judged, names=names, tables=tables)
        assert row["unknown"] == [] and row["score"] == 1.0, (probe["id"], row)
