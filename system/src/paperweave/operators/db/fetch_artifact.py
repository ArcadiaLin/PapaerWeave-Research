"""FetchArtifact：把共同产物的文档取到写者的工作目录（docs/designs/v2/operators.md §3.6）。

    FetchArtifact(artifact, at?) -> {items, missing, next}

``artifact`` 是产物 id 或 id 列表。它是检出：编辑后经 ``CheckIn`` 检入。只写写者的工作目录，不改动库，所以
``PAPERWEAVE_READ_ONLY`` 时也列出。流程见 :mod:`paperweave.artifact.checkout`。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ...artifact.checkout import fetch
from ...query.versions import id_list
from ...store.store import ContractError
from ..base import STRING, STRINGS, Context, Operator, params_of, schema

PARAMETERS = schema({"artifact": STRINGS, "at": STRING}, ["artifact"])


def execute(ctx: Context, request: Mapping[str, Any]) -> dict[str, Any]:
    params = params_of("FetchArtifact", PARAMETERS, request)
    ids = id_list(params["artifact"], at="artifact")
    assert ids is not None
    at = params.get("at")
    if at is not None and not isinstance(at, str):
        raise ContractError([{"rule": "format", "at": "at", "msg": "a commit id or a branch name"}])
    return fetch(ctx.store, ids, workdir=ctx.workdir, me=ctx.formed_by, at=at)


FETCH_ARTIFACT = Operator(name="FetchArtifact", family="db", parameters=PARAMETERS, execute=execute)

__all__ = ["FETCH_ARTIFACT", "PARAMETERS", "execute"]
