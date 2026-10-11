"""可能过期的 ``revised``：所用的有据层、解释层记录在产物形成之后被修订。实体与概念的改动不算。"""

from __future__ import annotations

from conftest import EXTRACT, call, commit_doc, write

from e09.artifact.stale import stale
from e09.store import Store

REVISE_EXP = """graph-doc: v0.1
by: claude
confirm:
  exp_0001: {revise: {reason: "the table compares linear models too", anchor: "5.2 Comparison::10:20"}}
nodes:
  exp_0001:
    text: Multivariate long-term forecasting comparing DLinear with Transformer and linear baselines.
"""


def doc(body: str, by: str = "claude") -> str:
    return f"graph-doc: v0.1\nby: {by}\nnodes:\n{body}"


def test_revisions_of_used_records_mark_artifacts(store: Store) -> None:
    first = write(store, EXTRACT)["artifact"]  # 用到 exp_0001、method_0003、dataset_0001、dataset_0002
    assert stale(store, [first]) == {first: []}

    entity = doc("  dataset_0001:\n    aliases: [ETT-h1]\n    description: Hourly ETT data, a common LTSF benchmark.\n")
    assert commit_doc(store, entity, source="test:entity")["status"] == "committed"
    assert stale(store, [first]) == {first: []}  # 实体的改动不算

    revision = commit_doc(store, REVISE_EXP, source="test:revise")
    assert revision["status"] == "committed", revision
    assert stale(store, [first]) == {first: [{"ref": "exp_0001", "reason": "revised", "commit": revision["commit"]}]}

    obs = commit_doc(
        store,
        doc("  $obs:\n    kind: Observation\n    text: DLinear wins on most horizons.\n    ABOUT: [exp_0001]\n"),
        source="test:obs",
    )
    obs_id = obs["ids"]["$obs"]
    later = write(store, call("Generate", [obs_id], {"purpose": "answer"}, {"text": f"Mostly [{obs_id}]."}))
    later = later["artifact"]
    added = commit_doc(store, doc(f"  {obs_id}:\n    ABOUT: [exp_0001, dataset_0001]\n", by="gpt"), source="test")
    assert added["status"] == "committed", added
    assert stale(store, [later]) == {later: []}  # 别人新增出边不算

    edited = commit_doc(store, doc(f"  {obs_id}:\n    text: DLinear wins on all horizons.\n"), source="test")
    assert edited["status"] == "committed", edited
    assert stale(store, [later]) == {later: [{"ref": obs_id, "reason": "revised", "commit": edited["commit"]}]}
