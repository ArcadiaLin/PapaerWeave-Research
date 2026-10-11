"""A0（文件 + git）的笔记库：把一个图状态渲染成 Markdown 笔记，每个对象一个文件。

    python -m t1.a0_seed <输出目录> [--config experiments/t1/config/pilot-ltsf.yml] [--git]

布局（README 只描述它，不规定写者必须怎样做）：

- ``papers/<短名>-<arXiv id>.md``：一篇论文，它的贡献、主张与实验是文件中的章节；
- ``methods/``、``datasets/``、``tasks/``：其余对象各一个文件，文件名是名称的小写连字符形式；
- 对象之间用相对链接；原文位置写成 ``<章节>::<起始行>:<结束行>``，行号是论文材料文件的行号。

不渲染反向链接（A0 用 grep 反查，对应 A3 的 Traverse）。A3 的 id 不出现在笔记中，来源引用中的论文 id 换成指向
论文笔记的链接。渲染是确定性的：同一个状态渲染两次，结果逐字节相同。``--git`` 把输出目录下的 ``store/`` 初始化为
git 仓库，以作者 ``seed`` 提交，标签 ``checkpoint-0``。
"""

from __future__ import annotations

import argparse
import re
import subprocess
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import Any

import yaml
from e09.config import REPO
from e09.model.refs import parse_ref
from e09.query.view import node_view
from graph_vc import GraphState

from .replay import replay

DIRS = {"Paper": "papers", "Method": "methods", "Dataset": "datasets", "Task": "tasks"}
CONTENT = ("Contribution", "Claim", "Experiment")  # 论文笔记中章节的顺序
FIELDS = ("aliases", "identifiers", "year", "material", "stated_by", "anchors")
TEXTS = ("definition", "description", "text")
RELATIONS = {
    "FROM": "Where in the paper",
    "ABOUT": "About",
    "SUPPORTED_BY": "Supported by",
    "EVALUATES": "Evaluates",
    "USES": "Uses",
    "ON_TASK": "Task",
    "HAS_PART": "Parts",
    "PART_OF": "Part of",
    "FOR_TASK": "For task",
    "BROADER": "Broader",
    "CITES": "Cites",
    "SUPPORTS": "Supports",
    "OPPOSES": "Opposes",
}
EDGE_FIELDS = ("role", "stated_by", "description")
README = """# Shared notes

Notes on research papers about long-term time series forecasting, kept by several people for later readers.
Anyone may read, add to, reorganize or correct them; commit your changes with git.

Layout as it stands: one Markdown file per object. `papers/` holds one file per paper, with the paper's
contributions, claims and experiments as sections; `methods/`, `datasets/` and `tasks/` hold one file each.
Notes link to each other with relative links. A location in a paper is written
`<section>::<first line>:<last line>`, using the line numbers of the paper's material file
(`papers/<arXiv id with version>/paper.md` in the workspace, `../papers/...` from this directory).
"""
_ID = re.compile(r"\b(?:paper|method|dataset|task|bench|model|code|exp|claim|contrib|obs|art|issue|prop)_\d{4}\b")


class RenderError(Exception):
    """渲染结果违反不变式（文件名冲突、链接悬空、泄漏 id）。"""


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def heading_anchor(heading: str) -> str:
    """GitHub 的标题锚点：小写，去掉标点（保留连字符），空格换成连字符。"""
    return re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")


def render(state: GraphState) -> dict[str, str]:
    """图状态 → ``{相对路径: Markdown 文本}``，含 README。"""
    views: dict[str, dict[str, Any]] = {}
    for node_id in sorted(state.nodes):
        try:
            views[node_id] = node_view(node_id, state)
        except ValueError:  # NameKey、Material 等系统节点
            continue
    files = _files(views)
    sections = _sections(views)
    # 来源引用的头部可以是材料：换成材料所属的论文
    owners = {k.src: k.dst for k in state.edges if k.type == "MATERIAL_OF" and k.dst in files}
    files_and_owners = (files, owners)
    out = {"README.md": README}
    for node_id, path in sorted(files.items(), key=lambda item: item[1]):
        view = views[node_id]
        lines = [f"# {view['name']}", "", f"- **kind:** {view['kind']}"]
        lines += _body(view, path, views, files_and_owners, sections, level=1)
        if view["kind"] == "Paper":
            for content_id, (paper, heading) in sorted(sections.items(), key=lambda item: _section_order(item, views)):
                if paper == node_id:
                    section = _body(views[content_id], path, views, files_and_owners, sections, level=2)
                    lines += ["", f"## {heading}", "", *section]
        out[path] = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip("\n") + "\n"
    _check(out)
    return out


def _files(views: dict[str, dict[str, Any]]) -> dict[str, str]:
    files: dict[str, str] = {}
    for node_id, view in views.items():
        if view["kind"] not in DIRS:
            continue
        name = view["name"]
        if view["kind"] == "Paper":
            arxiv = [i.split(":", 1)[1] for i in view.get("identifiers", []) if i.startswith("arxiv:")]
            name = f"{name.split(':')[0]} {arxiv[0]}" if arxiv else name
        files[node_id] = f"{DIRS[view['kind']]}/{slug(name)}.md"
    taken: dict[str, str] = {}
    for node_id, path in files.items():
        if path in taken:
            raise RenderError(f"{node_id} and {taken[path]} both map to {path}")
        taken[path] = node_id
    return files


def _sections(views: dict[str, dict[str, Any]]) -> dict[str, tuple[str, str]]:
    """Content → (所属论文, 章节标题)。标题用主锚点，没有锚点或重复时按论文内的序号。"""
    out: dict[str, tuple[str, str]] = {}
    counts: dict[tuple[str, str], int] = {}
    for node_id, view in views.items():
        if view["kind"] not in CONTENT:
            continue
        papers = [e["to"] if isinstance(e, dict) else e for e in view.get("FROM", [])]
        if not papers:
            raise RenderError(f"{node_id} has no paper")
        key = (papers[0], view["kind"])
        counts[key] = counts.get(key, 0) + 1
        anchors = view.get("anchors") or []
        label = anchors[0] if view["kind"] == "Experiment" and anchors else str(counts[key])
        heading = f"{view['kind']} {label}"
        if any(h == heading and p == papers[0] for p, h in out.values()):
            heading = f"{view['kind']} {label} ({counts[key]})"
        out[node_id] = (papers[0], heading)
    return out


def _section_order(item: tuple[str, tuple[str, str]], views: dict[str, dict[str, Any]]) -> tuple[int, str]:
    node_id = item[0]
    return CONTENT.index(views[node_id]["kind"]), node_id


def _link(target: str, here: str, views, files, sections) -> str:
    base = PurePosixPath(here).parent
    if target in files:
        rel = _relative(PurePosixPath(files[target]), base)
        return f"[{views[target]['name']}]({rel})"
    if target in sections:
        paper, heading = sections[target]
        anchor = heading_anchor(heading)
        if files[paper] == here:
            return f"[{heading}](#{anchor})"
        return f"[{heading} in {views[paper]['name']}]({_relative(PurePosixPath(files[paper]), base)}#{anchor})"
    raise RenderError(f"{here}: no note for {target}")


def _relative(path: PurePosixPath, base: PurePosixPath) -> str:
    if path.parent == base:
        return path.name
    return str(PurePosixPath("..") / path)


def _source(ref: str, here: str, views, files, owners, sections) -> str:
    parsed = parse_ref(ref)
    head = owners.get(parsed.head, parsed.head) if parsed is not None else None
    if parsed is None or head not in files:
        raise RenderError(f"{here}: cannot render source reference {ref}")
    rest = ref[len(parsed.head) + 2 :]
    return f"{_link(head, here, views, files, sections)} {rest}"


def _body(view: dict[str, Any], here: str, views, files_and_owners, sections, *, level: int) -> list[str]:
    files, owners = files_and_owners
    lines: list[str] = []
    for field in FIELDS:
        value = view.get(field)
        if value:
            lines.append(f"- **{field}:** {', '.join(map(str, value)) if isinstance(value, list) else value}")
    if view.get("stub"):
        lines.append("- **stub:** known only from citations so far")
    for field in TEXTS:
        if view.get(field):
            lines += ["", str(view[field]).strip()]
    if view.get("note"):
        lines += ["", f"Note: {str(view['note']).strip()}"]
    for rel, title in RELATIONS.items():
        edges = view.get(rel)
        if not edges:
            continue
        lines += ["", f"{'#' * (level + 1)} {title}", ""]
        if rel == "FROM" and view["kind"] in CONTENT:
            lines += [f"- {loc}" for e in edges if isinstance(e, dict) for loc in e.get("locators", [])]
            continue
        for edge in edges:
            if isinstance(edge, str):
                lines.append(f"- {_link(edge, here, views, files, sections)}")
                continue
            extra = [f"{k}: {str(edge[k]).strip()}" for k in EDGE_FIELDS if k in edge]
            if edge.get("locators"):
                extra.append("lines: " + "; ".join(edge["locators"]))
            if edge.get("source_refs"):
                sources = [_source(r, here, views, files, owners, sections) for r in edge["source_refs"]]
                extra.append("sources: " + "; ".join(sources))
            target = _link(edge["to"], here, views, files, sections)
            lines.append(f"- {target}" + (" — " + " · ".join(extra) if extra else ""))
    return lines


def _check(out: dict[str, str]) -> None:
    """不变式：没有 A3 的 id；每个相对链接都指向存在的文件与标题。"""
    for path, text in out.items():
        if leaked := _ID.findall(text):
            raise RenderError(f"{path}: ids leaked {sorted(set(leaked))}")
        for target in re.findall(r"\]\(([^)]+)\)", text):
            file, _, anchor = target.partition("#")
            resolved = str(PurePosixPath(path).parent / file) if file else path
            resolved = str(PurePosixPath(*_normalize(PurePosixPath(resolved).parts)))
            if resolved not in out:
                raise RenderError(f"{path}: dangling link {target}")
            headings = {heading_anchor(h) for h in re.findall(r"^#+ (.+)$", out[resolved], re.M)}
            if anchor and anchor not in headings:
                raise RenderError(f"{path}: dangling anchor {target}")


def _normalize(parts: tuple[str, ...]) -> list[str]:
    stack: list[str] = []
    for part in parts:
        if part == "..":
            stack.pop()
        elif part != ".":
            stack.append(part)
    return stack


def seed_docs(config: Path) -> list[tuple[Path, str]]:
    """配置中的入库文档与来源标签（路径相对于仓库根目录）。"""
    data = yaml.safe_load(config.read_text(encoding="utf-8"))
    return [(REPO / item["doc"], item["source"]) for item in data["seed_docs"]]


def write(files: dict[str, str], store: Path) -> None:
    for path, text in files.items():
        target = store / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


def commit_seed(store: Path) -> None:
    """``store`` 初始化为 git 仓库，以作者 ``seed`` 提交全部文件并打标签 ``checkpoint-0``。"""
    env = ["-c", "user.name=seed", "-c", "user.email=seed@t1.example", "-c", "commit.gpgsign=false"]
    subprocess.run(["git", "init", "-q", "-b", "main", str(store)], check=True)
    subprocess.run(["git", "-C", str(store), "add", "-A"], check=True)
    message = "Seed notes: anchors and seed papers (checkpoint 0)"
    subprocess.run(["git", "-C", str(store), *env, "commit", "-q", "-m", message], check=True)
    subprocess.run(["git", "-C", str(store), *env, "tag", "checkpoint-0"], check=True)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = Path(args.config)
    root = REPO / yaml.safe_load(config.read_text(encoding="utf-8"))["corpus"]["material_root"]
    store = Path(args.out).expanduser().resolve() / "store"
    if store.exists() and any(store.iterdir()):
        print(f"error: {store} exists and is not empty")
        return 1
    files = render(replay(seed_docs(config), root))
    write(files, store)
    if args.git:
        commit_seed(store)
    print(f"{store}: {len(files)} files" + (", committed as checkpoint-0" if args.git else ""))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m t1.a0_seed", description=__doc__.split("\n\n")[0])
    parser.add_argument("out", help="输出目录；笔记库写在其下的 store/")
    parser.add_argument("--config", default=str(REPO / "experiments/t1/config/pilot-ltsf.yml"))
    parser.add_argument("--git", action="store_true", help="初始化 git 仓库，提交并打标签 checkpoint-0")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["README", "RenderError", "commit_seed", "main", "render", "seed_docs", "write"]
