"""Artifact 文档的文件名：取标题，去掉不能用的字符，按字节截断，重复时加序号。不连库。"""

from __future__ import annotations

import pytest

from paperweave.artifact.document import NAME_BYTES, file_name


@pytest.mark.parametrize(
    ("title", "n", "expected"),
    [
        ("DLinear vs PatchTST on ETTh1", 0, "DLinear vs PatchTST on ETTh1.md"),
        ("DLinear vs PatchTST on ETTh1", 2, "DLinear vs PatchTST on ETTh1 (2).md"),
        ("ETTh1: T=96/336?", 0, "ETTh1 T=96 336.md"),  # Linux 与 Windows 文件名中不能用的字符
        ("比较 DLinear 与 PatchTST", 1, "比较 DLinear 与 PatchTST (1).md"),
        ("..\n../x  ", 0, "x.md"),
        ("  ", 0, "artifact.md"),
    ],
)
def test_file_name(title: str, n: int, expected: str) -> None:
    assert file_name(title, n) == expected


def test_long_titles_are_cut_on_a_character_boundary() -> None:
    name = file_name("结果" * 200, 12)
    assert name.endswith(" (12).md") and len(name.removesuffix(" (12).md").encode("utf-8")) <= NAME_BYTES
    name.encode("utf-8").decode("utf-8")
