"""PaperWeave：按 v2 数据模型（docs/designs/v2/graph_model_v2.md）入库真实论文，检验算子。

- ``operators/``：算子，``db/`` 由中间件执行，``agent/`` 由 Agent 给内容、中间件校验后写成 Artifact；
- ``model/``：数据模型与引用的写法；``store/``：连接、库的版本记录与约束索引、向量；
- ``query/``：读取共用的条件、融合、读视图与材料；``commit/``：graph-doc 的写入管线；
- ``artifact/``：Artifact 的文档、写入与过期；
- ``cli.py``：命令行入口 ``python -m paperweave``。
"""
