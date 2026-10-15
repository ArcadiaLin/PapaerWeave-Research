"""读视图：节点按写入时的拼写还原，原样交回 Commit 为 noop。"""

from __future__ import annotations

from conftest import AT

from paperweave.commit import Context, Neo4jReader
from paperweave.model.schema import kind_of
from paperweave.operators.db.commit import run
from paperweave.query.view import dump, render
from paperweave.store import Store


def test_the_whole_graph_round_trips_as_noop(store: Store) -> None:
    state = store.graph.snapshot()
    ids = sorted(i for i, node in state.nodes.items() if kind_of(node.labels))
    view = render(state, ids, {"note": "every object"})
    view["by"] = "claude"
    ctx = Context(Neo4jReader(store.graph, store.driver), "test", AT, store.material_root)
    out = run(dump(view), graph=store.graph, driver=store.driver, ctx=ctx, commit=False)
    assert out["status"] == "noop", out


def test_nodes_are_spelled_as_written(store: Store) -> None:
    state = store.graph.local_state(["paper_0001", "method_0003", "exp_0001", "exp_0002"])
    nodes = render(state, ["paper_0001", "method_0003", "exp_0001", "exp_0002"], {})["nodes"]

    paper = nodes["paper_0001"]
    assert paper["material"] == "papers/2023-DLinear/paper.md"
    assert paper["_material"].startswith("material_")
    assert nodes["method_0003"] == {
        "kind": "Method",
        "name": "DLinear",
        "aliases": ["D-Linear"],
        "definition": "A linear model on a trend and remainder decomposition.",
        "BROADER": ["method_0001"],
    }
    main = nodes["exp_0001"]
    assert "exp_key" not in main
    source = {"to": "paper_0001", "locators": ["5.2 Comparison::10:20"], "_material": paper["_material"]}
    assert main["FROM"] == [source]
    assert main["EVALUATES"][0] == {  # 同类型的边按终点 id 排序
        "to": "method_0002",
        "role": "baseline",
        "description": "Results taken from FEDformer.",
        "source_refs": [f"{paper['_material']}::5.1::21:21"],
    }
    assert nodes["exp_0002"]["USES"] == ["dataset_0003"]  # 没有属性的边写成终点 id
