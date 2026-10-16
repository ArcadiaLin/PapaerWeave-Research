"""graph_doc：graph-doc（借用 Cypher 动词的 YAML 改动文档）的解析与求差。见 README。"""

from .document import SECTIONS, VERSION, VERSIONS, DocEdge, DocNode, Document, from_data, is_temp, load, parse
from .errors import DiffError, DocError, GraphDocError
from .fragment import Fragment, FragmentNode, diff

__all__ = [
    "SECTIONS",
    "VERSION",
    "VERSIONS",
    "DiffError",
    "DocEdge",
    "DocError",
    "DocNode",
    "Document",
    "Fragment",
    "FragmentNode",
    "GraphDocError",
    "diff",
    "from_data",
    "is_temp",
    "load",
    "parse",
]
