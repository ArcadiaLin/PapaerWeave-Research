"""checkout：把要改的东西取到工作目录，改完用 commit 提交（docs/designs/v3/tools.md）。

    checkout(ids?, new?) -> {files: [...], missing: [...], next}

- ``ids`` 中的产物：取出当前版本的文档（头部带 ``id`` 与 ``base``，检入时核对）。编辑提示与类型的附注
  （:mod:`paperweave.artifact.checkout`）写进旁边的 ``<文档名>.notes.yaml``，返回中只有路径、版本、最近一次编辑与
  一行摘要：读文档的人不需要它们，16 KB 的提示曾被 pi 截断（RPC 第 11 轮）。结构化的全文仍在 ``details`` 中。
- ``ids`` 中的证据节点：写成一份 graph-doc（``set`` 下是 ``get`` 给出的节点，带注释），改其中的值即为修改；
  加边写进 ``create``，删边写进 ``delete``。
- ``new`` 中的 kind：一份空白模板（:mod:`paperweave.model.templates`），每个 kind 一个 ``$`` 节点；产物类型给出
  该类型的空白文档（类型契约中的 ``template``）。

只写写者的工作目录，不改动库。
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any

from ...artifact.checkout import fetch
from ...artifact.types import TYPES
from ...model.schema import ARTIFACT, ARTIFACT_TYPES, KIND_SPECS
from ...model.templates import templates
from ...query.read import get_view
from ...query.view import excerpt
from ...store.store import ContractError
from ...yamlfmt import dump
from ..base import STRINGS, Context, Operator, Rendered, params_of, schema

PARAMETERS = schema({"ids": STRINGS, "new": STRINGS})
EDITS = "edits"


def execute(ctx: Context, request: Mapping[str, Any]) -> Rendered:
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
        for item in fetched["items"]:
            item["notes_file"] = _write_notes(ctx, item)
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
        for k in arts_new:
            if not TYPES[k].template:
                missing.append({"id": k, "msg": f"no blank {k} template; write the document with a type: {k} header"})
                continue
            path = f"artifacts/new-{k.lower()}-{stamp}.md"
            _write(ctx, path, TYPES[k].template)
            files.append({"kind": "artifact", "path": path, "template": k})
        kinds_new = [k for k in new if k in KIND_SPECS]
        if kinds_new:
            path = f"{EDITS}/new-{'-'.join(k.lower() for k in kinds_new)}-{stamp}.yaml"
            _write(ctx, path, templates(kinds_new))
            files.append({"kind": "graph-doc", "path": path, "template": kinds_new})
    nxt = (
        "Read the files with your own read tool (it pages with offset/limit). To change them, edit them and call commit "
        "with files: [<paths>] and a one-line message."
    )
    details = {"files": files, "missing": missing, "next": nxt}
    shown = {"files": [_brief(f) for f in files], "missing": missing, "next": nxt}
    if not missing:
        del shown["missing"]
    return Rendered(details, dump(shown))


def _write_notes(ctx: Context, item: dict[str, Any]) -> str:
    """产物的编辑提示与附注写成文档旁的 ``<文档名>.notes.yaml``，返回它的路径。"""
    path = str(PurePosixPath(item["path"]).with_suffix(".notes.yaml"))
    head = (
        f"# Edit notes for {item['path']} (v{item['version']}): who edited it, what changed since your last edit, and\n"
        "# the type's notes. Line numbers refer to that file. This is not a document: do not commit it.\n"
    )
    _write(ctx, path, head + dump({"hint": item.get("hint", {}), "notes": item.get("notes", {})}))
    return path


def _brief(file: dict[str, Any]) -> dict[str, Any]:
    """返回给 agent 的一项：产物只列路径、版本、最近一次编辑与附注的条数，详情在 notes 文件中。"""
    if file["kind"] != "artifact" or "hint" not in file:
        return file
    out = {k: file[k] for k in ("kind", "artifact", "type", "path", "version", "base", "overwritten", "read_only") if k in file}
    last = file["hint"].get("last_edit", {})
    out["last_edit"] = f"by {last.get('editor')} in {last.get('commit')}: {excerpt(last.get('message', ''), 120)}"
    since = file["hint"].get("since_your_last_edit")
    if isinstance(since, str):
        out["since_your_last_edit"] = since
    elif isinstance(since, dict):  # 写者改过它，之后别人又改了：条数在这里，逐条在 notes 文件中
        n = len(since.get("changed_by_others", [])) + int(str(since.get("more", "0")).split()[0] or 0)
        out["since_your_last_edit"] = f"{n} change(s) by others since your v{since.get('your_version')}; see the notes file"
    counts = [f"{key} {len(value)}" for key, value in file.get("notes", {}).items() if isinstance(value, list | dict)]
    out["notes_file"] = file["notes_file"] + (f" ({'; '.join(counts)})" if counts else "")
    return out


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
