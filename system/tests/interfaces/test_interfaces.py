"""版本记录的读取接口：Log、Show、Diff、AsOf（docs/designs/v2/versioning_interfaces.md）。

不连库：用内存中的版本图（按变更集正向重放求各提交时的状态）代替 :class:`graph_vc.VersionedGraph`，接口只用到它的
``head``、``get_commit``、``history`` 与 ``state_at``。``state_at`` 的逆向重放与真实库的一致性由 graph-vc 的测试检验。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
import yaml

from paperweave.operators import Context
from paperweave.query import capacity
from paperweave.store import Store
from paperweave.tools import call
from graph_vc import Changeset, CommitRecord, EdgeChange, GraphState, GraphVCError, NodeChange

AT = "2026-10-07T00:00:00+00:00"
M, T, E, K = ["Concept", "Method"], ["Concept", "Task"], ["Content", "Experiment"], ["NameKey"]
LONG = "".join(f"第 {i} 句：a long experiment description. " for i in range(120))  # 多字节字符，约 5 KB


class History:
    """内存中的线性历史。"""

    def __init__(self) -> None:
        self.records: list[CommitRecord] = []

    def add(self, changeset: Changeset, *, source: str, message: str = "", input: str = "", meta=None) -> str:
        seq = len(self.records) + 1
        nodes = {c.id for c in changeset.nodes if c.op != "delete"}
        ends = {e for c in changeset.edges for e in (c.key.src, c.key.dst)}
        removed = {c.id for c in changeset.nodes if c.op == "delete"}
        record = CommitRecord(
            id=f"commit_{seq:06d}",
            branch="main",
            seq=seq,
            parent=self.records[-1].id if self.records else None,
            author="tester",
            at=f"2026-10-0{seq}T12:00:00+00:00",
            message=message,
            source=source,
            changeset=changeset,
            input=input,
            meta=meta or {},
            touched=tuple(sorted((nodes | ends) - removed)),
            removed=tuple(sorted(removed)),
        )
        self.records.append(record)
        return record.id

    def head(self, branch: str = "main") -> str | None:
        if branch != "main":
            raise GraphVCError(f"unknown branch {branch!r}")
        return self.records[-1].id if self.records else None

    def get_commit(self, commit_id: str) -> CommitRecord:
        for record in self.records:
            if record.id == commit_id:
                return record
        raise GraphVCError(f"unknown commit {commit_id!r}")

    def history(self, branch: str = "main") -> list[CommitRecord]:
        return list(self.records)

    def state_at(self, commit_id: str | None, branch: str = "main") -> GraphState:
        state = GraphState()
        for record in self.records if commit_id is not None else []:
            state = state.apply(record.changeset)
            if record.id == commit_id:
                break
        return state


def build() -> History:
    h = History()
    h.add(  # commit_000001
        Changeset(
            nodes=(
                NodeChange.create("task_0001", T, {"name": "Time series forecasting", "definition": "Predict."}),
                NodeChange.create("method_0001", M, {"name": "DLinear", "definition": "A linear model."}),
                NodeChange.create("exp_0001", E, {"text": "Main table."}),
                NodeChange.create("dlinear|Method|global", K, {"raw": "DLinear"}),
            ),
            edges=(
                EdgeChange.create("exp_0001", "EVALUATES", "method_0001", {"role": "target"}),
                EdgeChange.create("exp_0001", "ON_TASK", "task_0001"),
                EdgeChange.create("dlinear|Method|global", "NAMES", "method_0001"),
            ),
        ),
        source="seed",
        message="seed",
        input="graph-doc: v0.1\nby: tester\nconfirm:\n  $dlinear: {distinct_from: [method_0002]}\nnodes: {}\n",
        meta={"ids": {"$dlinear": "method_0001"}, "dedup": False},
    )
    h.add(  # commit_000002：改定义、加别名、改边上的 role
        Changeset(
            nodes=(
                NodeChange.update("method_0001", M, {"definition": "A linear model."}, {"definition": "Linear."}),
                NodeChange.create("d-linear|Method|global", K, {"raw": "D-Linear"}),
            ),
            edges=(
                EdgeChange.create("d-linear|Method|global", "NAMES", "method_0001"),
                EdgeChange.update("exp_0001", "EVALUATES", "method_0001", {"role": "target"}, {"role": "baseline"}),
            ),
        ),
        source="commit-tool",
        input="".join(f"line {i}: {'x' * 60}\n" for i in range(400)),  # 约 28 KB，要分页
    )
    h.add(  # commit_000003：删掉 exp_0001，新建 exp_0002
        Changeset(
            nodes=(
                NodeChange.delete("exp_0001", E, {"text": "Main table."}),
                NodeChange.create("exp_0002", E, {"text": LONG}),
            ),
            edges=(
                EdgeChange.delete("exp_0001", "EVALUATES", "method_0001", {"role": "baseline"}),
                EdgeChange.delete("exp_0001", "ON_TASK", "task_0001"),
                EdgeChange.create("exp_0002", "EVALUATES", "method_0001", {"role": "target"}),
            ),
        ),
        source="operator:Check",
    )
    h.add(  # commit_000004：定义改回原样
        Changeset(
            nodes=(NodeChange.update("method_0001", M, {"definition": "Linear."}, {"definition": "A linear model."}),)
        ),
        source="commit-tool",
    )
    return h


@pytest.fixture
def history() -> History:
    return build()


def ask(history: History, op: str, **params: Any) -> dict[str, Any]:
    store: Any = Store(None, history, Path("."))  # type: ignore[arg-type]
    out = call(Context(store, AT), {"op": op, **params})
    assert len(out.text.encode("utf-8")) <= capacity.LIMIT
    if not out.is_error:
        assert out.details["meta"]["size"]["used"] == len(out.text.encode("utf-8"))
    return out.details


def pages(history: History, op: str, key: str, **params: Any) -> list[dict[str, Any]]:
    out = [ask(history, op, **params)]
    while out[-1]["meta"]["continuation"]:
        out.append(ask(history, op, **params, continuation=out[-1]["meta"]["continuation"]))
    return out


@pytest.fixture
def small(monkeypatch: pytest.MonkeyPatch) -> int:
    """把容量上限降到 1500 字节，让分页与截短在小数据上出现。"""
    monkeypatch.setattr("paperweave.query.capacity.LIMIT", 1500)
    return 1500


# ── Log ──────────────────────────────────────────────────────────────


def test_log_lists_commits_newest_first_with_object_ids_only(history: History) -> None:
    out = ask(history, "log")
    assert [c["id"] for c in out["commits"]] == ["commit_000004", "commit_000003", "commit_000002", "commit_000001"]
    first = out["commits"][-1]
    assert first["counts"] == {"nodes": {"create": 4}, "edges": {"create": 3}}
    assert first["touched"] == ["exp_0001", "method_0001", "task_0001"]  # NameKey 不列
    assert out["commits"][1]["removed"] == ["exp_0001"]
    assert out["meta"]["at"] == "commit_000004"


@pytest.mark.parametrize(
    ("params", "ids"),
    [
        ({"node": ["exp_0001"]}, ["commit_000003", "commit_000002", "commit_000001"]),
        ({"source": "operator:"}, ["commit_000003"]),
        ({"since": "commit_000002"}, ["commit_000004", "commit_000003"]),
        ({"until": "commit_000002"}, ["commit_000002", "commit_000001"]),
        ({"since": "2026-10-03", "until": "2026-10-03"}, ["commit_000003"]),
    ],
)
def test_log_filters(history: History, params: dict[str, Any], ids: list[str]) -> None:
    assert [c["id"] for c in ask(history, "log", **params)["commits"]] == ids


def test_log_pages_stay_at_the_pinned_commit(history: History) -> None:
    first = ask(history, "log", budget=2)
    assert first["meta"]["continuation"] == "2@commit_000004"
    history.add(Changeset(nodes=(NodeChange.create("task_0002", T, {"name": "Imputation"}),)), source="later")
    rest = ask(history, "log", budget=2, continuation=first["meta"]["continuation"])
    assert [c["id"] for c in rest["commits"]] == ["commit_000002", "commit_000001"]
    assert rest["meta"]["at"] == "commit_000004" and rest["meta"]["continuation"] is None
    assert ask(history, "log")["meta"]["at"] == "commit_000005"  # 新的请求才看到新提交


# ── Show ─────────────────────────────────────────────────────────────


def test_show_summary(history: History) -> None:
    out = ask(history, "show", commit="commit_000001")["commit"]
    assert out["parent"] is None and out["source"] == "seed"
    assert out["confirm"] == {"$dlinear": {"distinct_from": ["method_0002"]}}
    assert out["ids"] == ["$dlinear -> method_0001"] and out["dedup"] is False
    assert out["input"] == {"bytes": len(build().records[0].input.encode()), "lines": 5}
    assert ask(history, "show", commit="main")["commit"]["id"] == "commit_000004"


def test_show_changes_spell_aliases_and_edges_as_the_read_view(history: History) -> None:
    out = ask(history, "show", commit="commit_000002", part="changes")
    assert out["changes"] == [
        {
            "id": "exp_0001",
            "kind": "Experiment",
            "op": "edges",
            "edges": {
                "changed": [{"rel": "EVALUATES", "to": "method_0001", "fields": {"role": ["target", "baseline"]}}]
            },
        },
        {
            "id": "method_0001",
            "kind": "Method",
            "op": "update",
            "fields": {"definition": ["A linear model.", "Linear."], "alias": [None, ["D-Linear"]]},
        },
    ]


def test_show_input_is_paged_by_lines_and_reassembles(history: History) -> None:
    parts = pages(history, "show", "input", commit="commit_000002", part="input")
    assert len(parts) == 2
    assert "".join(p["input"] for p in parts) == history.records[1].input
    assert all(p["input"].endswith("\n") for p in parts)
    assert parts[1]["meta"]["lines"][0] == parts[0]["meta"]["lines"][1] + 1


# ── Diff ─────────────────────────────────────────────────────────────


def test_diff_is_the_net_difference(history: History) -> None:
    out = ask(history, "diff", **{"from": "commit_000001"})
    by_id = {c["id"]: c for c in out["changes"]}
    assert out["summary"]["commits"] == 3
    assert out["summary"]["counts"] == {"Experiment": {"create": 1, "delete": 1}, "Method": {"update": 1}}
    assert by_id["method_0001"]["fields"] == {"alias": [None, ["D-Linear"]]}  # 定义改了又改回，不出现
    assert by_id["exp_0001"]["op"] == "delete" and "kind" not in by_id["exp_0001"]["fields"]
    assert by_id["exp_0001"]["edges"]["removed"] == [
        {"rel": "EVALUATES", "to": "method_0001", "role": "target"},
        {"rel": "ON_TASK", "to": "task_0001"},
    ]
    assert by_id["exp_0002"]["op"] == "create"
    assert out["meta"]["from"] == "commit_000001" and out["meta"]["to"] == "commit_000004"


def test_diff_of_a_parent_and_its_commit_is_show_changes(history: History) -> None:
    for record in history.records[1:]:
        diff = ask(history, "diff", **{"from": record.parent, "to": record.id})["changes"]
        assert diff == ask(history, "show", commit=record.id, part="changes")["changes"]


def test_diff_rejects_a_from_that_is_not_an_ancestor(history: History) -> None:
    out = ask(history, "diff", **{"from": "commit_000003", "to": "commit_000001"})
    assert out["status"] == "rejected" and out["errors"][0]["at"] == "from"
    assert ask(history, "diff", **{"from": "main"})["changes"] == []


# ── AsOf ─────────────────────────────────────────────────────────────


def test_as_of_reads_the_old_state(history: History) -> None:
    out = ask(history, "as_of", at="commit_000001", ids=["method_0001", "exp_0001", "exp_0002"])
    assert "alias" not in out["nodes"]["method_0001"]
    assert out["nodes"]["method_0001"]["definition"] == "A linear model."
    assert out["nodes"]["exp_0001"]["EVALUATES"] == {"method_0001": {"role": "target"}}
    assert out["meta"]["missing"] == [{"ref": "exp_0002", "missing_in": "commit_000001"}]
    now = ask(history, "as_of", at="main", ids=["exp_0001", "method_0001"])
    assert now["meta"]["missing"] == [{"ref": "exp_0001", "missing_in": "commit_000004"}]
    assert now["nodes"]["method_0001"]["alias"] == ["D-Linear"]


def test_as_of_rejects_system_nodes(history: History) -> None:
    out = ask(history, "as_of", at="main", ids=["d-linear|Method|global"])
    assert out["status"] == "rejected" and out["errors"][0]["at"] == "ids"


# ── 容量：分页、截短与分块读取 ───────────────────────────────────────


def test_pages_hold_whole_objects_and_cover_all(history: History, small: int) -> None:
    ids = ["task_0001", "method_0001", "exp_0002"]
    parts = pages(history, "as_of", "nodes", at="main", ids=ids)
    assert len(parts) > 1
    assert [i for p in parts for i in p["nodes"]] == ids
    assert {p["meta"]["at"] for p in parts} == {"commit_000004"}


def test_an_object_that_does_not_fit_is_cut_and_read_back_in_chunks(history: History, small: int) -> None:
    out = ask(history, "as_of", at="main", ids=["exp_0002"])
    node = out["nodes"]["exp_0002"]
    assert node["_cut"] == {"text": {"bytes": len(LONG.encode("utf-8"))}} and node["text"].endswith("…")
    chunks, offset = [], 0
    while offset is not None:
        part = ask(history, "as_of", at="main", ids=["exp_0002"], field="text", offset=offset)
        assert part["bytes"] == len(LONG.encode("utf-8"))
        chunks.append(part["value"])
        offset = part["meta"]["next_offset"]
    assert len(chunks) > 1 and "".join(chunks) == LONG


def test_a_cut_change_is_read_back_by_its_path(history: History, small: int) -> None:
    out = ask(history, "show", commit="commit_000003", part="changes", node=["exp_0002"])
    entry = out["changes"][0]
    assert "fields.text.1" in entry["_cut"]
    chunks, offset = [], 0
    while offset is not None:
        part = ask(
            history,
            "show",
            commit="commit_000003",
            part="changes",
            node=["exp_0002"],
            field="fields.text.1",
            offset=offset,
        )
        chunks.append(part["value"])
        offset = part["meta"]["next_offset"]
    assert "".join(chunks) == LONG


def test_continuations_are_checked(history: History) -> None:
    out = ask(history, "log", continuation="next please")
    assert out["status"] == "rejected" and out["errors"][0]["at"] == "continuation"
    out = ask(history, "show", commit="commit_000002", part="changes", continuation="1@commit_000003")
    assert out["status"] == "rejected" and "commit=commit_000003" in out["errors"][0]["msg"]


def test_results_are_yaml_for_the_agent(history: History) -> None:
    store: Any = Store(None, history, Path("."))  # type: ignore[arg-type]
    out = call(Context(store, AT), {"op": "diff", "from": "commit_000001"})
    assert yaml.safe_load(out.text) == out.details


# ── 历史读取用到的两处算子改动 ───────────────────────────────────────


def test_read_evidence_at_resolves_documents_of_that_commit(history: History, tmp_path: Path) -> None:
    text = "".join(f"line {i}\n" for i in range(1, 11))
    (tmp_path / "doc.md").write_text(text, encoding="utf-8")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    material = NodeChange.create("material_0001", ["Material"], {"path": "doc.md", "content_hash": digest})
    art = NodeChange.create("art_0001", ["Artifact"], {"title": "Notes"})
    paper = NodeChange.create("paper_0001", ["Entity", "Paper"], {"name": "DLinear", "source": ["2205.13504v1"]})
    owns = EdgeChange.create("material_0001", "MATERIAL_OF", "art_0001")
    with_material = history.add(Changeset(nodes=(art, paper, material), edges=(owns,)), source="artifact")
    lost = NodeChange.delete("material_0001", ["Material"], {"path": "doc.md", "content_hash": digest})
    disowned = EdgeChange.delete("material_0001", "MATERIAL_OF", "art_0001")
    history.add(Changeset(nodes=(lost,), edges=(disowned,)), source="x")
    store: Any = Store(None, history, tmp_path)  # type: ignore[arg-type]
    refs = ["art_0001::1 Intro::2:3", "material_0001::4:4", "paper_0001::2:3"]
    then = call(Context(store, AT), {"op": "read_evidence", "source_refs": refs, "at": with_material}).details
    assert [i["state"] for i in then["items"]] == ["available", "available", "missing"]
    assert then["items"][0]["text"] == "2| line 2\n3| line 3\n" and then["coverage"]["at"] == with_material
    assert "the source of paper_0001: 2205.13504v1" in then["items"][2]["reason"]  # 论文按来源 ID 读


class _Moving:
    """头提交在两次读取之间移动的版本图。"""

    def __init__(self, heads: list[str]) -> None:
        self.heads = iter(heads)

    def head(self, branch: str = "main") -> str:
        return next(self.heads)


@pytest.mark.parametrize(
    ("heads", "snapshot", "noted"),
    [(["commit_000004", "commit_000004"], "commit_000004", False), (["commit_000004", "commit_000005"], None, True)],
)
def test_snapshot_is_given_only_when_the_head_did_not_move(heads: list[str], snapshot: str | None, noted: bool) -> None:
    store: Any = Store(None, _Moving(heads), Path("."))  # type: ignore[arg-type]
    got, diagnostics = store.stable(store.snapshot())
    assert got == snapshot and bool(diagnostics) is noted
