"""neo4j-e09 的连接、约束与全文索引。"""

from neo4j import GraphDatabase, RoutingControl

from ..config import NEO4J_AUTH, NEO4J_DB, NEO4J_URI
from ..model.schema import CONSTRAINTS, FULLTEXT, RETIRED_CONSTRAINTS

# 空库时查不存在的属性键或 Label 会收到 UNRECOGNIZED 类提示，关掉
driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH, notifications_disabled_classifications=["UNRECOGNIZED"])


def q(cypher: str, **params) -> list[dict]:
    """只读查询的简写。"""
    records, _, _ = driver.execute_query(cypher, params, database_=NEO4J_DB, routing_=RoutingControl.READ)
    return [r.data() for r in records]


def ensure_schema():
    """建约束与全文索引，全部 IF NOT EXISTS，重跑无副作用；删除已退役的约束。

    `CREATE ... IF NOT EXISTS` 不会改已有索引的配置，所以覆盖的 Label、字段或分词方式与声明不一致的全文索引先删再重建。
    """
    existing = {r["name"]: (r["labels"], r["properties"], r["analyzer"]) for r in
                q("SHOW FULLTEXT INDEXES YIELD name, labelsOrTypes, properties, options "
                  "RETURN name, labelsOrTypes AS labels, properties, options.indexConfig.`fulltext.analyzer` AS analyzer")}
    for name, (label, fields, analyzer) in FULLTEXT.items():
        want = ([label], fields, analyzer)
        if name in existing and existing[name] != want:
            print(f"重建 {name}：{existing[name]} -> {want}")
            driver.execute_query(f"DROP INDEX {name}", database_=NEO4J_DB)
    for name in RETIRED_CONSTRAINTS:
        driver.execute_query(f"DROP CONSTRAINT {name} IF EXISTS", database_=NEO4J_DB)
    for stmt in CONSTRAINTS:
        driver.execute_query(stmt, database_=NEO4J_DB)
    for name, (label, fields, analyzer) in FULLTEXT.items():
        driver.execute_query(
            f"CREATE FULLTEXT INDEX {name} IF NOT EXISTS FOR (n:{label}) ON EACH [{', '.join('n.' + f for f in fields)}] "
            f"OPTIONS {{indexConfig: {{`fulltext.analyzer`: '{analyzer}'}}}}", database_=NEO4J_DB)
    driver.execute_query("CALL db.awaitIndexes(300)", database_=NEO4J_DB)   # 新建或重建的索引填充完再往下走
