"""共同产物的文档格式、类型契约与版本比对：不连库。"""

from __future__ import annotations

from e09.artifact.document import add_checkout, header_field, line_map, parse, strip_checkout, tables
from e09.artifact.types import TYPES
from e09.artifact.versions import blame, compare, since
from e09.model.refs import parse_ref

LEADERBOARD = """---
type: Leaderboard
title: ETTh1 multivariate long-term forecasting
abs: MSE and MAE reported for methods on ETTh1.
task: task_0001          # Long-term forecasting
dataset: dataset_0002    # ETTh1
setting: {variate: multivariate}
---
## Results

| method | variant | paper | lookback | pred_len | MSE | source |
| --- | --- | --- | --- | --- | --- | --- |
| method_0001 Informer |  | paper_0001 Informer | 96 | 24 | 0.577 | paper_0001::4.2::120 |
| method_0002 PatchTST | PatchTST/64 | paper_0002 | best of 24–720 | 96 | 0.370 | [paper_0002::4.1::30:31] |

## Papers covered

| paper | tables | complete |
| --- | --- | --- |
| paper_0001 Informer | Table 1 (paper_0001::4.2::112:140) | yes |

Rows follow the papers' own tables [exp_0001].
"""

SKILL = """---
name: leaderboard
description: How to add a paper's results to a Leaderboard.
metadata:
  type: Skill
---
Find the Leaderboard first.
"""


def test_checkout_lines_round_trip() -> None:
    fetched = add_checkout(LEADERBOARD, "art_0003", "commit_000057")
    assert fetched.splitlines()[1:3] == ["id: art_0003", "base: commit_000057"]
    assert strip_checkout(fetched) == LEADERBOARD
    assert line_map(fetched, LEADERBOARD)[:4] == [1, 4, 5, 6]


def test_skill_keeps_checkout_lines_under_metadata() -> None:
    fetched = add_checkout(SKILL, "art_0007", "commit_000009")
    header = parse(fetched).header
    assert set(header) == {"name", "description", "metadata"}
    assert header_field(header, "id") == "art_0007" and header_field(header, "type") == "Skill"
    assert strip_checkout(fetched) == SKILL
    assert TYPES["Skill"].checkout_path(header) == ".agents/skills/leaderboard/SKILL.md"


def test_tables_and_row_keys() -> None:
    doc = parse(LEADERBOARD)
    found = tables(doc)
    assert [t.heading for t in found] == ["Results", "Papers covered"]
    kind = TYPES["Leaderboard"]
    assert list(kind.records(doc).values()) == [
        "method_0001++paper_0001+24+96",
        "method_0002+PatchTST/64+paper_0002+96+best of 24–720",
    ]
    ref = parse_ref("art_0003#method_0002+PatchTST/64+paper_0002+96+best of 24–720")
    assert ref is not None and ref.kind == "record" and ref.key.casefold() in kind.records(doc)


def test_leaderboard_identity_ignores_names_and_case() -> None:
    kind = TYPES["Leaderboard"]
    a = parse(LEADERBOARD).header
    b = {**a, "dataset": "dataset_0002 ETTh1", "setting": {"variate": "Multivariate"}}
    assert kind.key(a) == kind.key(b)
    assert kind.key(a) != kind.key({**a, "dataset": "dataset_0003"})


def test_leaderboard_mentions() -> None:
    mentions = {(m.text, m.role) for m in TYPES["Leaderboard"].mentions(parse(LEADERBOARD))}
    assert {("task_0001", "task"), ("dataset_0002", "dataset"), ("method_0001", "method")} <= mentions
    assert ("paper_0001::4.2::120", None) in mentions
    assert ("paper_0002::4.1::30:31", None) in mentions
    assert ("paper_0001::4.2::112:140", None) in mentions  # 单元格中不带方括号的来源引用
    assert ("exp_0001", None) in mentions


def test_leaderboard_check() -> None:
    bad = LEADERBOARD.replace("dataset: dataset_0002    # ETTh1\n", "").replace("| method_0002 PatchTST", "| PatchTST")
    errors: list[tuple[str, int, str]] = []
    TYPES["Leaderboard"].check(parse(bad), lambda *e: errors.append(e))
    assert {(rule, line) for rule, line, _ in errors} == {("schema", 1), ("schema", 13)}
    duplicated = LEADERBOARD.replace("| paper_0002 | best of 24–720 | 96 |", "| paper_0001 | 96 | 24 |").replace(
        "| method_0002 PatchTST | PatchTST/64", "| method_0001 Informer | "
    )
    errors.clear()
    TYPES["Leaderboard"].check(parse(duplicated), lambda *e: errors.append(e))
    assert [(rule, line) for rule, line, _ in errors] == [("schema", 14)]


def test_skill_check() -> None:
    errors: list[tuple[str, int, str]] = []
    TYPES["Skill"].check(parse(SKILL.replace("name: leaderboard", "name: Leader Board")), lambda *e: errors.append(e))
    assert [(rule, line) for rule, line, _ in errors] == [("schema", 2)]


def test_blame_and_compare() -> None:
    kind = TYPES["Leaderboard"]
    v1 = parse(LEADERBOARD)
    v2 = parse(LEADERBOARD.replace("| 0.370 |", "| 0.371 |").replace("follow the papers'", "follow each paper's"))
    blamed = blame(kind, [("seed", 1, v1), ("bob", 2, v2)])
    by_line = {b.unit.line: (b.author, b.version) for b in blamed}
    assert by_line[13] == ("seed", 1) and by_line[14] == ("bob", 2) and by_line[22] == ("bob", 2)

    mine = parse(
        LEADERBOARD.replace("| 0.370 |", "| 0.371 |")
        .replace("follow the papers'", "follow each paper's")
        .replace("| 0.577 |", "| 0.578 |")
        .replace(
            "| method_0002 PatchTST | PatchTST/64 | paper_0002 | best of 24–720 | 96 | 0.371 "
            "| [paper_0002::4.1::30:31] |\n",
            "",
        )
    )
    changes = compare(blamed, kind.units(mine), "bob")
    assert [c["row"] for c in changes.modified] == ["results row method_0001++paper_0001+24+96"]
    assert [c["row"] for c in changes.deleted] == ["results row method_0002+PatchTST/64+paper_0002+96+best of 24–720"]
    assert [(o["editor"], o["change"]) for o in changes.others] == [("seed", "modified")]  # 删掉的是 bob 自己的行

    alice = compare(blamed, kind.units(mine), "alice")
    assert sorted(o["editor"] for o in alice.others) == ["bob", "seed"]


def test_since_your_last_edit() -> None:
    kind = TYPES["Generate"]
    text = "---\ntype: Generate\ntitle: Notes\nabs: Notes.\n---\nalpha\nbeta\n"
    v1, v2 = parse(text), parse(text.replace("beta", "gamma"))
    versions = [("alice", 1, v1), ("bob", 2, v2)]
    changed = since(blame(kind, versions), blame(kind, versions[:1]), "alice", 1)
    assert [(c["what"], c["editor"]) for c in changed] == [("gamma", "bob")]
