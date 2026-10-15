"""NameKey 精确键与规范化配置 name-key-v1（intents_decompose.md §3.2）。

NFC；由 Unicode White_Space 字符组成的连续空白折叠为一个空格，再去首尾空白；保留大小写、连字符与其他标点。
所以 `BM-25` 与 `BM25`、`BERT` 与 `bert` 是不同的键。读写使用同一配置。
"""

import re
import unicodedata

# White_Space 是 Unicode 属性，与 Python 的 str.isspace 不完全一致，这里显式列出
WHITE_SPACE = re.compile("[\u0009-\u000d\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+")
# 设计要求 Unicode 15.1；NFC 用的是 Python 自带的 unicodedata，版本如实记进 normalizer_ref
NORMALIZER = f"name-key-v1@unicode-{unicodedata.unidata_version}"


def normalize(s: str) -> str:
    return WHITE_SPACE.sub(" ", unicodedata.normalize("NFC", s)).strip()


def name_key(raw: str, kind: str, scope: str = "global") -> str:
    """NameKey.key：规范化名称、kind、scope 拼成的单个字符串，唯一约束作用在它上面。"""
    return f"{normalize(raw)}|{kind}|{scope}"
