"""检索的查询词：小数整个保留，与索引的分词一致。不连库。"""

from __future__ import annotations

from paperweave.query.search import _lucene


def test_decimals_stay_whole_and_words_are_lowercased_once() -> None:
    assert _lucene("Autoformer ETTh1 MSE 0.505") == "autoformer etth1 mse 0.505"
    assert _lucene("1.058, 2.169 / 4.721 (ETTh2)") == "1.058 2.169 4.721 etth2"
    assert _lucene("PatchTST/42 patchtst") == "patchtst 42"
