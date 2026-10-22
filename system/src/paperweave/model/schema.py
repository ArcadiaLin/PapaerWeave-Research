"""数据模型 V3 的机器可读部分（docs/designs/v3/data_model.md）：kind、字段、关系、约束与索引。

与文档不一致时以文档为准，改这里。这里是**单一来源**：写入检查（:mod:`paperweave.commit`）、读取投影
（:mod:`paperweave.query`）、``checkout`` 给出的空白模板与 MCP 工具说明中的 kind 列表都从这里生成，不在别处另写一份。

- 三类证据节点：Entity（有外部标识的资源）、Concept（共享概念）、Content（某篇论文在某处说的话）。
- 系统记录：NameKey（名称与别名）、Material（固定来源与产物文档的文件）；产物 Artifact 只有主 Label。
- 证据的来源是外部来源 ID（论文 ``2205.13504v2``、代码 ``<仓库>@<commit>``），Paper 与 Code 用 ``source`` 声明，
  锚点写作 ``<来源 ID>::<起>:<止>``（docs/experiments/f3/2026-10-22-f3-design.md §4.1）。
- 关系都是“具名类型 + description + extra + anchor”的同一结构，词表由工作负载推出，词表外的语义用 ``RELATES_TO``。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ── kind ──────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Kind:
    """一个 kind：所属类别、id 前缀、独有字段、能否建桩，以及给写者看的一句话含义。"""

    family: str
    prefix: str
    gloss: str
    own_fields: tuple[str, ...] = ()
    stub: bool = False


KIND_SPECS: dict[str, Kind] = {
    "Paper": Kind("Entity", "paper", "a paper's bibliographic object", ("year", "source"), stub=True),
    "Dataset": Kind("Entity", "dataset", "data itself, or a named benchmark suite (members via PART_OF)", stub=True),
    "Code": Kind("Entity", "code", "a code repository", ("source",), stub=True),
    "Model": Kind(
        "Entity",
        "model",
        "released weights or a checkpoint, or a model called through an API; a method a paper trains and compares is a Method",
        stub=True,
    ),
    "Tool": Kind("Entity", "tool", "software, a library or a service that is not a model", stub=True),
    "Method": Kind("Concept", "method", "a method or method family (variants and configurations are not nodes)", stub=True),
    "Task": Kind("Concept", "task", "a research task", stub=True),
    "Issue": Kind("Concept", "issue", "a research problem; name is a short title"),
    "Experiment": Kind("Content", "exp", "one group of experiments a paper reports (one research question)", ("figures",)),
    "Claim": Kind("Content", "claim", "one claim by the paper's authors, with the context it needs"),
    "Contribution": Kind("Content", "contrib", "one contribution the paper states for itself"),
}
FAMILIES = ("Entity", "Concept", "Content")
KINDS = {family: [k for k, s in KIND_SPECS.items() if s.family == family] for family in FAMILIES}
FAMILY = {kind: spec.family for kind, spec in KIND_SPECS.items()}  # kind → 主 Label
PREFIX = {kind: spec.prefix for kind, spec in KIND_SPECS.items()}

ENTITY = frozenset(KINDS["Entity"])
CONCEPT = frozenset(KINDS["Concept"])
CONTENT = frozenset(KINDS["Content"])
EVIDENCE = ENTITY | CONCEPT | CONTENT
NAMED = ENTITY | CONCEPT  # name 与 alias 注册为 NameKey
STUB_KINDS = frozenset(k for k, s in KIND_SPECS.items() if s.stub)

ARTIFACT = "Artifact"  # 只有主 Label，不分 kind；类型记在 ``op`` 上
ARTIFACT_TYPES = ("Leaderboard", "CompareSettings", "Verify", "Summarize", "Note", "Skill")
SYSTEM_LABELS = frozenset({"NameKey", "Material"})

# ── 节点字段 ──────────────────────────────────────────────────────────
# 写者可写的字段。``kind`` 由 Label 表达；``alias`` 存为 NameKey；``paper`` 存为 FROM 边；``source`` 登记为 Material；
# ``extra`` 存为一个 JSON 字符串。

FAMILY_FIELDS = {
    "Entity": ("name", "alias", "identities", "description", "extra", "stub"),
    "Concept": ("name", "alias", "description", "extra", "stub"),
    "Content": ("paper", "anchor", "description", "extra"),
}
FIELDS = {kind: frozenset(FAMILY_FIELDS[s.family] + s.own_fields) for kind, s in KIND_SPECS.items()}
REQUIRED_FIELDS = {
    **{kind: frozenset({"name"}) for kind in ENTITY},
    **{kind: frozenset({"name", "description"}) for kind in CONCEPT},
    **{kind: frozenset({"paper", "anchor", "description"}) for kind in CONTENT},
}
LIST_FIELDS = frozenset({"alias", "identities", "anchor", "figures", "source"})
SYSTEM_FIELDS = frozenset({"formed_by", "formed_at", "exp_key", "embedding", "embedding_key", "search_text"})
DERIVED_FIELDS = frozenset({"embedding", "embedding_key", "search_text"})  # 不受版本管理，提交后补算

NAMESPACES = {"arxiv": True, "doi": True, "s2": True, "url": False}  # 命名空间 → 是否全库唯一

# 字段的一句话说明：模板与工具说明用
FIELD_GLOSS = {
    "name": "the main name",
    "alias": "other names it goes by, a list",
    "identities": "external identities <namespace>:<value>, namespaces arxiv, doi, s2, url",
    "description": "what it is, in your own words, readable on its own",
    "extra": "other details as key: value lines (venue, authors, cited_as, caveat ...)",
    "stub": "true when only mentioned, not yet described: the name is enough; add identities if known, so others find it",
    "year": "publication year",
    "source": "the fixed sources it is read from, by id: a paper with its version like 2205.13504v2, code like Autoformer@09994619",
    "paper": "the id of the paper it comes from",
    "anchor": "the source lines it rests on, <source id>::<start>:<end>, like [2205.13504v2::120:135]",
    "figures": "tables and figures it covers, main one first, like [S4.T3, A1.T8]",
}
EDGE_GLOSS = {
    "anchor": "the source lines this edge rests on, <source id>::<start>:<end> (code: <source id>::<file>::<start>:<end>)",
    "description": "what the relation is, in a sentence",
    "extra": "other details as key: value lines",
    "role": (
        "EVALUATES: target | baseline; USES: evaluation_data | training_data | analysis_input | tooling | retrieval_corpus; "
        "a list when one edge plays two, like [training_data, evaluation_data]"
    ),
    "result": "own (the authors ran it) | cited (copied from another paper) | unstated",
    "printed_as": "the name as printed in the paper, like ECL",
}

# 外部来源 ID：论文为带版本的 arXiv 编号，代码为 <仓库>@<8 位 commit>（docs/experiments/f3/2026-10-22-f3-design.md §4）
PAPER_SOURCE = re.compile(r"\d{4}\.\d{4,5}v\d+")
CODE_SOURCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*@[0-9a-f]{8}")
SOURCE_ID = re.compile(rf"{PAPER_SOURCE.pattern}|{CODE_SOURCE.pattern}")
UNVERSIONED = re.compile(r"\d{4}\.\d{4,5}")  # 不带版本的 arXiv 编号：锚点中拒绝，提示写出版本
# 行号范围 <起始行>:<结束行>，行号从 1 起
ANCHOR = re.compile(r"(?P<start>\d+):(?P<end>\d+)")
# 来源引用 <来源、产物或材料 id>::[<章节>::]<start>:<end> 中 :: 之后的定位部分；论文的章节可省略，只作提示，
# 代码的这一段是仓库内的文件路径
LOCATOR = re.compile(r"(?:(?P<section>.+)::)?(?P<start>\d+):(?P<end>\d+)")

# ── 关系 ──────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Relationship:
    """一种关系：允许的（起点 kind 集合, 终点 kind 集合）、独有属性、必填属性、给写者看的一句话含义。"""

    ends: tuple[tuple[frozenset[str], frozenset[str]], ...]
    gloss: str
    props: tuple[str, ...] = ()
    required: frozenset[str] = frozenset()
    same_kind: bool = False  # 两端 kind 必须相同


def _k(*names: str) -> frozenset[str]:
    return frozenset(names)


EDGE_FIELDS = ("anchor", "description", "extra")  # 所有关系共有；锚点自带来源 ID

RELATIONSHIPS: dict[str, Relationship] = {
    # 实验参与
    "EVALUATES": Relationship(
        ((_k("Experiment"), _k("Method", "Model", "Code", "Tool")),),
        "a method (or model, code, tool) compared in the experiment",
        props=("role", "result"),
        required=_k("role"),
    ),
    "USES": Relationship(
        ((_k("Experiment"), ENTITY - {"Paper"}),),
        "data (or code, model, tool) the experiment uses",
        props=("role", "printed_as"),
    ),
    "ON_TASK": Relationship(((_k("Experiment"), _k("Task")),), "the task the experiment is on"),
    # 论证
    "SUPPORTS": Relationship(((_k("Experiment", "Claim"), _k("Claim")),), "evidence for a claim"),
    "OPPOSES": Relationship(((_k("Experiment", "Claim"), _k("Claim")),), "evidence against a claim"),
    # 讨论
    "ABOUT": Relationship(((CONTENT, EVIDENCE),), "what the content is about (the method proposed, a dataset, ...)"),
    # 资源结构
    "CITES": Relationship(
        ((_k("Paper"), _k("Paper")),), "the paper cites another; description says what for", required=_k("description")
    ),
    "PART_OF": Relationship(((_k("Dataset"), _k("Dataset")),), "a subset, or a member of a benchmark suite"),
    "IMPLEMENTS": Relationship(((_k("Code", "Model"), _k("Method")),), "code or weights implementing a method"),
    "FOR_TASK": Relationship(((_k("Dataset"), _k("Task")),), "a task the dataset serves"),
    # 概念结构
    "BROADER": Relationship(((CONCEPT, CONCEPT),), "a broader concept of the same kind", same_kind=True),
    # 兜底
    "RELATES_TO": Relationship(
        ((EVIDENCE, EVIDENCE),), "any other relation; description says which", required=_k("description")
    ),
}
EVALUATES_ROLES = ("target", "baseline")
EVALUATES_RESULTS = ("own", "cited", "unstated")
USES_ROLES = ("evaluation_data", "training_data", "analysis_input", "tooling", "retrieval_corpus")
ROLES = {"EVALUATES": EVALUATES_ROLES, "USES": USES_ROLES}
CHOICES = {("EVALUATES", "result"): EVALUATES_RESULTS}  # 单值的枚举属性

# 系统关系：写者不能写。FROM 由 Content 的 paper 生成；USED 由产物检入生成；NAMES、MATERIAL_OF 是系统记录
FROM = "FROM"
USED = "USED"
SYSTEM_RELS = frozenset({FROM, USED, "NAMES", "MATERIAL_OF"})
SYSTEM_REL_PROPS = frozenset({"material_ref", "formed_by", "formed_at", "embedding", "embedding_key"})
READABLE_RELS = (*RELATIONSHIPS, FROM, USED)  # 读取时可以走的关系

REQUIRED_RELS = {"Experiment": ("EVALUATES",), "Contribution": ("ABOUT",)}

# ── 约束与索引 ────────────────────────────────────────────────────────

CONSTRAINTS = [
    "CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (n:Entity) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT concept_id IF NOT EXISTS FOR (n:Concept) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT content_id IF NOT EXISTS FOR (n:Content) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT namekey_key IF NOT EXISTS FOR (k:NameKey) REQUIRE k.key IS UNIQUE",
    "CREATE CONSTRAINT experiment_key IF NOT EXISTS FOR (n:Experiment) REQUIRE n.exp_key IS UNIQUE",
    "CREATE CONSTRAINT material_id IF NOT EXISTS FOR (m:Material) REQUIRE m.id IS UNIQUE",
    "CREATE CONSTRAINT artifact_id IF NOT EXISTS FOR (n:Artifact) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT artifact_identity IF NOT EXISTS FOR (n:Artifact) REQUIRE n.key IS UNIQUE",
]
RETIRED_CONSTRAINTS = ["result_row_key", "batch_id", "material_hash", "content_key", "artifact_key"]

# 检索：每个可检索的节点带公共 Label ``Searchable``，全文与向量各一个索引覆盖证据节点与产物；
# 关系的全文与向量索引覆盖全部具名关系。``search_text`` 是派生字段（名称、别名、描述、邻居名称），提交后补算。
SEARCHABLE = "Searchable"
NODE_TEXT_INDEX = "node_texts"
EDGE_TEXT_INDEX = "edge_texts"
NODE_VECTOR_INDEX = "node_vectors"
EDGE_VECTOR_INDEX = "edge_vectors"
NAME_INDEX = "namekey_raw"
INDEXED_RELS = tuple(RELATIONSHIPS)

NODE_LABELS = frozenset(FAMILIES) | EVIDENCE | SYSTEM_LABELS | {ARTIFACT, SEARCHABLE}
REL_TYPES = frozenset(RELATIONSHIPS) | SYSTEM_RELS


def kind_of(labels: frozenset[str] | set[str]) -> str | None:
    """节点的 kind（次级 Label）；系统记录与 Artifact 返回 None。"""
    kinds = [label for label in labels if label in FAMILY]
    return kinds[0] if len(kinds) == 1 else None


def labels_of(kind: str) -> frozenset[str]:
    """一个 kind 的节点在库中的全部 Label。"""
    return frozenset({FAMILY[kind], kind, SEARCHABLE})


def relation_types(src_kind: str | None, dst_kind: str | None) -> list[str]:
    """从 ``src_kind`` 到 ``dst_kind`` 可以写的关系类型（含同 kind 的要求），按登记表的顺序。"""
    return [
        t
        for t, spec in RELATIONSHIPS.items()
        if any(src_kind in s and dst_kind in d for s, d in spec.ends) and not (spec.same_kind and src_kind != dst_kind)
    ]


def endpoints(rel_type: str) -> str:
    """关系端点的一句话写法，如 ``Experiment → Method | Model | Code | Tool``。"""
    spec = RELATIONSHIPS[rel_type]
    parts = []
    for srcs, dsts in spec.ends:
        parts.append(f"{_names(srcs)} → {_names(dsts)}")
    return "; ".join(parts)


def _names(kinds: frozenset[str]) -> str:
    for family in FAMILIES:
        if kinds == frozenset(KINDS[family]):
            return family
    if kinds == EVIDENCE:
        return "any node"
    return " | ".join(k for k in KIND_SPECS if k in kinds)
