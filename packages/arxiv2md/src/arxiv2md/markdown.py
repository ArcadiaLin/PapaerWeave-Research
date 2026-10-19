"""Convert arXiv HTML to Markdown with a custom serializer."""

from __future__ import annotations

import base64
import binascii
import html as html_lib
import re
import textwrap
from typing import Iterable
from urllib.parse import urljoin

try:
    from bs4 import BeautifulSoup
    from bs4.element import NavigableString, Tag
except ImportError as exc:  # pragma: no cover - runtime dependency check
    raise RuntimeError("BeautifulSoup4 is required for HTML parsing (pip install beautifulsoup4).") from exc


from arxiv2md.utils.logging_config import get_logger

logger = get_logger(__name__)

_EQUATION_TABLE_RE = re.compile(r"ltx_equationgroup|ltx_eqn_align|ltx_eqn_table")
# A cell holding only an equation number such as "(1)", "(A.1)" or "(3a)".
_EQNO_TEXT_RE = re.compile(r"^\(\s*([\w.\-]+)\s*\)$")
# Attribute marking a placeholder whose text is finished Markdown (see convert_equation_tables).
_MD_BLOCK_ATTR = "data-arxiv2md-md"
# In-document link "[text](#frag)"; skips images and escaped brackets.
_FRAGMENT_LINK_RE = re.compile(r"(?<![!\\])\[([^\[\]]*)\]\(#([^)\s]+)\)")
_ANCHOR_ID_RE = re.compile(r'<a id="([^"]+)"')


def convert_html_to_markdown(html: str, *, remove_refs: bool = False, remove_toc: bool = False) -> str:
    """Convert arXiv HTML into Markdown."""
    soup = BeautifulSoup(html, "html.parser")
    toc_markdown = None
    toc_nav = soup.find("nav", class_=re.compile(r"ltx_TOC"))
    if toc_nav and not remove_toc:
        toc_markdown = _serialize_toc(toc_nav)

    _strip_unwanted_elements(soup)
    if remove_refs:
        for ref in soup.find_all("section", class_=re.compile(r"ltx_bibliography")):
            ref.decompose()

    convert_equation_tables(soup)
    convert_all_mathml_to_latex(soup)
    convert_span_tabulars(soup)
    fix_tabular_tables(soup)

    root = _find_document_root(soup)
    title_tag = root.find("h1", class_=re.compile(r"ltx_title_document"))
    authors_tag = root.find("div", class_=re.compile(r"ltx_authors"))
    abstract_tag = root.find("div", class_=re.compile(r"ltx_abstract"))

    blocks: list[str] = []
    if title_tag:
        blocks.append(f"# {_normalize_text(title_tag.get_text(' ', strip=True))}")
    if authors_tag:
        authors_text = _normalize_text(authors_tag.get_text(" ", strip=True))
        if authors_text:
            blocks.append(f"Authors: {authors_text}")
    if toc_markdown:
        blocks.append("## Contents\n" + toc_markdown)
    if abstract_tag:
        blocks.extend(_serialize_abstract(abstract_tag))

    for tag in (title_tag, authors_tag, abstract_tag):
        if tag:
            tag.decompose()

    blocks.extend(_serialize_children(root))

    return "\n\n".join(block for block in blocks if block).strip()


def convert_fragment_to_markdown(html: str, *, remove_inline_citations: bool = False, base_url: str | None = None) -> str:
    """Convert an HTML fragment into Markdown without title/author/abstract handling.

    Parameters
    ----------
    html : str
        The HTML fragment to convert.
    remove_inline_citations : bool
        If True, completely remove inline citation links. If False (default),
        citation links keep their in-document anchor (e.g. ``[12](#bib.bib12)``);
        the matching anchors are emitted on bibliography entries.
    base_url : str | None
        Base URL to resolve relative image paths against. When provided,
        relative ``<img src>`` attributes are converted to absolute URLs.
    """
    soup = BeautifulSoup(html, "html.parser")
    _strip_unwanted_elements(soup)
    convert_equation_tables(soup)
    convert_all_mathml_to_latex(soup)
    convert_span_tabulars(soup)
    fix_tabular_tables(soup)
    if base_url:
        _resolve_image_urls(soup, base_url)
    blocks = _serialize_children(soup, remove_inline_citations=remove_inline_citations)
    return "\n\n".join(block for block in blocks if block).strip()


def _find_document_root(soup: BeautifulSoup) -> Tag:
    root = soup.find("article", class_=re.compile(r"ltx_document"))
    if root:
        return root
    if soup.body:
        return soup.body
    return soup


def _strip_unwanted_elements(soup: BeautifulSoup) -> None:
    for tag in soup.find_all(["script", "style", "noscript", "link", "meta"]):
        tag.decompose()
    for tag in soup.select("nav.ltx_page_navbar, nav.ltx_TOC"):
        tag.decompose()
    for tag in soup.select("button.sr-only, div.package-alerts, div.ltx_pagination, footer"):
        tag.decompose()


def _math_to_latex(math: Tag) -> str | None:
    """Return the TeX source of a MathML element, or None if it carries none."""
    annotation = math.find("annotation", attrs={"encoding": "application/x-tex"})
    if not (annotation and annotation.text):
        return None
    latex_source = annotation.text.strip()
    latex_source = re.sub(r"(?<!\\)%", "", latex_source)
    # Upstream also stripped the backslash from "\_" / "\^" here; that turns a
    # literal underscore into a subscript (x\_y -> x_y) and breaks \text{a\_b}.
    latex_source = re.sub(r"\\(?=[\[\]])", "", latex_source)
    return latex_source


def convert_all_mathml_to_latex(root: BeautifulSoup) -> None:
    for math in root.find_all("math"):
        latex_source = _math_to_latex(math)
        if latex_source is not None:
            math.replace_with(f"${latex_source}$")
        else:
            math.replace_with(math.get_text(" ", strip=True))


def convert_equation_tables(root: BeautifulSoup) -> None:
    """Replace LaTeXML display-equation tables with finished display-math Markdown.

    Must run before :func:`convert_all_mathml_to_latex`: the TeX is read per
    table cell straight from the MathML, so an equation's structure (rows,
    left/right-hand cells, number) comes from the table rather than from
    re-splitting flattened ``$...$`` text. LaTeXML emits one ``<tbody>`` per
    equation (``id`` = ``S3.E1`` / ``S3.Ex1``), one ``<tr>`` per line, and one
    ``<td>`` per alignment column; an equation becomes one ``$$`` block, with
    ``aligned`` for multi-line equations and ``\\tag{n}`` for its number.
    """
    tables = [
        table
        for table in root.find_all("table", class_=_EQUATION_TABLE_RE)
        if not table.find_parent("table", class_=_EQUATION_TABLE_RE)
    ]
    for table in tables:
        blocks: list[str] = []
        groups = table.find_all("tbody", recursive=False) or [table]
        for group in groups:
            group_id = group.get("id") or (table.get("id") if len(groups) == 1 else None)
            blocks.extend(_equation_group_blocks(group, group_id))
        placeholder = root.new_tag("div", attrs={_MD_BLOCK_ATTR: ""})
        placeholder.string = "\n\n".join(blocks)
        table.replace_with(placeholder)


def _equation_group_blocks(group: Tag, group_id: str | None) -> list[str]:
    """Serialize one LaTeXML equation (a tbody, or a whole table) into Markdown blocks."""
    # Without any MathML the cell text is the only form of the equation there
    # is; keep it verbatim rather than wrapping it in \text{}.
    text_as_tex = group.find("math") is None
    rows: list[tuple[list[str], str | None]] = []
    for tr in group.find_all("tr", recursive=False):
        cells: list[str] = []
        number = None
        for td in tr.find_all("td", recursive=False):
            classes = td.get("class", [])
            if any(cls.startswith("ltx_eqn_center_pad") for cls in classes):
                continue
            eqno = _EQNO_TEXT_RE.match(td.get_text(" ", strip=True)) if not td.find("math") else None
            if "ltx_eqn_eqno" in classes or eqno:
                label = eqno.group(1) if eqno else td.get_text(" ", strip=True).strip("() ")
                number = number or label or None
                continue
            cells.append(_cell_to_latex(td, text_as_tex=text_as_tex))
        if any(cells) or number:
            rows.append((cells, number))

    numbers = [number for _, number in rows if number]
    # Several numbered lines in one group: give each its own block so every
    # number survives (\tag is not allowed inside aligned).
    if len(numbers) > 1:
        return [
            block
            for index, (cells, number) in enumerate(rows)
            for block in _display_math_blocks([cells], number, group_id if index == 0 else None)
        ]
    return _display_math_blocks([cells for cells, _ in rows], numbers[0] if numbers else None, group_id)


def _display_math_blocks(rows: list[list[str]], number: str | None, anchor_id: str | None) -> list[str]:
    if len(rows) == 1:
        body = " ".join(cell for cell in rows[0] if cell)
    else:
        lines = " \\\\\n".join(" & ".join(cells) for cells in rows)
        body = f"\\begin{{aligned}}\n{lines}\n\\end{{aligned}}"
    if not body.strip():
        return []
    if number:
        body = f"{body} \\tag{{{number}}}"
    problem = _display_math_problem(body)
    if problem:
        logger.warning("Display equation {} may not render: {}", anchor_id or "?", problem)
    blocks = [f"$$\n{body}\n$$"]
    if anchor_id:
        blocks.insert(0, anchor_html(anchor_id))
    return blocks


def _cell_to_latex(node: Tag, *, text_as_tex: bool = False) -> str:
    """TeX for one equation-table cell: math via its annotation, loose text via \\text{}."""
    parts: list[str] = []
    for child in node.children:
        if isinstance(child, NavigableString):
            text = _normalize_text(str(child))
            if text:
                # Spaces inside \text{} are kept; math mode would swallow them.
                parts.append(text if text_as_tex else f"\\text{{ {_escape_tex_text(text)} }}")
        elif isinstance(child, Tag):
            if child.name == "math":
                latex = _math_to_latex(child)
                if latex is None:
                    text = _normalize_text(child.get_text(" ", strip=True))
                    latex = f"\\text{{{_escape_tex_text(text)}}}" if text else ""
                if latex:
                    parts.append(latex)
            else:
                inner = _cell_to_latex(child, text_as_tex=text_as_tex)
                if inner:
                    parts.append(inner)
    return " ".join(parts)


_TEX_TEXT_ESCAPES = {
    "\\": r"\textbackslash{}",
    "^": r"\^{}",
    "~": r"\~{}",
    **{char: "\\" + char for char in "{}%$&#_"},
}


def _escape_tex_text(text: str) -> str:
    return re.sub(r"[\\^~{}%$&#_]", lambda m: _TEX_TEXT_ESCAPES[m.group(0)], text)


def _display_math_problem(body: str) -> str | None:
    """Cheap structural check of a display-math body; returns a reason or None."""
    stripped = re.sub(r"\\[\\{}$%&#_]", "", body)
    if "$" in stripped:
        return "unescaped $ inside display math"
    depth = 0
    for char in stripped:
        depth += {"{": 1, "}": -1}.get(char, 0)
        if depth < 0:
            return "unbalanced braces"
    if depth:
        return "unbalanced braces"
    if len(re.findall(r"\\begin\{", body)) != len(re.findall(r"\\end\{", body)):
        return "unbalanced \\begin/\\end"
    return None


def anchor_html(anchor_id: str) -> str:
    """Inline HTML anchor for an in-document jump target. Emits both id and
    name — Markdown renderers disagree on which one they honor."""
    escaped = html_lib.escape(anchor_id, quote=True)
    return f'<a id="{escaped}" name="{escaped}"></a>'


def unlink_dangling_fragment_links(markdown: str) -> str:
    """Turn ``[text](#frag)`` links whose target anchor is absent into plain text.

    Targets can go missing legitimately (filtered sections, removed references,
    elements without an emitted anchor); a dead link is worse than plain text.
    """
    anchors = {html_lib.unescape(anchor) for anchor in _ANCHOR_ID_RE.findall(markdown)}

    def _sub(match: re.Match) -> str:
        return match.group(0) if match.group(2) in anchors else match.group(1)

    return _FRAGMENT_LINK_RE.sub(_sub, markdown)


_SPAN_TABLE_PARTS = {"ltx_tabular": "table", "ltx_thead": "thead", "ltx_tbody": "tbody", "ltx_tfoot": "tfoot",
                     "ltx_tr": "tr", "ltx_td": "td"}
_SPAN_RE = re.compile(r"ltx_(row|col)span_(\d+)")


def convert_span_tabulars(root: BeautifulSoup) -> None:
    """Turn LaTeXML's inline tabulars (``<span class="ltx_tabular">`` with span rows and cells) into real tables.

    LaTeXML emits these when a tabular sits inside a box such as ``\resizebox``; without this they reach the
    serializer as loose spans and every cell ends up on its own line. Spans are encoded in classes
    (``ltx_colspan_4``) rather than attributes, so they are copied into ``colspan``/``rowspan``.
    """
    for tabular in root.find_all("span", class_="ltx_tabular"):
        parts = [tabular] + [el for el in tabular.find_all("span") if set(el.get("class") or []) & _SPAN_TABLE_PARTS.keys()]
        for el in parts:
            classes = el.get("class") or []
            el.name = next(_SPAN_TABLE_PARTS[c] for c in classes if c in _SPAN_TABLE_PARTS)
            for c in classes:
                if m := _SPAN_RE.fullmatch(c):
                    el[f"{m.group(1)}span"] = m.group(2)


def fix_tabular_tables(root: BeautifulSoup) -> None:
    tables = root.find_all("table", class_=re.compile(r"ltx_tabular"))
    for table in tables:
        _remove_all_attributes(table)
        for child in table.find_all(["tbody", "thead", "tfoot", "tr", "td", "th"]):
            _remove_all_attributes(child)


def _iter_image_elements(root: Tag) -> Iterable[tuple[Tag, str]]:
    """Yield (element, url-attribute) pairs for images in a subtree.

    LaTeXML embeds SVG figures as ``<object type="image/svg+xml" data="...">``
    instead of ``<img>``; both forms count as images.
    """
    for el in root.find_all(["img", "object"]):
        if el.name == "img":
            yield el, "src"
        elif (el.get("type") or "").startswith("image/") and el.get("data"):
            yield el, "data"


def _resolve_image_urls(root: BeautifulSoup, base_url: str) -> None:
    """Resolve relative image URLs (``<img src>``, ``<object data>``) to absolute URLs."""
    # Ensure base_url ends with '/' so urljoin resolves relative paths correctly
    if not base_url.endswith("/"):
        base_url += "/"
    # Some papers reference assets with the paper-id prefix already included
    # (e.g. src="1706.03762v7/Figures/x.png" under base .../html/1706.03762v7);
    # resolving those against base_url would duplicate the id segment. The
    # version suffix may appear only in src (base .../html/1207.5777 with
    # src="1207.5777v1/intro1.png"), so match it optionally on both sides.
    base_id = re.sub(r"v\d+$", "", base_url.rstrip("/").rsplit("/", 1)[-1])
    id_prefix_re = re.compile(re.escape(base_id) + r"(?:v\d+)?/")
    for el, attr in _iter_image_elements(root):
        src = el.get(attr)
        if src and not src.startswith(("http://", "https://", "data:")):
            if id_prefix_re.match(src):
                el[attr] = urljoin(base_url, "../" + src)
            else:
                el[attr] = urljoin(base_url, src)


def _remove_all_attributes(tag: Tag) -> None:
    # rowspan/colspan are structure, not styling: without them merged cells
    # shift every later cell of the row into the wrong column.
    tag.attrs = {key: value for key, value in tag.attrs.items() if key in ("rowspan", "colspan")}


def _serialize_children(container: Tag, *, remove_inline_citations: bool = False) -> list[str]:
    """Serialize a container's children as blocks.

    Runs of text and inline elements sitting directly in a block container
    (no <p> around them — e.g. LaTeXML listing lines ``div > span > text``)
    are collected into a paragraph instead of being dropped.
    """
    blocks: list[str] = []
    inline_run: list[Tag | NavigableString] = []

    def _flush() -> None:
        if inline_run:
            text = _cleanup_inline_text(
                "".join(_serialize_inline(node, remove_inline_citations=remove_inline_citations) for node in inline_run)
            )
            if text:
                blocks.append(text)
            inline_run.clear()

    for child in container.children:
        if isinstance(child, NavigableString):
            if type(child) is NavigableString:  # skip comments, CDATA, doctype
                inline_run.append(child)
            continue
        if not isinstance(child, Tag):
            continue
        if _is_block(child):
            _flush()
            blocks.extend(_serialize_block(child, remove_inline_citations=remove_inline_citations))
        else:
            inline_run.append(child)
    _flush()
    return blocks


_BLOCK_TAGS = frozenset(
    {"p", "div", "section", "article", "figure", "figcaption", "table", "ul", "ol", "dl",
     "blockquote", "pre", "h1", "h2", "h3", "h4", "h5", "h6", "svg", "foreignobject"}
)


def _is_block(tag: Tag) -> bool:
    """A tag is serialized as a block if it is one, or wraps one (e.g. a span
    holding paragraphs)."""
    if tag.name in _BLOCK_TAGS or tag.has_attr(_MD_BLOCK_ATTR):
        return True
    return tag.find(_BLOCK_TAGS) is not None


def _serialize_block(tag: Tag, *, remove_inline_citations: bool = False) -> list[str]:
    if tag.has_attr(_MD_BLOCK_ATTR):
        text = tag.get_text()
        return [text] if text else []

    classes = tag.get("class", [])
    if "ltx_listing_data" in classes:
        return []  # LaTeXML's "download source" link

    # Verbatim code/prompt listings: their text must not be read as Markdown
    # (a prompt line "## Task" would become a heading).
    if "ltx_lstlisting" in classes or tag.name == "pre":
        code = _serialize_code_block(tag)
        return [code] if code else []

    # Pseudocode (algorithmic): also a code block, for agents rather than
    # human readers — line numbers, nesting and $...$ math kept as plain text.
    if "ltx_listing" in classes:
        code = _serialize_algorithm_block(tag)
        return [code] if code else []

    if tag.name in {"section", "article", "div", "span"}:
        return _serialize_children(tag, remove_inline_citations=remove_inline_citations)

    if tag.name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        level = int(tag.name[1])
        heading = _normalize_text(tag.get_text(" ", strip=True))
        if not heading:
            return []
        return [f"{'#' * level} {heading}"]

    if tag.name == "p":
        paragraph = _serialize_paragraph(tag, remove_inline_citations=remove_inline_citations)
        return [paragraph] if paragraph else []

    if tag.name in {"ul", "ol"}:
        lines = _serialize_list(tag, remove_inline_citations=remove_inline_citations)
        return ["\n".join(lines)] if lines else []

    if tag.name == "figure":
        figure = _serialize_figure(tag, remove_inline_citations=remove_inline_citations)
        return [figure] if figure else []

    if tag.name == "table":
        table_md = _serialize_table(tag, remove_inline_citations=remove_inline_citations)
        return [table_md] if table_md else []

    if tag.name == "blockquote":
        # Serialize as blocks so paragraphs, lists and listings inside a quote
        # keep their structure, then quote every line.
        inner = "\n\n".join(_serialize_children(tag, remove_inline_citations=remove_inline_citations))
        if not inner.strip():
            return []
        return ["\n".join(f"> {line}" if line else ">" for line in inner.split("\n"))]

    if tag.name == "br":
        return []

    return _serialize_children(tag, remove_inline_citations=remove_inline_citations)


def _serialize_code_block(tag: Tag) -> str:
    # LaTeXML's rendered lines collapse indentation and show string spaces as
    # "␣"; the embedded download link carries the original listing source.
    text = _listing_source(tag)
    lines_tags = tag.find_all(class_="ltx_listingline")
    if text is None and lines_tags:
        lines = []
        for line in lines_tags:
            for number in line.find_all(class_="ltx_tag_listingline"):
                number.decompose()
            lines.append(line.get_text().rstrip("\n").rstrip())
        text = "\n".join(lines)
    elif text is None:
        text = tag.get_text().strip("\n")
    if not text.strip():
        return ""
    language = next(
        (cls.removeprefix("ltx_lst_language_").lower() for cls in tag.get("class", []) if cls.startswith("ltx_lst_language_")),
        "",
    )
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}{language}\n{text}\n{fence}"


# Widths (in em) of the Unicode spaces LaTeXML uses to render algorithmic indentation.
_SPACE_WIDTHS_EM = {
    "\u2003": 1.0, "\u2002": 0.5, "\u2007": 0.5, "\u2004": 1 / 3, "\u2005": 0.25, "\u2008": 0.25,
    "\u205f": 0.22, "\u2009": 0.2, "\u202f": 0.2, "\u2006": 1 / 6, "\u200a": 0.1, "\u00a0": 0.25, " ": 0.25,
}


def _serialize_algorithm_block(tag: Tag) -> str:
    """Render a LaTeXML algorithmic listing as a fenced block.

    LaTeXML drops the nesting structure of algorithmic blocks and encodes it
    only as leading Unicode spaces of varying width (e.g. em + en + hair space
    per level). The smallest non-zero leading width in the listing is taken
    as one level, and levels are rendered as 4-space indents; for bodies
    without "end for"/"end if" markers that indentation is the only scope cue.
    """
    rows: list[tuple[str, float, str]] = []
    for line in tag.find_all(class_="ltx_listingline"):
        number_tag = line.find(class_="ltx_tag_listingline")
        number = _normalize_text(number_tag.get_text()) if number_tag else ""
        if number_tag:
            number_tag.decompose()
        text = line.get_text().lstrip("\n\r\t")
        width = 0.0
        for index, char in enumerate(text):
            if char in _SPACE_WIDTHS_EM:
                width += _SPACE_WIDTHS_EM[char]
            elif char in "\n\r\t":
                continue
            else:
                text = text[index:]
                break
        else:
            text = ""
        rows.append((number, width, _normalize_text(text)))
    rows = [row for row in rows if row[0] or row[2]]
    if not rows:
        return ""

    unit = min((width for _, width, _ in rows if width > 0.05), default=0.0)
    number_width = max(len(number) for number, _, _ in rows)
    lines = []
    for number, width, text in rows:
        level = round(width / unit) if unit else 0
        prefix = f"{number:>{number_width}} " if number_width else ""
        lines.append(f"{prefix}{'    ' * level}{text}".rstrip())
    body = "\n".join(lines)
    longest = max((len(run) for run in re.findall(r"`+", body)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}\n{body}\n{fence}"


def _listing_source(tag: Tag) -> str | None:
    """Decode the ``data:text/plain;base64,...`` source of a LaTeXML listing, if present."""
    link = tag.select_one(".ltx_listing_data a[href^='data:']")
    if link is None:
        return None
    header, _, payload = link["href"].partition(",")
    if ";base64" not in header:
        return None
    try:
        source = base64.b64decode(payload).decode("utf-8", errors="replace")
    except (binascii.Error, ValueError):
        return None
    source = textwrap.dedent(source.replace("\r\n", "\n")).strip("\n")
    return source.rstrip() or None


def _serialize_abstract(tag: Tag) -> list[str]:
    blocks = ["## Abstract"]
    paragraphs = tag.find_all("p")
    if not paragraphs:
        content = _normalize_text(tag.get_text(" ", strip=True))
        if content:
            blocks.append(content)
        return blocks

    for paragraph in paragraphs:
        text = _serialize_paragraph(paragraph)
        if text:
            blocks.append(text)
    return blocks


def _serialize_paragraph(tag: Tag, *, remove_inline_citations: bool = False) -> str:
    content = _serialize_inline(tag, remove_inline_citations=remove_inline_citations)
    content = _cleanup_inline_text(content)
    return content


def _is_citation_link(href: str | None) -> bool:
    """Check if a link is a citation reference (e.g., #bib.bib7)."""
    if not href:
        return False
    return "#bib." in href or href.startswith("#bib")


def _is_internal_paper_link(href: str | None) -> bool:
    """Check if a link is an internal paper section reference (e.g., arxiv.org/html/...#S2.SS1)."""
    if not href:
        return False
    return "arxiv.org/html/" in href and "#" in href and "#bib" not in href


def _extract_fragment(href: str | None) -> str | None:
    """Return the ``#fragment`` part of an href, or None if it has none."""
    if not href or "#" not in href:
        return None
    return href[href.index("#") :]


def _serialize_inline(node: Tag | NavigableString, *, remove_inline_citations: bool = False) -> str:
    if isinstance(node, NavigableString):
        return str(node)

    if node.name == "br":
        return "\n"

    if node.name in {"em", "i"}:
        return f"*{_serialize_children_inline(node, remove_inline_citations=remove_inline_citations)}*"

    if node.name in {"strong", "b"}:
        return f"**{_serialize_children_inline(node, remove_inline_citations=remove_inline_citations)}**"

    if node.name == "a":
        text = _serialize_children_inline(node, remove_inline_citations=remove_inline_citations).strip()
        href = node.get("href")
        # Handle citation links specially
        if _is_citation_link(href):
            if remove_inline_citations:
                return ""  # Completely remove citation
            fragment = _extract_fragment(href)
            # Keep the in-document jump (e.g. [12](#bib.bib12)); the matching
            # anchor is emitted next to the bibliography entry in _serialize_list.
            if fragment:
                return f"[{text or fragment}]({fragment})"
            return text  # No fragment to link to; keep text only
        # Handle internal paper links (section references)
        if remove_inline_citations and _is_internal_paper_link(href):
            return text  # Keep text only, strip URL
        # Regular links: keep full markdown link
        if href:
            return f"[{text or href}]({href})"
        return text

    if node.name == "sup":
        text = _serialize_children_inline(node, remove_inline_citations=remove_inline_citations).strip()
        return f"^{text}" if text else ""

    if node.name == "cite":
        if remove_inline_citations and "ltx_cite" in node.get("class", []):
            return ""
        return _serialize_children_inline(node, remove_inline_citations=remove_inline_citations)

    if node.name == "math":
        text = node.get_text(" ", strip=True)
        return f"${text}$" if text else ""

    if "ltx_listing_data" in node.get("class", []):
        return ""

    if "ltx_note" in node.get("class", []):
        text = _normalize_text(_serialize_children_inline(node, remove_inline_citations=remove_inline_citations))
        return f"({text})" if text else ""

    return _serialize_children_inline(node, remove_inline_citations=remove_inline_citations)


def _serialize_children_inline(tag: Tag, *, remove_inline_citations: bool = False) -> str:
    return "".join(_serialize_inline(child, remove_inline_citations=remove_inline_citations) for child in tag.children)


def _cleanup_inline_text(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    return text.strip()


def _serialize_list(list_tag: Tag, indent: int = 0, *, remove_inline_citations: bool = False) -> list[str]:
    lines: list[str] = []
    for item in list_tag.find_all("li", recursive=False):
        item_text_parts: list[str] = []
        nested_lists: list[Tag] = []
        for child in item.children:
            if isinstance(child, Tag) and child.name in {"ul", "ol"}:
                nested_lists.append(child)
            else:
                item_text_parts.append(_serialize_inline(child, remove_inline_citations=remove_inline_citations))
        item_text = _cleanup_inline_text("".join(item_text_parts))
        # Bibliography entries carry id="bib.bibN", the jump target of citation
        # links; other list items (itemize bullets) get no anchor.
        item_id = item.get("id")
        if item_id and item_id.startswith("bib."):
            item_text = anchor_html(item_id) + item_text
        prefix = "  " * indent + "- "
        lines.append(prefix + item_text if item_text else prefix.rstrip())
        for nested in nested_lists:
            lines.extend(_serialize_list(nested, indent + 1, remove_inline_citations=remove_inline_citations))
    return lines


def _serialize_toc(toc_nav: Tag) -> str:
    list_tag = toc_nav.find("ol")
    if not list_tag:
        return ""
    lines = _serialize_list(list_tag)
    return "\n".join(lines)


def _serialize_table(table: Tag, *, remove_inline_citations: bool = False) -> str:
    # Equation tables never reach here: convert_equation_tables replaced them.
    # Rows sit in tbody/thead/tfoot or directly in the table.
    sections = table.find_all(["thead", "tbody", "tfoot"], recursive=False) or [table]
    trs = [row for section in sections for row in section.find_all("tr", recursive=False)]
    rows = _table_grid(trs, remove_inline_citations=remove_inline_citations)

    if not rows:
        return ""

    max_cols = max(len(row) for row in rows)
    normalized = [row + [""] * (max_cols - len(row)) for row in rows]
    header = normalized[0]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    for row in normalized[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _table_grid(trs: list[Tag], *, remove_inline_citations: bool = False) -> list[list[str]]:
    """Lay table rows out on a grid, honoring rowspan/colspan.

    A merged cell's text appears once, at its top-left position; the other
    positions it covers are left empty, so every value stays under its own
    column header.
    """
    grid: list[list[str]] = []
    covered: set[tuple[int, int]] = set()
    for r, row in enumerate(trs):
        cells = row.find_all(["th", "td"], recursive=False)
        if not cells:
            continue
        values: list[str] = []
        c = 0
        for cell in cells:
            while (r, c) in covered:
                values.append("")
                c += 1
            text = _cleanup_inline_text(_serialize_inline(cell, remove_inline_citations=remove_inline_citations))
            values.append(text.replace("\n", "<br>").replace("|", "\\|"))
            rowspan, colspan = _span(cell, "rowspan"), _span(cell, "colspan")
            for dr in range(rowspan):
                for dc in range(colspan):
                    if dr or dc:
                        covered.add((r + dr, c + dc))
            values.extend([""] * (colspan - 1))
            c += colspan
        while (r, c) in covered:
            values.append("")
            c += 1
        grid.append(values)
    return grid


def _span(cell: Tag, attr: str) -> int:
    try:
        return max(1, min(int(cell.get(attr, 1)), 1000))
    except (TypeError, ValueError):
        return 1


def _serialize_figure(figure: Tag, *, remove_inline_citations: bool = False) -> str:
    # Check if this is a table figure (ltx_table class)
    figure_classes = " ".join(figure.get("class", []))
    is_table_figure = "ltx_table" in figure_classes

    # Only the figure's own caption: with sub-figure panels, a plain recursive
    # find would return the first panel's "(a) ..." caption instead.
    caption_tag = next((fc for fc in figure.find_all("figcaption") if fc.find_parent("figure") is figure), None)
    caption = _normalize_text(_serialize_inline(caption_tag, remove_inline_citations=remove_inline_citations)) if caption_tag else ""
    anchor = anchor_html(figure["id"]) if figure.get("id") else ""
    # Everything serialized here is detached afterwards; whatever remains in
    # the figure (listings, algorithm bodies, footnote lists, text boxes, extra
    # tables) goes through the generic block serializer instead of being lost.
    handled: list[Tag] = [caption_tag] if caption_tag else []

    lines = []

    if is_table_figure:
        # Handle table figures - find and serialize the embedded table
        # Note: fix_tabular_tables strips attributes, so search for any table element
        table = figure.find("table")
        if table:
            handled.append(table)
            table_md = _serialize_table(table, remove_inline_citations=remove_inline_citations)
            if caption:
                lines.append(f"{anchor}**{caption}**")
            elif anchor:
                lines.append(anchor)
            if table_md:
                lines.append(table_md)
        elif caption:
            # Fallback if no table found but has caption
            lines.append(f"{anchor}Table: {caption}")
        elif anchor:
            lines.append(anchor)
    else:
        # Handle regular image figures: emit real Markdown image syntax so the
        # pictures render. A figure may contain several sub-figure images.
        images = [(el.get(attr), el) for el, attr in _iter_image_elements(figure)]
        # Alt text is plain text: the rich caption may contain links, whose
        # brackets would break the image syntax.
        plain_caption = _normalize_text(caption_tag.get_text()) if caption_tag else ""

        if caption:
            lines.append(f"{anchor}Figure: {caption}")
            anchor = ""
        seen_panels: set[int] = set()
        for src, el in images:
            handled.append(el)
            if not src:
                continue
            alt = (el.get("alt") or "").strip()
            # LaTeXML's placeholder alt text carries no information
            if alt.lower() == "refer to caption":
                alt = ""
            label = _escape_markdown_alt(plain_caption or alt or "figure")
            # Sub-figure panels (id "S3.F2.sf1") are link targets of their own,
            # and may carry a sub-caption "(a) ...".
            panel = el.find_parent("figure")
            panel_anchor, panel_caption = "", ""
            if panel is not None and panel is not figure and id(panel) not in seen_panels:
                seen_panels.add(id(panel))
                if panel.get("id"):
                    panel_anchor = anchor_html(panel["id"])
                    del panel["id"]  # anchored here; the leftover pass must not repeat it
                sub_tag = panel.find("figcaption", recursive=False)
                if sub_tag and sub_tag is not caption_tag:
                    handled.append(sub_tag)
                    panel_caption = _normalize_text(_serialize_inline(sub_tag, remove_inline_citations=remove_inline_citations))
            lines.append(f"{anchor}{panel_anchor}![{label}]({src})")
            if panel_caption:
                lines.append(f"Subfigure: {panel_caption}")
            anchor = ""
        if anchor:
            lines.append(anchor)

    for tag in handled:
        tag.extract()
    rest = _serialize_children(figure, remove_inline_citations=remove_inline_citations)

    return "\n\n".join(part for part in ["\n".join(lines).strip(), *rest] if part).strip()


def _escape_markdown_alt(text: str) -> str:
    return re.sub(r"([\\\[\]])", r"\\\1", text)


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
