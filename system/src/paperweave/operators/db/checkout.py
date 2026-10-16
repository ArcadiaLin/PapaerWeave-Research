"""checkout：把要改的东西取到工作目录，改完用 commit 提交（docs/designs/v3/tools.md）。

    checkout(ids?, new?) -> {files: [...], missing: [...], next}

- ``ids`` 中的产物：取出当前版本的文档（头部带 ``id`` 与 ``base``，检入时核对），并给出编辑提示
  （:mod:`paperweave.artifact.checkout`）。
- ``ids`` 中的证据节点：写成一份 graph-doc（``set`` 下是 ``get`` 给出的节点，带注释），改其中的值即为修改；
  加边写进 ``create``，删边写进 ``delete``。
- ``new`` 中的 kind：一份空白模板（:mod:`paperweave.model.templates`），每个 kind 一个 ``$`` 节点。

只写写者的工作目录，不改动库。
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from ...artifact.checkout import fetch
from ...model.schema import ARTIFACT, ARTIFACT_TYPES, KIND_SPECS
from ...model.templates import templates
from ...query.read import get_view
from ...store.store import ContractError
from ..base import STRINGS, Context, Operator, params_of, schema

PARAMETERS = schema({"ids": STRINGS, "new": STRINGS})
EDITS = "edits"


def execute(ctx: Context, request: Mapping[str, Any]) -> dict[str, Any]:
    params = params_of("checkout", PARAMETERS, request)
    ids = _list(params.get("ids"), "ids")
    new = _list(params.get("new"), "new")
    if not ids and not new:
        raise ContractError([{"at": "ids", "msg": "give ids to edit, or new: [<kind>] for a blank template"}])
    if ctx.workdir is None:
        raise ContractError([{"at": "ids", "msg": "checkout writes into your working directory, which is not available here"}])
    stamp = datetime.now(UTC).strftime("%H%M%S")
    files: list[dict[str, Any]] = []
    missing: list[dict[str, str]] = []
    kinds = ctx.store.kinds(ids) if ids else {}
    arts = [i for i in ids if kinds.get(i) == ARTIFACT]
    nodes = [i for i in ids if kinds.get(i) not in (None, ARTIFACT)]
    missing += [{"id": i, "msg": "not in the store"} for i in ids if i not in kinds]
    if arts:
        fetched = fetch(ctx.store, arts, workdir=ctx.workdir, me=ctx.formed_by)
        files += [{"kind": "artifact", **item} for item in fetched["items"]]
        missing += [{"id": m["artifact"], "msg": m["msg"]} for m in fetched["missing"]]
    if nodes:
        view, _ = get_view(ctx.store, nodes)
        body = view.text()
        text = "graph-doc: v0.2\nset:\n" + "".join(f"  {line}\n" if line else "\n" for line in body.splitlines())
        text = (
            "# Change values under set (fields you do not touch stay as they are; null clears one).\n"
            "# To add edges, write them under a create: section with the same id; to remove them, under delete:.\n"
            + text
        )
        path = f"{EDITS}/edit-{'-'.join(nodes[:3])}{'-etc' if len(nodes) > 3 else ''}-{stamp}.yaml"
        _write(ctx, path, text)
        files.append({"kind": "graph-doc", "path": path, "nodes": nodes})
    if new:
        unknown = [k for k in new if k not in KIND_SPECS]
        arts_new = [k for k in unknown if k in ARTIFACT_TYPES]
        if bad := [k for k in unknown if k not in ARTIFACT_TYPES]:
            raise ContractError([{"at": "new", "msg": f"unknown kind {', '.join(bad)}; one of {', '.join(KIND_SPECS)}"}])
        if arts_new:
            for k in arts_new:
                missing.append({"id": k, "msg": f"no blank {k} template; write the document as its skill describes, then commit it"})
        kinds_new = [k for k in new if k in KIND_SPECS]
        if kinds_new:
            path = f"{EDITS}/new-{'-'.join(k.lower() for k in kinds_new)}-{stamp}.yaml"
            _write(ctx, path, templates(kinds_new))
            files.append({"kind": "graph-doc", "path": path, "template": kinds_new})
    nxt = "Edit the files with your own tools, then call commit with files: [<paths>] and a one-line message."
    return {"files": files, "missing": missing, "next": nxt}


def _list(value: Any, at: str) -> list[str]:
    if value is None:
        return []
    values = [value] if isinstance(value, str) else value
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        raise ContractError([{"at": at, "msg": "a list of strings"}])
    return list(dict.fromkeys(v.strip() for v in values))


def _write(ctx: Context, rel: str, text: str) -> None:
    assert ctx.workdir is not None
    file = ctx.workdir.root / rel
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text, encoding="utf-8")


CHECKOUT = Operator(name="checkout", family="db", parameters=PARAMETERS, execute=execute)

__all__ = ["CHECKOUT", "PARAMETERS", "execute"]
