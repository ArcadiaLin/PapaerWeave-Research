"""到 ``PAPERWEAVE_NEO4J_URI`` 所指的库的连接（:mod:`paperweave.config`）。命令行、MCP 服务与脚本从这里取连接。"""

from neo4j import Driver, GraphDatabase

from ..config import NEO4J_AUTH, NEO4J_URI


def connect(uri: str = NEO4J_URI) -> Driver:
    """空库时查不存在的属性键或 Label 会收到 UNRECOGNIZED 类提示，向量检索过程收到 DEPRECATION 类提示，都关掉。"""
    return GraphDatabase.driver(uri, auth=NEO4J_AUTH, notifications_disabled_classifications=["UNRECOGNIZED", "DEPRECATION"])


__all__ = ["connect"]
