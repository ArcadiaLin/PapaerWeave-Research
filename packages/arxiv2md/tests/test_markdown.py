"""Tests for Markdown serialization."""

from __future__ import annotations

from arxiv2md.markdown import convert_fragment_to_markdown, unlink_dangling_fragment_links


def test_math_and_tables_render() -> None:
    html = """
    <div class="ltx_para"><p>Equation <math>
        <annotation encoding="application/x-tex">x+y</annotation>
    </math></p></div>
    <table class="ltx_tabular">
        <tr><th>A</th><th>B</th></tr>
        <tr><td>1</td><td>2</td></tr>
    </table>
    <table class="ltx_equationgroup">
        <tr><td>E = mc^2 (1)</td></tr>
    </table>
    """

    markdown = convert_fragment_to_markdown(html)

    assert "$x+y$" in markdown
    assert "| A | B |" in markdown
    assert "| 1 | 2 |" in markdown
    assert "$$" in markdown
    assert "E = mc^2" in markdown


def test_table_with_tbody() -> None:
    """Test that tables with tbody/thead/tfoot structure are correctly converted."""
    html = """
    <table class="ltx_tabular">
        <tbody>
            <tr><th>Model</th><th>Accuracy</th></tr>
            <tr><td>Llama-7B</td><td>70.12</td></tr>
            <tr><td>Llama-13B</td><td>72.39</td></tr>
        </tbody>
    </table>
    """

    markdown = convert_fragment_to_markdown(html)

    # Should contain table structure
    assert "| Model | Accuracy |" in markdown
    assert "| --- | --- |" in markdown
    assert "| Llama-7B | 70.12 |" in markdown
    assert "| Llama-13B | 72.39 |" in markdown


def test_table_with_thead_tbody() -> None:
    """Test that tables with thead and tbody are correctly converted."""
    html = """
    <table class="ltx_tabular">
        <thead>
            <tr><th>Method</th><th>Result</th></tr>
        </thead>
        <tbody>
            <tr><td>Prune SW</td><td>0.0%</td></tr>
            <tr><td>Prune Non-SW</td><td>68.5%</td></tr>
        </tbody>
    </table>
    """

    markdown = convert_fragment_to_markdown(html)

    # Should contain table structure
    assert "| Method | Result |" in markdown
    assert "| Prune SW | 0.0% |" in markdown
    assert "| Prune Non-SW | 68.5% |" in markdown


def test_table_inside_figure() -> None:
    """Test that tables wrapped in figure elements (ltx_table) are correctly converted."""
    html = """
    <figure class="ltx_table" id="S3.T1">
        <table class="ltx_tabular ltx_centering ltx_guessed_headers ltx_align_middle">
            <thead class="ltx_thead">
                <tr class="ltx_tr">
                    <th class="ltx_td ltx_align_left ltx_th ltx_th_column">Model</th>
                    <th class="ltx_td ltx_align_center ltx_th ltx_th_column">Arc-c</th>
                    <th class="ltx_td ltx_align_center ltx_th ltx_th_column">Arc-e</th>
                </tr>
            </thead>
            <tbody class="ltx_tbody">
                <tr class="ltx_tr">
                    <td class="ltx_td ltx_align_left">Original</td>
                    <td class="ltx_td ltx_align_center">41.81</td>
                    <td class="ltx_td ltx_align_center">75.29</td>
                </tr>
                <tr class="ltx_tr">
                    <td class="ltx_td ltx_align_left">Prune SW</td>
                    <td class="ltx_td ltx_align_center">19.80</td>
                    <td class="ltx_td ltx_align_center">39.60</td>
                </tr>
            </tbody>
        </table>
        <figcaption class="ltx_caption ltx_centering">
            <span class="ltx_tag ltx_tag_table">Table 1: </span>
            <span class="ltx_text ltx_font_bold">Super Weight Importance</span>.
            Pruning the super weight significantly impairs quality.
        </figcaption>
    </figure>
    """

    markdown = convert_fragment_to_markdown(html)

    # Should contain the caption
    assert "Table 1:" in markdown
    assert "Super Weight Importance" in markdown
    # Should contain the actual table data
    assert "| Model | Arc-c | Arc-e |" in markdown
    assert "| Original | 41.81 | 75.29 |" in markdown
    assert "| Prune SW | 19.80 | 39.60 |" in markdown


def test_remove_inline_citations_citep() -> None:
    """Test that parenthetical citations (citep) are fully removed."""
    html = (
        '<p>We study deceptive alignment '
        '<cite class="ltx_cite ltx_citemacro_citep">'
        '(Anthropic, <a class="ltx_ref" href="#bib.bib4">2024</a>; '
        'OpenAI, <a class="ltx_ref" href="#bib.bib29">2024</a>)'
        '</cite> in large models.</p>'
    )

    result = convert_fragment_to_markdown(html, remove_inline_citations=True)
    assert "Anthropic" not in result
    assert "OpenAI" not in result
    assert "2024" not in result
    assert "deceptive alignment" in result
    assert "large models" in result


def test_remove_inline_citations_citet() -> None:
    """Test that textual citations (citet) are fully removed."""
    html = (
        '<p>As shown by '
        '<cite class="ltx_cite ltx_citemacro_citet">'
        'Treutlein et al. (<a class="ltx_ref" href="#bib.bib40">2024</a>)'
        '</cite>, this is important.</p>'
    )

    result = convert_fragment_to_markdown(html, remove_inline_citations=True)
    assert "Treutlein" not in result
    assert "this is important" in result


def test_remove_inline_citations_preserves_when_disabled() -> None:
    """Test that citations are preserved as plain text when removal is disabled."""
    html = (
        '<p>We study '
        '<cite class="ltx_cite ltx_citemacro_citep">'
        '(Anthropic, <a class="ltx_ref" href="#bib.bib4">2024</a>)'
        '</cite> things.</p>'
    )

    result = convert_fragment_to_markdown(html, remove_inline_citations=False)
    assert "Anthropic" in result
    assert "2024" in result


def test_remove_inline_citations_ignores_non_ltx_cite() -> None:
    """Test that plain cite tags without ltx_cite class are not removed."""
    html = '<p>See <cite>A Book Title</cite> for details.</p>'

    result = convert_fragment_to_markdown(html, remove_inline_citations=True)
    assert "A Book Title" in result


def test_resolve_relative_image_urls() -> None:
    """Test that relative image paths are resolved to absolute URLs."""
    html = """
    <figure>
        <img src="extracted/figures/fig1.png" alt="Architecture diagram"/>
        <figcaption>Figure 1: System overview</figcaption>
    </figure>
    """

    result = convert_fragment_to_markdown(html, base_url="https://arxiv.org/html/2501.11120v1")
    assert "https://arxiv.org/html/2501.11120v1/extracted/figures/fig1.png" in result
    assert "Figure 1: System overview" in result


def test_absolute_image_urls_unchanged() -> None:
    """Test that absolute image URLs are not modified."""
    html = """
    <figure>
        <img src="https://arxiv.org/html/2501.11120v1/assets/img.png" alt="Diagram"/>
        <figcaption>Figure 2: Results</figcaption>
    </figure>
    """

    result = convert_fragment_to_markdown(html, base_url="https://ar5iv.labs.arxiv.org/html/2501.11120v1")
    assert "https://arxiv.org/html/2501.11120v1/assets/img.png" in result


def test_no_base_url_preserves_relative_paths() -> None:
    """Test that without base_url, relative paths are preserved as-is."""
    html = """
    <figure>
        <img src="extracted/fig1.png" alt="Diagram"/>
    </figure>
    """

    result = convert_fragment_to_markdown(html)
    assert "extracted/fig1.png" in result


def test_citation_links_keep_in_document_anchor() -> None:
    """Citation links keep their #bib fragment; bibliography entries get anchors."""
    html = """
    <div class="ltx_para"><p>See <cite class="ltx_cite"><a class="ltx_ref" href="#bib.bib7">[7]</a></cite>.</p></div>
    <section class="ltx_bibliography">
        <ul class="ltx_biblist">
            <li class="ltx_bibitem" id="bib.bib7">Smith et al. A title.</li>
        </ul>
    </section>
    """

    result = convert_fragment_to_markdown(html)

    assert "[[7]](#bib.bib7)" in result
    assert '<a id="bib.bib7" name="bib.bib7"></a>Smith et al. A title.' in result


def test_absolute_citation_href_reduced_to_fragment() -> None:
    """Absolute arxiv.org citation hrefs are reduced to the in-document fragment."""
    html = '<p>See <a class="ltx_ref" href="https://arxiv.org/html/2501.11120v1#bib.bib3">[3]</a>.</p>'

    result = convert_fragment_to_markdown(html)

    assert "[[3]](#bib.bib3)" in result
    assert "arxiv.org" not in result


def test_citation_links_removed_when_requested() -> None:
    """remove_inline_citations=True still removes citation links entirely."""
    html = '<p>See <a class="ltx_ref" href="#bib.bib7">[7]</a>.</p>'

    result = convert_fragment_to_markdown(html, remove_inline_citations=True)

    assert "#bib" not in result
    assert "[7]" not in result


def test_image_src_with_paper_id_prefix_resolves_against_parent() -> None:
    """src that already includes the paper-id prefix resolves against the parent dir."""
    html = """
    <figure>
        <img src="1706.03762v7/Figures/ModalNet-21.png" alt="Architecture"/>
    </figure>
    """

    result = convert_fragment_to_markdown(html, base_url="https://arxiv.org/html/1706.03762v7")

    assert "https://arxiv.org/html/1706.03762v7/Figures/ModalNet-21.png" in result
    assert "1706.03762v7/1706.03762v7" not in result


def test_image_src_with_versioned_prefix_under_versionless_base() -> None:
    """src="1207.5777v1/intro1.png" under base .../html/1207.5777 must not duplicate the id."""
    html = """
    <figure>
        <img src="1207.5777v1/intro1.png" alt="Evolution"/>
    </figure>
    """

    result = convert_fragment_to_markdown(html, base_url="https://arxiv.org/html/1207.5777")

    assert "https://arxiv.org/html/1207.5777v1/intro1.png" in result
    assert "1207.5777/1207.5777v1" not in result


def test_numbered_equation_table_emits_clean_display_math() -> None:
    """Numbered equation tables must not nest $...$ inside $$...$$ (KaTeX rejects that)."""
    html = (
        '<table class="ltx_equationgroup"><tr>'
        '<td><math><annotation encoding="application/x-tex">'
        "\\mathrm{Attention}(Q,K,V)=\\mathrm{softmax}(\\frac{QK^{T}}{\\sqrt{d_{k}}})V"
        "</annotation></math></td>"
        "<td>(1)</td>"
        "</tr></table>"
    )

    result = convert_fragment_to_markdown(html)

    assert "$$\n\\mathrm{Attention}(Q,K,V)=\\mathrm{softmax}(\\frac{QK^{T}}{\\sqrt{d_{k}}})V \\tag{1}\n$$" in result
    assert "$" not in result.replace("$$", "")


def test_multi_equation_table_splits_into_separate_blocks() -> None:
    html = (
        '<table class="ltx_equationgroup">'
        '<tr><td><math><annotation encoding="application/x-tex">a=b</annotation></math></td><td>(1)</td></tr>'
        '<tr><td><math><annotation encoding="application/x-tex">c=d</annotation></math></td><td>(2)</td></tr>'
        "</table>"
    )

    result = convert_fragment_to_markdown(html)

    assert "$$\na=b \\tag{1}\n$$" in result
    assert "$$\nc=d \\tag{2}\n$$" in result


def test_figure_emits_markdown_image() -> None:
    html = """
    <figure class="ltx_figure">
        <img src="x1.png" alt="Refer to caption"/>
        <figcaption>Figure 1: Architecture.</figcaption>
    </figure>
    """

    result = convert_fragment_to_markdown(html, base_url="https://arxiv.org/html/1706.03762v7")

    assert "![Figure 1: Architecture.](https://arxiv.org/html/1706.03762v7/x1.png)" in result


def test_figure_with_multiple_images_emits_all() -> None:
    html = """
    <figure class="ltx_figure">
        <img src="x1.png" alt="left"/>
        <img src="x2.png" alt="right"/>
        <figcaption>Figure 2: Two views.</figcaption>
    </figure>
    """

    result = convert_fragment_to_markdown(html, base_url="https://arxiv.org/html/1706.03762v7")

    assert result.count("![") == 2
    assert "x1.png" in result and "x2.png" in result


def test_svg_object_figure_emits_markdown_image() -> None:
    """LaTeXML embeds SVG figures as <object data=...> rather than <img>."""
    html = """
    <figure class="ltx_figure">
        <object type="image/svg+xml" data="fig3.svg"></object>
        <figcaption>Figure 3: Attention.</figcaption>
    </figure>
    """

    result = convert_fragment_to_markdown(html, base_url="https://arxiv.org/html/1706.03762v7")

    assert "![Figure 3: Attention.](https://arxiv.org/html/1706.03762v7/fig3.svg)" in result


def _tex(latex: str) -> str:
    return f'<math><annotation encoding="application/x-tex">{latex}</annotation></math>'


def _eqn_row(*cells: str, eqno: str | None = None) -> str:
    """One LaTeXML equation row: padding cells, content cells, optional number cell."""
    tds = '<td class="ltx_eqn_cell ltx_eqn_center_padleft"></td>'
    tds += "".join(f'<td class="ltx_td ltx_eqn_cell">{cell}</td>' for cell in cells)
    tds += '<td class="ltx_eqn_cell ltx_eqn_center_padright"></td>'
    if eqno:
        tds += f'<td class="ltx_eqn_cell ltx_eqn_eqno" rowspan="1"><span>{eqno}</span></td>'
    return f'<tr class="ltx_equation ltx_eqn_row">{tds}</tr>'


def test_aligned_equation_cells_stay_in_one_block() -> None:
    """lhs and rhs cells of an align row belong to one equation, not two blocks."""
    html = (
        '<table class="ltx_equationgroup ltx_eqn_align ltx_eqn_table">'
        '<tbody id="S3.Ex1">' + _eqn_row(_tex("\\displaystyle\\mathrm{MultiHead}(Q,K,V)"), _tex("\\displaystyle=\\mathrm{Concat}(h_1,h_2)W^{O}")) + "</tbody>"
        '<tbody id="S3.Ex2">' + _eqn_row(_tex("\\displaystyle\\text{where}~h_{i}"), _tex("\\displaystyle=\\mathrm{Attention}(QW_i)")) + "</tbody>"
        "</table>"
    )

    result = convert_fragment_to_markdown(html)

    assert result.count("$$") == 4  # two equations, two blocks
    assert "$$\n\\displaystyle\\mathrm{MultiHead}(Q,K,V) \\displaystyle=\\mathrm{Concat}(h_1,h_2)W^{O}\n$$" in result
    assert '<a id="S3.Ex1" name="S3.Ex1"></a>' in result


def test_multiline_equation_becomes_aligned_with_single_tag() -> None:
    html = (
        '<table class="ltx_equationgroup ltx_eqn_align ltx_eqn_table">'
        '<tbody id="S2.E3">'
        + _eqn_row(_tex("\\displaystyle L"), _tex("\\displaystyle=a+b"), eqno="(3)")
        + _eqn_row("", _tex("\\displaystyle\\quad+c"))
        + "</tbody></table>"
    )

    result = convert_fragment_to_markdown(html)

    assert result.count("$$") == 2
    assert "\\begin{aligned}\n\\displaystyle L & \\displaystyle=a+b \\\\\n & \\displaystyle\\quad+c\n\\end{aligned} \\tag{3}" in result


def test_equation_number_formats_and_text_cells() -> None:
    html = (
        '<table class="ltx_equation ltx_eqn_table" id="A1.E1">'
        + _eqn_row(_tex("x_i") + " for all " + _tex("i"), eqno="(A.1)")
        + "</table>"
    )

    result = convert_fragment_to_markdown(html)

    assert "$$\nx_i \\text{ for all } i \\tag{A.1}\n$$" in result
    assert '<a id="A1.E1" name="A1.E1"></a>' in result


def test_image_alt_is_plain_text_when_caption_has_links() -> None:
    html = """
    <figure class="ltx_figure" id="S2.F3">
        <img src="https://arxiv.org/html/x/fig3.png" alt="Refer to caption"/>
        <figcaption>Figure 3: Details in <a href="#A3.SS1">Section C.1</a> for $[0,1]$.</figcaption>
    </figure>
    """

    result = convert_fragment_to_markdown(html)

    assert "Figure: Figure 3: Details in [Section C.1](#A3.SS1) for $[0,1]$." in result
    assert "![Figure 3: Details in Section C.1 for $\\[0,1\\]$.](https://arxiv.org/html/x/fig3.png)" in result
    assert '<a id="S2.F3" name="S2.F3"></a>Figure:' in result


def test_figure_prefers_own_caption_and_anchors_panels() -> None:
    html = """
    <figure class="ltx_figure" id="S4.F2">
        <figure class="ltx_figure ltx_figure_panel" id="S4.F2.sf1">
            <img src="https://arxiv.org/html/x/a.png"/><figcaption>(a) left</figcaption>
        </figure>
        <figure class="ltx_figure ltx_figure_panel" id="S4.F2.sf2">
            <img src="https://arxiv.org/html/x/b.png"/><figcaption>(b) right</figcaption>
        </figure>
        <figcaption>Figure 2: Whole figure.</figcaption>
    </figure>
    """

    result = convert_fragment_to_markdown(html)

    assert "Figure: Figure 2: Whole figure." in result
    assert "(a) left" not in result.split("\n")[0]
    assert '<a id="S4.F2.sf1" name="S4.F2.sf1"></a>![Figure 2: Whole figure.](https://arxiv.org/html/x/a.png)' in result
    assert '<a id="S4.F2.sf2" name="S4.F2.sf2"></a>![' in result


def test_table_figure_gets_anchor() -> None:
    html = """
    <figure class="ltx_table" id="S5.T1">
        <figcaption>Table 1: Scores.</figcaption>
        <table class="ltx_tabular"><tr><td>A</td></tr></table>
    </figure>
    """

    result = convert_fragment_to_markdown(html)

    assert '<a id="S5.T1" name="S5.T1"></a>**Table 1: Scores.**' in result


def test_only_bibliography_list_items_get_anchors() -> None:
    html = """
    <ul class="ltx_itemize"><li id="S3.I1.i1">bullet</li></ul>
    <ul class="ltx_biblist"><li id="bib.bib1">Ref one.</li></ul>
    """

    result = convert_fragment_to_markdown(html)

    assert "S3.I1.i1" not in result
    assert '<a id="bib.bib1" name="bib.bib1"></a>Ref one.' in result


def test_unlink_dangling_fragment_links() -> None:
    md = (
        '<a id="S3" name="S3"></a>\n## 3 Model\n\n'
        "See [3](#S3), [Figure 9](#S9.F9) and [[12](#bib.bib12)]. "
        "![alt \\[x\\]](#S9.F9) [site](https://example.org)"
    )

    result = unlink_dangling_fragment_links(md)

    assert "[3](#S3)" in result
    assert "Figure 9 and" in result
    assert "[12]" in result and "(#bib.bib12)" not in result
    assert "![alt \\[x\\]](#S9.F9)" in result  # images untouched
    assert "[site](https://example.org)" in result


def test_rowspan_and_colspan_keep_columns_aligned() -> None:
    html = """
    <table class="ltx_tabular">
        <tr><td rowspan="2">Model</td><td colspan="2">BLEU</td></tr>
        <tr><td>EN-DE</td><td>EN-FR</td></tr>
        <tr><td rowspan="2">Group</td><td>1.0</td><td>2.0</td></tr>
        <tr><td>3.0</td><td>4.0</td></tr>
    </table>
    """

    result = convert_fragment_to_markdown(html)

    assert "| Model | BLEU |  |" in result
    assert "|  | EN-DE | EN-FR |" in result
    assert "| Group | 1.0 | 2.0 |" in result
    assert "|  | 3.0 | 4.0 |" in result


def test_inline_span_tabular_inside_table_figure() -> None:
    # LaTeXML renders a \\resizebox-ed tabular as spans; it must still become a table with its spans.
    html = """
    <figure class="ltx_table" id="S4.T2">
      <figcaption class="ltx_caption">Table 2: MSE results.</figcaption>
      <div class="ltx_inline-block ltx_transformed_outer"><p class="ltx_p"><span class="ltx_text">
        <span class="ltx_tabular ltx_guessed_headers"><span class="ltx_tbody">
          <span class="ltx_tr"><span class="ltx_td ltx_th">Dataset</span>
            <span class="ltx_td ltx_colspan ltx_colspan_2">ETTh1</span></span>
          <span class="ltx_tr"><span class="ltx_td ltx_rowspan ltx_rowspan_2">Horizon</span>
            <span class="ltx_td">96</span><span class="ltx_td">192</span></span>
          <span class="ltx_tr"><span class="ltx_td">0.359</span><span class="ltx_td">0.397</span></span>
        </span></span>
      </span></p></div>
    </figure>
    """

    result = convert_fragment_to_markdown(html)

    assert "Table:" not in result
    assert "| Dataset | ETTh1 |  |" in result
    assert "| Horizon | 96 | 192 |" in result
    assert "|  | 0.359 | 0.397 |" in result


def test_table_cell_pipe_is_escaped() -> None:
    html = '<table class="ltx_tabular"><tr><td>a</td></tr><tr><td>x | y</td></tr></table>'
    assert "| x \\| y |" in convert_fragment_to_markdown(html)


def test_loose_text_in_block_containers_is_kept() -> None:
    html = '<div class="ltx_block"><span>loose</span> text <em>here</em><p>para</p>tail</div>'

    result = convert_fragment_to_markdown(html)

    assert result == "loose text *here*\n\npara\n\ntail"


def test_algorithm_becomes_code_block_with_numbers_nesting_and_math() -> None:
    em, en, hair = "\u2003", "\u2002", "\u200a"
    level1 = em + en + hair  # LaTeXML's rendering of one nesting level
    html = f"""
    <figure class="ltx_float ltx_float_algorithm" id="alg1">
        <figcaption class="ltx_caption">Algorithm 1 Training</figcaption>
        <div class="ltx_listing">
            <div class="ltx_listingline"><span class="ltx_tag ltx_tag_listingline">1:</span>
            <span>for</span> <math><annotation encoding="application/x-tex">p\\in D</annotation></math> <span>do</span></div>
            <div class="ltx_listingline"><span class="ltx_tag ltx_tag_listingline">2:</span>
            <span>{level1}</span><math><annotation encoding="application/x-tex">x_0\\sim q</annotation></math></div>
            <div class="ltx_listingline"><span class="ltx_tag ltx_tag_listingline">10:</span>
            <span>{level1 * 2}</span><span>## not a heading</span></div>
            <div class="ltx_listingline"><span class="ltx_tag ltx_tag_listingline">11:</span>
            <span>return</span></div>
        </div>
    </figure>
    """

    result = convert_fragment_to_markdown(html)

    assert '<a id="alg1" name="alg1"></a>Figure: Algorithm 1 Training' in result
    assert (
        "```\n"
        " 1: for $p\\in D$ do\n"
        " 2:     $x_0\\sim q$\n"
        "10:         ## not a heading\n"
        "11: return\n"
        "```"
    ) in result


def test_figure_leftovers_are_serialized() -> None:
    html = """
    <figure class="ltx_table" id="S1.T1">
        <figcaption>Table 1: T.</figcaption>
        <table class="ltx_tabular"><tr><td>A</td></tr><tr><td>1</td></tr></table>
        <ul class="ltx_itemize"><li>footnote about the table</li></ul>
    </figure>
    """

    result = convert_fragment_to_markdown(html)

    assert result.index("| A |") < result.index("- footnote about the table")


def test_panel_caption_not_used_as_outer_caption() -> None:
    html = """
    <figure class="ltx_figure" id="S3.fig1">
        <figure class="ltx_figure_panel ltx_float_algorithm" id="alg1">
            <figcaption>Algorithm 1 Training</figcaption>
            <div class="ltx_listing"><div class="ltx_listingline">repeat</div></div>
        </figure>
    </figure>
    """

    result = convert_fragment_to_markdown(html)

    assert '<a id="alg1" name="alg1"></a>Figure: Algorithm 1 Training' in result
    assert result.count("Algorithm 1 Training") == 1


def test_lstlisting_uses_embedded_source_as_code_block() -> None:
    import base64

    source = "    def f(x):\n        return x  # ## not a heading\n"
    data = base64.b64encode(source.encode()).decode()
    html = f"""
    <div class="ltx_listing ltx_lst_language_Python ltx_lstlisting">
        <div class="ltx_listing_data"><a href="data:text/plain;base64,{data}" download="">⬇</a></div>
        <div class="ltx_listingline"><span class="ltx_lst_space"> </span>def f(x):</div>
        <div class="ltx_listingline"><span class="ltx_lst_space"> </span>return x</div>
    </div>
    """

    result = convert_fragment_to_markdown(html)

    assert result == "```python\ndef f(x):\n    return x  # ## not a heading\n```"


def test_lstlisting_without_source_falls_back_to_lines() -> None:
    html = """
    <blockquote>
        <p>Prompt:</p>
        <div class="ltx_listing ltx_lstlisting">
            <div class="ltx_listingline">## Task</div>
            <div class="ltx_listingline">- item with ``` fence</div>
        </div>
    </blockquote>
    """

    result = convert_fragment_to_markdown(html)

    assert result == "> Prompt:\n>\n> ````\n> ## Task\n> - item with ``` fence\n> ````"


def test_escaped_underscore_in_math_is_preserved() -> None:
    html = '<p><math><annotation encoding="application/x-tex">\\{\\text{code\\_template}\\}+x\\_y</annotation></math></p>'

    result = convert_fragment_to_markdown(html)

    assert result == "$\\{\\text{code\\_template}\\}+x\\_y$"
