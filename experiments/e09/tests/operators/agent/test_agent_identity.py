"""登录身份：经算子入口写入时，身份与所用的 Agent 由调用环境给出，写入者不能自己声明。"""

from __future__ import annotations

from conftest import AT, EXTRACT

from e09.operators import Context
from e09.tools import TOOLS
from e09.store import Store

USER, AGENT = "results.curator@forecast-lab.example", "pi/sglang/qwen3.8-27b"


def test_commit_and_artifacts_record_the_signed_in_writer(store: Store) -> None:
    ctx = Context(store, at=AT, session="s-login", formed_by=USER, agent=AGENT)
    doc = "graph-doc: v0.1\nby: {by}\nnodes:\n  dataset_0001:\n    note: ETTh1 is hourly.\n"

    other = TOOLS["Commit"].call(ctx, {"doc": doc.format(by="claude"), "source": "test", "apply": True})
    assert other.is_error and other.details["errors"][0]["rule"] == "identity"

    done = TOOLS["Commit"].call(ctx, {"doc": doc.replace("by: {by}\n", ""), "source": "test", "apply": True})
    assert done.details["status"] == "committed", done.details
    record = store.graph.get_commit(done.details["commit"])
    assert record.author == USER and record.meta["agent"] == AGENT

    request = {k: v for k, v in EXTRACT.items() if k not in ("op", "session", "formed_by")}
    written = TOOLS["Extract"].call(ctx, request)
    assert written.details["status"] == "created", written.details
    record = store.graph.get_commit(written.details["commit"])
    assert record.author == USER and record.meta["agent"] == AGENT


def test_commit_source_defaults_to_the_session(store: Store) -> None:
    doc = "graph-doc: v0.1\nnodes:\n  dataset_0001:\n    note: ETTh1 is sampled hourly.\n"
    done = TOOLS["Commit"].call(Context(store, at=AT, session="s-src", formed_by=USER), {"doc": doc, "apply": True})
    assert done.details["status"] == "committed", done.details
    assert store.graph.get_commit(done.details["commit"]).source == "session:s-src"

    unsigned = TOOLS["Commit"].call(Context(store, at=AT), {"doc": doc})
    assert unsigned.is_error and unsigned.details["errors"][0]["at"] == "source"
