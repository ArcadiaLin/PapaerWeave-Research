"""graph_model_v2.md 的机器可读部分：kind、字段、关系端点、命名空间、id 前缀、约束与索引。

与 docs/designs/v2/graph_model_v2.md 不一致时以文档为准，改这里。对应冻结版模型（2026-10-04）：
不表达资源版本与切分，不建 Metric；Content 为 Claim、Experiment、Contribution、Observation，另有系统记录
NameKey、Material、IngestBatch 与使用产物 Artifact。写入管线（paperweave.commit）按这里的表检查 graph-doc。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ── 类别与 kind（§2.1、§3.1、§4.1）────────────────────────────────────

KINDS = {
    "Entity": ["Paper", "Dataset", "Code", "Model", "Benchmark", "Tool"],
    "Concept": ["Method", "Task", "Issue", "Proposition"],
    "Content": ["Claim", "Experiment", "Contribution", "Observation"],
}
FAMILY = {kind: family for family, kinds in KINDS.items() for kind in kinds}  # kind → 主 Label

ENTITY = frozenset(KINDS["Entity"])
CONCEPT = frozenset(KINDS["Concept"])
CONTENT = frozenset(KINDS["Content"])
ARTIFACT = "Artifact"  # 只有主 Label，不分 kind（§8）
# 经 CheckIn 检入的共同产物的类型（paperweave.artifact.types），记在 Artifact 的 op 上。库中可能还有已下线的旧版 Agent
# 算子写的 Artifact（op 为 Extract、Check、Filter、MatrixConstruct 等），只读
ARTIFACT_TYPES = ("Leaderboard", "CompareSettings", "Verify", "Summarize", "Generate", "Skill")
SYSTEM_LABELS = frozenset({"NameKey", "Material", "IngestBatch"})

# 有名称的 kind：name 与 aliases 注册为 NameKey（§2.2、§3.2、§5）。Issue、Proposition 是陈述型，没有名称。
NAMED = ENTITY | {"Method", "Task"}

# id 形如 <前缀>_<4 位序号>
PREFIX = {
    "Paper": "paper",
    "Dataset": "dataset",
    "Code": "code",
    "Model": "model",
    "Benchmark": "bench",
    "Tool": "tool",
    "Method": "method",
    "Task": "task",
    "Issue": "issue",
    "Proposition": "prop",
    "Claim": "claim",
    "Experiment": "exp",
    "Contribution": "contrib",
    "Observation": "obs",
}

# ── 节点字段（§2.2、§3.2、§4.2）──────────────────────────────────────
# graph-doc 可写的字段。kind 由 Label 表达；aliases 存为 NameKey；material 登记为 Material。

_ENTITY_FIELDS = frozenset({"kind", "name", "aliases", "identifiers", "description", "note", "stub"})
_TERM_FIELDS = frozenset({"kind", "name", "aliases", "definition", "note", "stub"})
FIELDS = {
    **{kind: _ENTITY_FIELDS for kind in ENTITY},
    "Paper": _ENTITY_FIELDS | {"year", "material"},
    "Method": _TERM_FIELDS,
    "Task": _TERM_FIELDS,
    "Issue": frozenset({"kind", "text", "description", "note"}),
    "Proposition": frozenset({"kind", "text", "note"}),
    "Claim": frozenset({"kind", "text", "note"}),
    "Experiment": frozenset({"kind", "text", "anchors", "note"}),
    "Contribution": frozenset({"kind", "text", "stated_by", "note"}),
    "Observation": frozenset({"kind", "text", "note"}),
}
# Entity 的描述面允许类内异构（作者、许可、安装说明等，§2.2）：未列出的字段只提示，不拒绝。
OPEN_KINDS = ENTITY
# 非桩节点必须有的字段；桩节点（stub: true）只要求名称。
REQUIRED_FIELDS = {
    **{kind: frozenset({"name", "description"}) for kind in ENTITY},
    "Method": frozenset({"name", "definition"}),
    "Task": frozenset({"name", "definition"}),
    "Issue": frozenset({"text"}),
    "Proposition": frozenset({"text"}),
    "Claim": frozenset({"text"}),
    "Experiment": frozenset({"text", "anchors"}),
    "Contribution": frozenset({"text", "stated_by"}),
    "Observation": frozenset({"text"}),
}
STUB_KINDS = NAMED
# 由系统生成，graph-doc 不能写：自然键、形成信息、检索派生属性
SYSTEM_FIELDS = frozenset({"exp_key", "content_key", "formed_by", "formed_at", "embedding", "embedding_key"})
DERIVED_FIELDS = frozenset({"embedding", "embedding_key"})  # 不受版本管理，提交后补算

STATED_BY = frozenset({"paper", "agent"})
NAMESPACES = {"arxiv": True, "doi": True, "s2": True, "url": False}  # 命名空间 → 是否唯一（§2.4）

# ── 关系（§6）────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Relationship:
    """一种关系的端点与属性规则。``ends`` 中每一项是允许的（起点 kind 集合，终点 kind 集合）。"""

    ends: tuple[tuple[frozenset[str], frozenset[str]], ...]
    props: frozenset[str] = frozenset()  # 除 description、source_refs 外允许的边属性
    required: frozenset[str] = frozenset()
    same_kind: bool = False  # 两端 kind 必须相同
    symmetric: bool = False  # 语义对称：只存一个方向


GENERIC_REL_PROPS = frozenset({"description", "source_refs"})  # 除另行说明外，关系都可带（§6.2）


def _k(*names: str) -> frozenset[str]:
    return frozenset(names)


_A = _k(ARTIFACT)

RELATIONSHIPS = {
    # 6.2.1 实验参与与来源
    "FROM": Relationship(
        ends=((CONTENT | CONCEPT | {"Benchmark"}, ENTITY), (_k("Observation"), _A)),
        props=_k("locators"),
    ),
    "ABOUT": Relationship(ends=((CONTENT, ENTITY | CONCEPT | CONTENT), (_k("Observation"), _A))),
    "EVALUATES": Relationship(
        ends=((_k("Experiment"), _k("Method", "Model", "Code", "Tool")),), props=_k("role"), required=_k("role")
    ),
    "USES": Relationship(ends=((_k("Experiment"), ENTITY),), props=_k("role")),
    "ON_TASK": Relationship(ends=((_k("Experiment"), _k("Task")),)),
    "EVALUATED_ON": Relationship(ends=((_k("Experiment"), _k("Benchmark")),)),
    # 6.2.2 主张、依据与正反关系
    "SUPPORTED_BY": Relationship(ends=((_k("Claim"), _k("Experiment", "Observation")),)),
    "SUPPORTS": Relationship(
        ends=((_k("Claim"), _k("Claim")), (_k("Proposition"), _k("Proposition"))),
        props=_k("stated_by"),
        required=_k("description", "stated_by"),
    ),
    "OPPOSES": Relationship(
        ends=((_k("Claim"), _k("Claim")), (_k("Proposition"), _k("Proposition"))),
        props=_k("stated_by"),
        required=_k("description", "stated_by"),
    ),
    # 6.2.3 资源之间与资源—概念
    "PART_OF": Relationship(ends=((ENTITY, ENTITY),)),
    "DERIVED_FROM": Relationship(ends=((ENTITY, ENTITY), (_k("Method"), _k("Method")))),
    "CITES": Relationship(ends=((_k("Paper"), _k("Paper")),)),
    "IMPLEMENTS": Relationship(ends=((_k("Code", "Model"), _k("Method")),)),
    "FOR_TASK": Relationship(ends=((_k("Dataset", "Benchmark"), _k("Task")),)),
    # 6.2.4 概念之间
    "BROADER": Relationship(ends=((CONCEPT, CONCEPT),), same_kind=True),
    "HAS_PART": Relationship(ends=((_k("Method"), _k("Method")),)),
    "ADDRESSES": Relationship(ends=((_k("Method"), _k("Task")),)),
    "OVERLAPS_WITH": Relationship(ends=((CONCEPT, CONCEPT),), symmetric=True),
}
STANCE_RELS = frozenset({"SUPPORTS", "OPPOSES"})
# Artifact 的使用关系（§8）：只由 CheckIn 写入，graph-doc 不能写，但可以沿它读取。role 是记录键或参数中的角色，
# 同一终点有多个时为列表；引用材料的行范围时带 material_ref 与 locators
USED = Relationship(ends=((_A, ENTITY | CONCEPT | CONTENT | _A),), props=_k("role", "locators"))
TRAVERSABLE = {**RELATIONSHIPS, "USED": USED}  # 读取时可以走的关系
SYSTEM_RELS = frozenset({"NAMES", "MATERIAL_OF", "USED"})  # 系统与使用产物的关系，graph-doc 不能写
SYSTEM_REL_PROPS = frozenset({"material_ref", "formed_by", "formed_at", "embedding", "embedding_key"})

EVALUATES_ROLES = frozenset({"target", "baseline"})
USES_ROLES = frozenset({"training_data", "evaluation_data", "analysis_input", "tooling", "retrieval_corpus"})

# 必需的出边（§4.2、§4.5）
REQUIRED_RELS = {
    "Claim": ("FROM",),
    "Experiment": ("FROM", "EVALUATES"),
    "Contribution": ("FROM", "ABOUT"),
    "Observation": ("ABOUT",),
}

# 来源引用 <material_id>::<章节>::<start>:<end> 中 :: 之后的定位部分，行号从 1 起（§1）
LOCATOR = re.compile(r"(?P<section>.+)::(?P<start>\d+):(?P<end>\d+)")

# ── 约束与索引 ────────────────────────────────────────────────────────

# NameKey 不存成对象上的 aliases 列表，正是为了让唯一约束作用在单个字符串上（§5）
CONSTRAINTS = [
    "CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (n:Entity) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT concept_id IF NOT EXISTS FOR (n:Concept) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT namekey_key IF NOT EXISTS FOR (k:NameKey) REQUIRE k.key IS UNIQUE",
    # 自然键（commit_contract.md §5）与系统记录；Observation 与 Agent 贡献不设自然键
    "CREATE CONSTRAINT content_id IF NOT EXISTS FOR (n:Content) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT experiment_key IF NOT EXISTS FOR (n:Experiment) REQUIRE n.exp_key IS UNIQUE",
    "CREATE CONSTRAINT content_key IF NOT EXISTS FOR (n:Content) REQUIRE n.content_key IS UNIQUE",
    # 论文材料的 id 由内容哈希给出，按 id 唯一即按内容唯一；共同产物每个版本一份 Material，内容可以与早先的版本
    # 相同（改回去），所以不再要求内容哈希唯一
    "CREATE CONSTRAINT material_id IF NOT EXISTS FOR (m:Material) REQUIRE m.id IS UNIQUE",
    "CREATE CONSTRAINT artifact_id IF NOT EXISTS FOR (n:Artifact) REQUIRE n.id IS UNIQUE",
    # 旧版 Agent 算子（已下线）写的 Artifact：相同 artifact_key 的写入曾是重试；库中还有这样的产物，约束保留
    "CREATE CONSTRAINT artifact_key IF NOT EXISTS FOR (n:Artifact) REQUIRE n.artifact_key IS UNIQUE",
    # 共同产物的身份键：一个键只有一份产物（operators.md §5.4）
    "CREATE CONSTRAINT artifact_identity IF NOT EXISTS FOR (n:Artifact) REQUIRE n.key IS UNIQUE",
]
# 已退役的约束：建库时删除。result_row_key 属于行级入库（f95631b），首版改为报告级后不用；
# batch_id 属于旧写入路径的 IngestBatch，已由 graph-vc 的 Commit 取代；material_hash 见上面 material_id
RETIRED_CONSTRAINTS = ["result_row_key", "batch_id", "material_hash"]

# 全文索引：名称 → (Label, 字段, 分词方式)。检索字段按类别声明（intents_decompose.md §6.2）
# - namekey_raw：名称词面通道。名称与 alias 都在 NameKey 上，对象上没有 aliases 列表；默认分词，不做词形还原
# - entity_texts / concept_texts / content_texts：各类的自由文本字段；english 分词
FULLTEXT = {
    "namekey_raw": ("NameKey", ["raw"], "standard-no-stop-words"),
    "entity_texts": ("Entity", ["description"], "english"),
    "concept_texts": ("Concept", ["definition", "text"], "english"),  # 术语型写 definition，陈述型写 text
    "content_texts": ("Content", ["text"], "english"),
    "artifact_texts": ("Artifact", ["title", "abs"], "english"),
}
TEXT_FIELDS = {  # 文本通道与向量共用
    "Entity": ["description"],
    "Concept": ["definition", "text"],
    "Content": ["text"],
    "Artifact": ["title", "abs"],
}
DESCRIBED_RELS = ["CITES", "SUPPORTS", "OPPOSES", "IMPLEMENTS", "ADDRESSES"]  # 边上带 description，建关系向量索引（§5）

# 版本管理下可以出现的 Label 与关系类型（graph-vc 的词表限制）
NODE_LABELS = frozenset(KINDS) | ENTITY | CONCEPT | CONTENT | SYSTEM_LABELS | {ARTIFACT}
REL_TYPES = frozenset(RELATIONSHIPS) | SYSTEM_RELS


def kind_of(labels: frozenset[str] | set[str]) -> str | None:
    """节点的 kind（次级 Label）；系统记录与 Artifact 返回 None。"""
    kinds = [label for label in labels if label in FAMILY]
    return kinds[0] if len(kinds) == 1 else None
