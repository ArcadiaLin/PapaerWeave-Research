"""ReadEvidence 只读产物文档（``E09_EVIDENCE_SCOPE=artifacts``）：产物文档能读，论文原文不能读。

T1 中只读库的读者这样设置：产物存在集中式的库中，ReadEvidence 是读产物文档的途径，不能为了挡住原文把它整个隐藏。"""

from __future__ import annotations

import pytest
from conftest import AT, EXTRACT, SOURCE, write

from e09.mcp.server import enabled, scoped
from e09.mcp.spec import load
from e09.operators import Context
from e09.operators.db.read_evidence import read_evidence
from e09.store import Store


def test_artifacts_only_reads_documents_but_not_papers(store: Store) -> None:
    art = write(store, EXTRACT)["artifact"]
    refs = [f"{art}::document::1:2", SOURCE]
    assert [i["state"] for i in read_evidence(store, refs)["items"]] == ["available", "available"]

    document, paper = read_evidence(store, refs, artifacts_only=True)["items"]
    assert document["state"] == "available" and document["path"].startswith("artifacts/")
    assert paper["state"] == "missing" and "source papers are not available" in paper["reason"]
    assert "text" not in paper


def test_server_scopes_read_evidence_from_the_environment(store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("E09_READ_ONLY", "1")
    tools, ops = scoped(enabled(load()))
    assert "only artifact documents" not in (tools["ReadEvidence"].description or "")

    monkeypatch.setenv("E09_EVIDENCE_SCOPE", "artifacts")
    tools, ops = scoped(enabled(load()))
    assert "only artifact documents can be read" in (tools["ReadEvidence"].description or "")
    result = ops["ReadEvidence"].call(Context(store, at=AT), {"source_refs": [SOURCE]})
    assert result.details["items"][0]["state"] == "missing"
