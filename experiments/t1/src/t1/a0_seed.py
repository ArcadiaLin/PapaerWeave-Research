"""A0（文件 + git）的笔记库：把 A3 检查点 0 的快照渲染成 Markdown 笔记，每个对象一个文件，再加上种子 Leaderboard。

    python -m t1.a0_seed <快照目录> <输出目录> [--boards experiments/t1/seeds/leaderboards] [--git]

布局（README 只描述它，不规定写者必须怎样做）：

- ``papers/<短名>-<arXiv id>.md``：一篇论文，它的贡献、主张与实验是文件中的章节；
- ``methods/``、``datasets/``、``tasks/``：其余对象各一个文件，文件名是名称的小写连字符形式；
- ``leaderboards/``：种子 Leaderboard，按 ``experiments/t1/seeds/a0-leaderboards.md`` 的规则从 A3 的文档转写；
- 对象之间用相对链接；原文位置写成 ``<章节>::<起始行>:<结束行>``，行号是论文材料文件的行号。

输入是快照（:mod:`t1.snapshot`），不导入被测系统（evaluation_draft §10.1）：对象视图按 graph_model_v2 自己装配
（kind 取次级标签，别名来自指向对象的 ``NameKey``，材料取没有被取代的 ``Material``）。不渲染反向链接（A0 用 grep
反查，对应 A3 的 Traverse）。A3 的 id 不出现在笔记中，来源引用中的论文 id 换成指向论文笔记的链接。渲染是确定性的：
同一个快照渲染两次，结果逐字节相同。``--git`` 把输出目录下的 ``store/`` 初始化为 git 仓库，以作者 ``seed`` 提交，
标签 ``checkpoint-0``。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import unicodedata
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from .paths import SEEDS
from .snapshot import Snapshot, load

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
EDGE_SHOWN = (*EDGE_FIELDS, "locators", "source_refs")
FAMILIES = {"Entity", "Concept", "Content"}
KINDS = {
    "Paper", "Dataset", "Code", "Model", "Benchmark", "Tool",
    "Method", "Task", "Issue", "Proposition",
    "Claim", "Experiment", "Contribution", "Observation",
}
NAMED = {"Paper", "Dataset", "Code", "Model", "Benchmark", "Tool", "Method", "Task"}
_WHITE = re.compile("[\u0009-\u000d\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+")
README = """# Shared notes

Notes on research papers about long-term time series forecasting, kept by several people for later readers.
Anyone may read, add to, reorganize or correct them; commit your changes with git.

Layout as it stands: one Markdown file per object. `papers/` holds one file per paper, with the paper's
contributions, claims and experiments as sections; `methods/`, `datasets/` and `tasks/` hold one file each.
Notes link to each other with relative links. A location in a paper is written
`<section>::<first line>:<last line>`, using the line numbers of the paper's material file
(`papers/<arXiv id with version>/paper.md` in the workspace, `../papers/...` from this directory).
"""
README_BOARDS = (
    "`leaderboards/` holds results tables, one per dataset and setting, with the paper lines of every number.\n"
)
_ID = re.compile(r"\b(?:paper|method|dataset|task|bench|model|code|exp|claim|contrib|obs|art|issue|prop)_\d{4}\b")


class RenderError(Exception):
    """渲染结果违反不变式（文件名冲突、链接悬空、泄漏 id）。"""


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def heading_anchor(heading: str) -> str:
    """GitHub 的标题锚点：小写，去掉标点（保留连字符），空格换成连字符。"""
    return re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")


def render(snap: Snapshot, boards: dict[str, str] | None = None) -> dict[str, str]:
    """快照 → ``{相对路径: Markdown 文本}``，含 README；``boards`` 是种子 Leaderboard 的 ``{文件名: A3 文档}``。"""
    views = object_views(snap)
    files = _files(views)
    sections = _sections(views)
    # 来源引用的头部可以是材料：换成材料所属的论文
    owners = {src: dst for src, rel, dst, _ in snap.edges if rel == "MATERIAL_OF" and dst in files}
    files_and_owners = (files, owners)
    out = {"README.md": README + ("\n" + README_BOARDS if boards else "")}
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
    for name, text in sorted((boards or {}).items()):
        path = f"leaderboards/{name}"
        out[path] = render_board(text, path, views, files)
        check_board(text, out[path], files)
    _check(out)
    return out


def object_views(snap: Snapshot) -> dict[str, dict[str, Any]]:
    """图模型对象的视图：kind、名称与字段、别名、当前材料的路径，以及按终点 id 排序的出边。系统记录与 Artifact
    不在其中。"""
    names: dict[str, list[str]] = {}
    materials: dict[str, list[str]] = {}
    out_edges: dict[str, list[tuple[str, str, dict[str, Any]]]] = {}
    for src, rel, dst, props in snap.edges:
        if rel == "NAMES":
            names.setdefault(dst, []).append(src)
        elif rel == "MATERIAL_OF" and not snap.nodes.get(src, {}).get("props", {}).get("superseded_by"):
            materials.setdefault(dst, []).append(src)
        out_edges.setdefault(src, []).append((rel, dst, props))
    views: dict[str, dict[str, Any]] = {}
    for node_id in sorted(snap.nodes):
        node = snap.nodes[node_id]
        kinds = [label for label in node["labels"] if label in KINDS]
        if len(kinds) != 1 or not FAMILIES & set(node["labels"]):
            continue
        view: dict[str, Any] = {"kind": kinds[0], **node["props"]}
        if kinds[0] in NAMED:
            name = _normalize_name(str(view.get("name") or ""))
            raws = [snap.nodes[k]["props"].get("raw") for k in sorted(names.get(node_id, [])) if k in snap.nodes]
            view["aliases"] = [r for r in raws if isinstance(r, str) and _normalize_name(r) != name]
        if materials.get(node_id):
            view["material"] = snap.nodes[sorted(materials[node_id])[0]]["props"]["path"]
        for rel, dst, props in sorted(out_edges.get(node_id, []), key=lambda e: (e[0], e[1])):
            if rel in RELATIONS:
                shown = {k: props[k] for k in EDGE_SHOWN if k in props}
                view.setdefault(rel, []).append({"to": dst, **shown} if shown else dst)
        views[node_id] = view
    return views


def _normalize_name(text: str) -> str:
    return _WHITE.sub(" ", unicodedata.normalize("NFC", text)).strip()


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
    """来源引用 ``<材料或节点 id>::<章节>::<行>`` → 论文笔记的链接加 ``<章节>::<行>``。"""
    first, sep, rest = ref.strip().partition("::")
    head = owners.get(first, first)
    if not sep or head not in files:
        raise RenderError(f"{here}: cannot render source reference {ref}")
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


# ---------------------------------------------------------------- 种子 Leaderboard（seeds/a0-leaderboards.md）

_LEAD_ID = re.compile(r"^([a-z]+_[0-9a-f]{4,})\b\s*(.*)$")
_BRACKET_SOURCE = re.compile(r"\[([a-z]+_[0-9a-f]{4,}::[^\[\]]+)\]")
_BARE_SOURCE = re.compile(r"\b[a-z]+_[0-9a-f]{4,}::")


def render_board(text: str, here: str, views: dict[str, dict[str, Any]], files: dict[str, str]) -> str:
    """A3 的 Leaderboard 文档 → A0 的笔记：头部换成标题与要点，方法与论文写成链接，来源引用去掉或换成论文链接。"""
    header, body = _split_header(text)
    sections: dict[str, tuple[str, str]] = {}
    lines = [f"# {header['title']}", "", str(header.get("abs") or "").strip(), ""]
    for name in ("task", "dataset"):
        lines.append(f"- **{name}:** {_link(_leading_id(str(header[name])), here, views, files, sections)}")
    setting = header.get("setting")
    shown = ", ".join(f"{k}: {v}" for k, v in setting.items()) if isinstance(setting, dict) else str(setting)
    lines.append(f"- **setting:** {shown}")
    if isinstance(header.get("metrics"), dict):
        metrics = ", ".join(f"{m} ({d} is better)" for m, d in header["metrics"].items())
        lines.append(f"- **metrics:** {metrics}")
    lines.append("")
    columns: list[str] = []
    for line in body:
        if not line.startswith("|"):
            columns = []
            lines.append(_BRACKET_SOURCE.sub(lambda m: _bracketed(m[1], here, views, files), line))
            continue
        cells = _cells(line)
        if not columns:
            columns = cells
            lines.append(line)
            continue
        if all(set(c) <= set("-: ") for c in cells):
            lines.append(line)
            continue
        row = dict(zip(columns, cells, strict=False))
        for column in ("method", "paper"):
            if column in row:
                row[column] = _cell_link(row[column], here, views, files)
        if "source" in row:
            row["source"] = "; ".join(_strip_head(part) for part in row["source"].split(";"))
        if "tables" in row:
            row["tables"] = _BARE_SOURCE.sub("", row["tables"])
        lines.append("| " + " | ".join(row.get(c, "") for c in columns) + " |")
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip("\n") + "\n"


def check_board(a3: str, a0: str, files: dict[str, str]) -> None:
    """不变式：两边的结果表逐行对应，方法与论文指向同一对象，其余各列（来源只比章节与行）相同。"""
    paths = {path: node for node, path in files.items()}
    a3_rows, a0_rows = _rows(_split_header(a3)[1]), _rows(a0.split("\n"))
    if len(a3_rows) != len(a0_rows):
        raise RenderError(f"board rows differ: {len(a3_rows)} in A3, {len(a0_rows)} in A0")
    for left, right in zip(a3_rows, a0_rows, strict=True):
        for column, value in left.items():
            other = right.get(column, "")
            if column in ("method", "paper"):
                target = re.search(r"\]\(\.\./([^)]+)\)", other)
                same = target is not None and paths.get(target[1]) == _leading_id(value)
            elif column == "source":
                same = [_strip_head(p) for p in value.split(";")] == [p.strip() for p in other.split(";")]
            elif column == "tables":
                same = _BARE_SOURCE.sub("", value) == other
            else:
                same = value == other
            if not same:
                raise RenderError(f"board row differs in {column}: {value!r} vs {other!r}")


def _split_header(text: str) -> tuple[dict[str, Any], list[str]]:
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        raise RenderError("board document has no YAML header")
    end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    return yaml.safe_load("\n".join(lines[1:end])) or {}, lines[end + 1 :]


def _rows(lines: list[str]) -> list[dict[str, str]]:
    out, columns = [], []
    for line in lines:
        if not line.startswith("|"):
            columns = []
            continue
        cells = _cells(line)
        if not columns:
            columns = cells
        elif not all(set(c) <= set("-: ") for c in cells):
            out.append(dict(zip(columns, cells, strict=False)))
    return out


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _leading_id(text: str) -> str:
    m = _LEAD_ID.match(text.strip())
    return m[1] if m else text.strip()


def _cell_link(cell: str, here: str, views: dict[str, dict[str, Any]], files: dict[str, str]) -> str:
    m = _LEAD_ID.match(cell.strip())
    if m is None or m[1] not in files:
        raise RenderError(f"{here}: cannot link {cell!r}")
    label = m[2].strip() or _short(views[m[1]])
    return f"[{label}]({_relative(PurePosixPath(files[m[1]]), PurePosixPath(here).parent)})"


def _strip_head(part: str) -> str:
    return _BARE_SOURCE.sub("", part.strip(), count=1)


def _bracketed(inner: str, here: str, views: dict[str, dict[str, Any]], files: dict[str, str]) -> str:
    out = []
    for ref in inner.split(";"):
        head, _, rest = ref.strip().partition("::")
        if head not in files:
            raise RenderError(f"{here}: cannot render source reference {ref}")
        link = f"[{_short(views[head])}]({_relative(PurePosixPath(files[head]), PurePosixPath(here).parent)})"
        out.append(f"{link} {rest}")
    return "; ".join(out)


def _short(view: dict[str, Any]) -> str:
    return str(view["name"]).split(":")[0] if view["kind"] == "Paper" else str(view["name"])


def read_boards(directory: Path) -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(directory.glob("*.md"))}


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
    store = Path(args.out).expanduser().resolve() / "store"
    if store.exists() and any(store.iterdir()):
        print(f"error: {store} exists and is not empty")
        return 1
    files = render(load(Path(args.snapshot)), read_boards(Path(args.boards)) if args.boards else None)
    write(files, store)
    if args.git:
        commit_seed(store)
    print(f"{store}: {len(files)} files" + (", committed as checkpoint-0" if args.git else ""))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m t1.a0_seed", description=__doc__.split("\n\n")[0])
    parser.add_argument("snapshot", help="A3 检查点 0 的快照目录（t1.snapshot）")
    parser.add_argument("out", help="输出目录；笔记库写在其下的 store/")
    boards = str(SEEDS / "leaderboards")
    parser.add_argument("--boards", default=boards, help="种子 Leaderboard 的目录；空字符串表示不加")
    parser.add_argument("--git", action="store_true", help="初始化 git 仓库，提交并打标签 checkpoint-0")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "README",
    "RenderError",
    "check_board",
    "commit_seed",
    "main",
    "object_views",
    "read_boards",
    "render",
    "render_board",
    "write",
]
