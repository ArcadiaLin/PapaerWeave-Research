"""连接与库：算子共用的环境 :class:`Store`、库的版本记录与约束索引（database）、连接（graph）与向量（embedding）。

``graph`` 与 ``embedding`` 在导入时建立到 ``E09_NEO4J_URI`` 的连接，这里不导入它们。
"""

from .database import UnversionedDatabaseError, check_versioned, index_statements, open_graph, setup_database
from .store import ContractError, Embed, Store

__all__ = [
    "ContractError",
    "Embed",
    "Store",
    "UnversionedDatabaseError",
    "check_versioned",
    "index_statements",
    "open_graph",
    "setup_database",
]
