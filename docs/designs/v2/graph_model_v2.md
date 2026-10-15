# Graph Model V2

> **状态：** 本文规定当前图模型及其工程映射；标为“待定”的项目不属于已确认实现要求。当前论文入库范围是 Paper、Method、Dataset、Benchmark、Task、Experiment、Claim、Contribution、来源与参与关系，以及选择性 `CITES`；Observation 与 Agent 提交的贡献、正反关系经增补表单写入；产物算子写入的产物为 Artifact，有版本、可共同编辑（第 8 节）。2026-10-12 修订：Artifact 由“每次调用新建、写入后不修改”改为有版本的文档；论文材料的新版本（第 5 节）；有据层修订（第 7 节）。E09 的入库代码已对齐论文表单与增补表单，尚待重新入库验证，见 [Commit 契约](./commit_contract.md)。算子契约见 [算子契约](./operators.md)，intent 与数据流见 [Workload 拆解](./intents_decompose.md)。

`V2` 设计一个面向研究 Agent 的论文知识图：保存阅读后形成的索引（轻度提炼、原文锚点与关联），通过论文引用、共享方法、资源和命题连接不同论文，让后续研究能够查找、比较和复用已有经验。

模型区分四类节点：`Entity`、`Concept`、`Content` 来自阅读论文，以主 Label 表达类别、次级 Label 表达类内类型；`Artifact` 来自使用知识，是产物算子写入的通用节点，不分类内类型，有版本、可由任何写者编辑（第 8 节）。类别与访问契约共同设计，其有效性需通过真实 workload 检验。

采用 Neo4j 的 Labeled Property Graph 模型，统一使用 `Node`、`Relationship`、`Label`、`Type`、`Property` 描述。概念依据见 [Neo4j 图模型](https://neo4j.com/docs/getting-started/appendix/graphdb-concepts/)。

```text
Graph Model
│
├── Node
│    ├── Entity     资源对象：Paper、Dataset、Benchmark、Code、Model、Tool
│    ├── Concept    定义对象：Method、Task、Issue、Proposition
│    ├── Content    来源化内容：Claim、Experiment、Contribution、Observation
│    ├── Artifact   使用产物：结果表、可比性与核查判断、概述与生成的文本（通用节点，有版本）
│    └── 系统记录   NameKey、Material、IngestBatch（支撑解析与来源，不是语义对象）
│
├── Relationship
│    ├── 视角一：四类之间的关联（4 × 4 矩阵）
│    └── 视角二：完整关系清单（Type、端点、Property）
```

## 定位：节点存什么

图与精读稿的分工不同：

| | 精读稿 | 图 |
| --- | --- | --- |
| 范围 | 单篇论文 | 跨论文 |
| 形态 | 非结构化，高度提炼的转述 | 结构化，轻度提炼的索引 |
| 用途 | 读懂一篇论文 | 从知识关联的角度找到该读的论文、实验与位置 |

图面向**关联、检索、发现与复用**；收益及其随规模的变化需要评价。原文数值、表格和段落通过锚点读取。精读稿不进入图。

因此节点不转录原文，存的是：

| 内容 | 写法 | 例子 |
| --- | --- | --- |
| 轻度提炼 | 用自己的话写到足以判断"要不要去读这里"为止，不写到足以替代阅读 | Experiment 的 `text`（目的、设计、论文的主张，4.2）；Concept 的 `definition`（3.2） |
| 阅读理解与评估 | 独立记录形成者、时间与依据 | Observation（4.5）；`note` 是对象上的备注与笔记 |
| 使用产物 | Agent 使用知识时整理的结果表、可比性与核查判断、概述与生成的文本，正文存为有版本的文档 | Artifact（第 8 节） |
| 锚点 | 在原文哪里 | `FROM` 的 locators；Experiment 的 `anchors` |
| 关联 | 和谁有关、以什么角色 | 参与边、`CITES`、概念之间的关系 |

**不存锚点能直接给出的内容：** 数值、表格、超参数与实验设置、原文段落。实验描述只保留理解该组实验所必需的设计概述，不转录条件明细；入库者的疑点与评价不混入论文陈述。

例外：

- **名称与标识**（`name`、NameKey、`identifiers`、`year`）：它们是查找的入口，必须结构化。
- **Paper 的摘要**：Paper 的 `description` 存摘要（2.2）。
- **阅读与分析形成的内容**：Observation 保存阅读者或 Agent 的理解、解释与评估，并引用其材料依据；这些内容不是原文转录。仓库检查、执行和复现的结果不入库。
- **关系的说明**（如 `CITES.description`）：写这条关联为什么存在、该去读哪里，同样只写到判断"要不要读"为止。

实验记录只到研究问题级，实际采用的参数与结果行按锚点读取。Claim 与 Contribution 同样只写轻度提炼与锚点。

## 0. 记法与状态标记

- `Entity.Paper` 表示物理上的双 Label `(:Entity:Paper)`：主 Label 是类别，次级 Label 是类内 kind。Entity、Concept、Content 的对象恰好带一个主 Label 和一个次级 Label；Artifact 与系统记录只带自己的 Label。
- Cypher 片段只展示结构，属性值为示意。
- 本文是工程方案，名词可以与设计文档不同：设计文档中的逻辑字段（如 `kind`、`aliases`、`source_refs`）在这里映射到具体的 Label、Node 或 Relationship，映射关系在对应条目中说明。
- “已定”表示当前契约；“待定”表示尚需任务实例或讨论确定，不应据此扩大实现范围。

## 1. 共同 Property

| Property | 含义 | 状态 | 说明 |
| --- | --- | --- | --- |
| `id` | 系统分配的无语义标识 | 已定 | 只定位记录，不证明对象同一性；引用即 `id`，不设修订号 |
| `kind` | 类内类型 | 已定 | 只用次级 Label 存储，不另存属性；逻辑字段由 Label 投影 |
| `family` | Entity / Concept / Content / Artifact | 已定 | 由主 Label 表达，不另存 |
| `source_refs` | 来源引用 `{entity_ref, material_ref, locator}` | 已定 | 固定来源实体、材料版本与位置；存储方式见下 |
| `note` | 对象上的备注与笔记 | 已定 | 使用提醒、消歧线索、引用线索或阅读笔记均可；不进检索面、没有独立修订。需要独立检索、引用和复用的阅读理解与评估写成 Observation。Experiment 不混入入库者的判断 |
| `embedding` 等派生属性 | 系统写入 | 已定 | 不属于模型；入库时按 E09 现状计算，见第 5 节 |

**`source_refs` 的存储。**

- 节点来源通过 `(:Content)-[:FROM {material_ref, locators: [...]}]->(:Entity:Paper)` 表达，终点即来源实体；Concept 的定义、Benchmark 的评测规则以及 Observation 的阅读依据有明确材料出处时也使用 `FROM`。Observation 等 Agent 形成的记录另记 `formed_by`，来源材料的作者不是该记录的作者。
- 关系来源存为字符串列表 `source_refs: ["<material_ref>::<章节::start:end>"]`。
- 实验参与边的来源由所属 Experiment 的 `FROM` 提供，不另存。
- `locator` 为 `<章节::start:end>`，`material_ref` 固定材料内容版本。

关系来源使用字符串的代价与约束：

- **反查困难。** "某篇论文或某份材料支持了哪些关系"无法沿边查询，只能扫描相关类型的边并匹配字符串。这主要影响维护：材料更新时查找依赖它的关系。
- **影响范围有限。** 实验参与边（`EVALUATES`、`USES` 等）的来源就是所属 Experiment 的 `FROM`，不另存；自带来源的主要是 `CITES`、论文陈述的 `SUPPORTS` / `OPPOSES`、`IMPLEMENTS`、`ADDRESSES`。原型规模下扫描代价可以接受。
- **引用完整性。** 数据库不保证字符串中的 `material_ref` 存在，由写入契约检查。
- **升级路径。** 某类关系的来源需要频繁反查时（最可能是 `IMPLEMENTS`），把它物化为关联节点，使其也能有 `FROM`（见 [Workload 拆解](./intents_decompose.md) §3.3）。

## 2. Entity：资源对象

### 2.1 次级 Label

| 次级 Label | 含义 | 状态 | 说明 |
| --- | --- | --- | --- |
| `Paper` | 书目对象 | 已定 | 只表达书目；论文中的方法、主张、实验在其他对象中。被引但尚未入库的论文建桩节点（`stub`，只有参考文献中印的标题与引用线索，[抽取原则](./extraction_principles.md) §8） |
| `Dataset` | 数据本身 | 已定 | 以资源身份供实验参与关系引用 |
| `Code` | 代码仓库 | 已定 | |
| `Model` | 权重、checkpoint 或 API 模型 | 已定 | |
| `Benchmark` | 具名的评测资源或套件 | 已定 | 有独立身份、评测目标与组成范围；定义规则存于描述并附来源锚点，见 2.5。论文把数据集称为 benchmark，不自动产生另一个节点 |
| `Tool` | 非模型的软件、库、服务 | 已定 | 暂时保留类型；当前论文表单不写 |

### 2.2 Property

| Property | 适用 | 检索面 | 状态 | 说明 |
| --- | --- | --- | --- | --- |
| `name` | 全部 | 精确键 | 已定 | Paper 与其他 Entity 均以 `name` 作为主称呼。精确键为 `(规范化 name/alias, type, kind, scope)`；`name` 留在对象上作主称呼，同时注册为一条 `NameKey` |
| `aliases` | 全部 | 精确键 | 已定 | 写入时强制作用域内唯一，冲突拒绝。不在对象上存列表，存为 `NameKey`（第 5 节）；对象视图由 NameKey 装配 aliases 供阅读 |
| `identifiers` | 全部 | 精确匹配 | 已定 | 逻辑结构 `{namespace, value}`。存为字符串列表 `"<namespace>:<value>"`，如 `"arxiv:2005.11401"`、`"url:https://github.com/zhouhaoyi/ETDataset"`；唯一性按命名空间声明，重复时的处理见 2.4 |
| `description` | 全部 | 全文 / 向量 | 已定 | Paper 的 `description` 存摘要，其他资源存内容与用途介绍。需要持久复用的任务相关阅读理解写成 Observation（4.5） |
| `year` | Paper | 否 | 已定 | 若 I1 需要按年份过滤，再提升进检索面 |
| 作者、许可、安装说明等 | 全部 | 否 | 已定 | 描述面，类内允许异构 |

### 2.3 不表达资源版本与切分

模型不表达资源版本与数据切分：数据集修订、代码 commit、模型快照不建版本节点，也不在参与边上记版本；train / dev / test 切分不建节点。名称不同的资源（如 FlashAttention 与 FlashAttention-2）是不同实体，必要时以 `DERIVED_FROM` 关联；数据集之间的组成（如 ETTh1 与 ETT）用 `PART_OF`。论文写明的版本与切分按原文锚点读取，I3 中是否可比由 Agent 读材料判断，缺失不视为一致。

### 2.4 标识的唯一性与重复

标识只用于匹配，不默认唯一。唯一性按命名空间在领域配置中声明，重复是正常输入，由算子报告，不靠改写模型或数据回避。

| 命名空间 | 唯一性 | 写入时重复 | 读取时多重命中 |
| --- | --- | --- | --- |
| `arxiv`、`doi`、`s2` | 唯一 | 拒绝写入，处理同 NameKey 冲突 | 正常不会发生；导入或核查发现的冲突隔离为 `ambiguous` |
| `url` | 非唯一：同一仓库可发布多个数据集，也可同时发布代码与模型 | 允许 | 多个命中时返回 `stage=id, status=ambiguous` 及全部命中，不静默落到下一级；只命中一个时返回 `candidates`，不单独确定身份 |

非唯一标识的多重命中缩小了候选范围，再按确定性规则继续缩小：

```text
id 级：   url = zhouhaoyi/ETDataset          → {ETT, ETTh1, ETTh2, ETTm1, ETTm2}
别名级：  mention = "ETTh1", kind = Dataset  → {ETTh1}
交集唯一  → status=resolved，match_trace 记录两级依据
仍不唯一或交集为空 → 保留 ambiguous，交 Agent 确认（入库时由 Commit 的查重退回候选）
名称命中了其他对象（如 mention = "Weather"）→ 交集为空且另记 resolution=conflicting
名称未注册 → 交集为空只是缺信息，不记冲突
```

写入模式下，非唯一标识的多重命中只作为查重候选，由外部判断新对象是其中之一还是同仓库中的另一个对象，不直接复用。同一原则适用于 alias：每条匹配规则都规定唯一命中、多重命中、无命中与数据冲突四种返回。

**工程实现（E09）。** 唯一命名空间的标识存在对象的字符串列表里，后端唯一约束作用于整个属性值、管不到列表元素，所以由 `Commit` 在 dry_run 中检查、在写入事务内复查。如果需要由后端保证，可以仿照 NameKey，为唯一命名空间单独建键节点（第 7 节）。上面的规则已在 E09 的种子图上逐条检验（`system/notebooks/02_resolve_get.ipynb`）。

### 2.5 Benchmark：定义与实际使用

Benchmark 共用 Entity 的 `name`、NameKey、`identifiers`、`description` 契约。`description` 概述评测目标、组成范围及发布者定义的评测流程和官方模式，定义材料以 `FROM` 固定材料与位置；目前不单列协议属性。

成员数据集可经 `PART_OF` 指向 Benchmark，Benchmark 经 `FOR_TASK` 指向任务。成员与任务的具体对应不能从两组边的笛卡尔积推导，必要时按描述与锚点确认。论文表单引用 Benchmark 的方式与 Dataset 相同。

论文声明在某个 Benchmark 上评测时，Experiment 经 `EVALUATED_ON` 指向它；具体数据集仍经 `USES {role: evaluation_data}` 记录，两者并存。`EVALUATED_ON` 只记录论文的声明，不能仅凭共享数据集推断。论文实际采用哪种模式、作了什么必要调整，由 Experiment 的 `text` 概述，完整设置按锚点读原文；Benchmark 节点不保存各论文用法的汇总副本。

## 3. Concept：定义对象

### 3.1 次级 Label

| 次级 Label | 含义 | 状态 | 说明 |
| --- | --- | --- | --- |
| `Method` | 方法方案及方法类别 | 已定 | 同属一个 kind，类别经 `BROADER` 表达。`level: scheme / family` 是否需要由 I1 实例确定；变体与配置不建节点或结构化标签，必要说明写在实验描述中 |
| `Task` | 研究任务 | 已定 | |
| `Issue` | 研究问题 | 已定 | Claim 经 `ABOUT` 关联；当前论文表单不写 |
| `Proposition` | 跨来源的共同命题 | 已定 | 名称待定，可能改名；Claim 经 `ABOUT` 关联，命题之间用 `SUPPORTS` / `OPPOSES`（6.2.2）；当前论文表单不写 |

### 3.2 Property

Method、Task 是术语型，Issue、Proposition 是陈述型，两者的检索字段不同。

| Property | 适用 | 检索面 | 状态 | 说明 |
| --- | --- | --- | --- | --- |
| `name` | 术语型 | 精确键 | 已定 | |
| `aliases` | 术语型 | 精确键 | 已定 | 同 Entity |
| `definition` | 术语型 | 全文 / 向量 | 已定 | 只写对象是什么，不写某篇论文如何使用它 |
| `text` | 陈述型 | 全文 / 向量 | 已定 | 措辞中立，保留范围限定 |
| `description` | Issue | 否 | 已定 | 争议所在与判断条件 |

## 4. Content：来源化内容

### 4.1 次级 Label

| 次级 Label | 含义 | 状态 | 来源责任 |
| --- | --- | --- | --- |
| `Claim` | 论文作者的主张 | 已定 | 作者，经抽取；进入论文表单 |
| `Experiment` | 论文报告的一项实验 | 已定 | 作者，经抽取 |
| `Observation` | 阅读与分析形成的理解、结论与评估 | 已定 | 形成该记录的阅读者或 Agent；与论文作者的 Claim 分开 |
| `Contribution` | 论文的贡献：论文自述或 Agent 认为的贡献 | 已定 | `stated_by: paper` 时为作者，经抽取，带原文锚点；`stated_by: agent` 时为形成该记录的 Agent |

**Claim 定义备忘（暂定）。** 在事实核查语境中，claim 是由特定主体提出、补齐必要上下文后具有确定核查对象与适用范围、因而可针对证据判断的具体陈述；是否为 claim 不取决于它已被证实。替换实体、谓词或关键条件通常得到另一条陈述，抽去这些内容得到的是句型而非待核查的具体命题。本模型的 `Claim` 仍只记录按当前抽取规则选出的论文作者主张（[抽取原则](./extraction_principles.md) §9），不代表原文所有可核查陈述；跨来源表达相同具体命题时可关联 `Proposition`，其识别与核查粒度须由任务规则确定。

Contribution 是检索论文的重要依据：经 `ABOUT` 连到它提出或改进的方法、数据集等对象，"论文提出了哪个方法"由此表达，不另设 Paper—Method 直连。论文自述的贡献随论文表单入库；Agent 认为的贡献经增补表单写入，两者以 `stated_by` 区分，读取时不得混为论文的陈述。

### 4.2 Property

| Property | 适用 | 检索面 | 状态 | 说明 |
| --- | --- | --- | --- | --- |
| `text` | 全部 | 全文 / 向量 | 已定 | Content 类统一的可独立理解描述。Experiment 写一组实验的目的、设计和论文声称的结论，不写数值；Claim、Contribution 写法见 [抽取原则](./extraction_principles.md) §4、§9 |
| `source_refs`（`FROM`） | 有材料依据的 Content | 限制条件 | 已定 | 原文位置与材料版本；Observation 的依据不表示其内容是原作者的陈述，见第 1 节 |
| `anchors`、`exp_key` | Experiment | 精确 | 已定 | `anchors`：该组实验涉及的表、图锚点列表（如 `S4.T3`、`A1.T8`），第一个为主锚点；`exp_key = <论文 id>::<主锚点>` 是自然键。全部行范围（含正文）在 `FROM.locators` |
| `content_key` | Claim、Contribution | 精确 | 已定 | 自然键，规则见 [Commit 契约](./commit_contract.md) §5 |
| `stated_by` | Contribution；`SUPPORTS` / `OPPOSES` 边 | 过滤 | 已定 | `paper / agent`：论文的陈述，还是 Agent 的判断。`paper` 必须带原文锚点，`agent` 必须带 `formed_by` |
| `formed_by` | Observation；`stated_by: agent` 的记录 | 过滤 | 已定 | 形成者，由提交的 Agent 填写 |
| `formed_at` | 同 `formed_by` | 过滤 | 已定 | 形成时间，由 `Commit` 写入时自动生成 |

### 4.3 实验粒度与结果访问

一个 Experiment 对应论文结果部分中的一个研究问题，可以覆盖多张表、图和正文段落。附录对正文实验的补全并入同一组，不按数据集、指标或预测长度拆分。自然键使用论文 id 与主锚点，分组与覆盖规则见 [抽取原则](./extraction_principles.md) §4。

实验视图（经 `Search` 或 `Traverse` 取得）给出实验、参与对象、角色及材料位置。图中不存数值或结果行；Agent 按锚点读原文，把结果行写进对应的 Leaderboard 产物（[算子契约](./operators.md) §4.2），每个数值带来源引用。同一实验内的共同参与只提供查找与配对线索，不建立行级对应。

### 4.4 实验条件与可比性

当前论文表单只记录方法及其 target / baseline 角色、数据集与任务。指标在必要时写入实验描述，不建 Metric 节点或指标参与边，也不作为 `Search` 的结构条件。

数据版本、切分、回看窗口、预测长度、评测协议、指标口径等具体条件由 Agent 读原文取得和比较。Benchmark 自身规定的评测规则随其描述与定义锚点保存；当前论文表单不结构化写入实验条件。条件相同、可比、同源等结论不能由共同实验或共享数据集推出；Agent 的可比性判断写成 CompareSettings 产物（[算子契约](./operators.md) §4.3），不写进图。

### 4.5 Observation：持久化理解、结论与评估

Observation 保存阅读者或 Agent 自己形成的内容，包括对单篇论文的理解、跨论文综合、实验比较与资源适用性评估。仓库检查、执行和复现的结果不作为 Observation 入库。`text` 可以是自由文本，不要求每条观察都表达一个布尔条件。Claim 表达论文作者的主张，Experiment 表达论文报告的实验，Observation 则标明形成者自己的解释与结论。

每条记录包括：

- **内容**：理解或结论是什么，写在 `text` 中。
- **形成信息**：`formed_by` 由提交的 Agent 填写，`formed_at` 由 `Commit` 自动生成；读材料后判断可运行不能被记为运行成功。
- **对象**：经 `ABOUT` 关联论文、方法、实验、资源或其他 Content；比较可关联多个对象，读取时保留完整对象集合，不能拆成对每个对象独立成立的判断。
- **依据**：材料位置经 `FROM` 保存；依赖的其他记录经 `ABOUT` 关联并在 `text` 中说明。`ABOUT` 只表达对象，不自动表示证据支持。

产物算子写入的 Artifact（第 8 节）是解释层的工作产物。需要长期积累的理解与结论，由提交者经 `Commit` 的增补表单显式写成 Observation（[Commit 契约](./commit_contract.md) §2.2）：可经 `ABOUT` 关联相关的 Artifact，以 Artifact 文档的行范围为依据。不要求 Observation 采用结构化的 T / F / U 判断形态。Content 的修改按层处理（[Commit 契约](./commit_contract.md) §5）：有据层的记录附锚点与理由时可以修订，旧值留在版本历史中；Observation 等解释层记录只由形成者本人修改，他人有不同意见就另写一条，两者并存。读取已有 Observation 只取得一份有依据的记录，是否适用于新任务由外部判断。

## 5. 系统记录

系统记录支撑解析与来源，不是语义对象，不进入任何类别的检索契约。

| Label | 作用 | 状态 | Property 与关系 |
| --- | --- | --- | --- |
| `NameKey` | 精确键注册表 | 已定 | `key`（规范化名称、kind、scope 拼成的单个字符串，带唯一约束）、`normalized`、`raw`、`kind`、`scope`（global 或父对象 id）、`normalizer_ref`（属性不能存 map，编码为字符串，如 `name-key-v1@unicode-15.0.0`）、`status: active / ambiguous`、注册来源与提交者（`registered_from`、`registered_by`）；`(:NameKey)-[:NAMES]->(对象)` |
| `Material` | 固定版本的材料 | 已定 | `path`、`format`、`content_hash`、`derived_from`（如原 PDF）、`created_at`、`superseded_by`（被同一论文或同一产物的新版本取代时，记新材料的 id）；论文原文 `(:Material)-[:MATERIAL_OF]->(:Entity:Paper)`，Artifact 文档 `(:Material)-[:MATERIAL_OF]->(:Artifact)`；`FROM.material_ref` 与 `USED.material_ref` 引用其 id。一个节点可以有多份材料，未被取代的那份是当前版本：论文出了新版本（如 arXiv v2）时经 `Commit` 挂上新材料，产物每次检入挂上新版本的文档；已有的引用按材料 id 固定在原来的版本上，不会错位 |
| `IngestBatch` | 论文入库批次 | 已定 | 锚点覆盖、解析与写入统计、表单和材料哈希、提交者与时间；连到 Paper，见 [Commit 契约](./commit_contract.md) §6 |

**为什么用 `NameKey`，而不是 `aliases` 列表。** 每个 alias 是一条带属性的注册记录。

- 精确键要求写入时唯一。后端唯一约束作用于整个属性值，而不作用于列表元素；`NameKey.key` 是单个字符串，唯一性可以交给数据库约束保证。
- `intents_decompose.md` §3.2 要求原字符串与 `normalizer_ref` 随注册记录保存，冲突键还要能单独标为 `ambiguous`。这些都是"每个键"的属性，放不进字符串列表。
- 对象上不另存 `aliases` 列表，避免两份副本需要同步；对象视图由 `NAMES` 装配 aliases 供 Agent 阅读。

**对算子的影响。** `Resolve` 的名称级解析查询如下；ambiguous 状态与 `normalizer_ref` 可以直接写入 match_trace。另外两个检索约束见 `intents_decompose.md` §6.2：

- **名称词面通道：** 语义阶段的名称词面通道查询 NameKey 的 `raw` 全文索引，因为对象上没有 aliases。
- **向量失效：** 向量的输入文本含由 NameKey 装配的 alias，所以注册或撤销 alias 会使该对象的派生向量失效。

向量（`embedding`、`embedding_key`）作为检索派生属性存在对象与带描述的关系上，不属于内容属性。所有自由文本（Entity 的 `description`、Concept 的 `definition`、Content 的 `text`、Artifact 的 `title` 与 `abs`、关系的 `description`）都在写入时建向量，不计成本；如何使用后续再定。

```cypher
MATCH (k:NameKey {key: $key})-[:NAMES]->(n)
```

注册 alias 时在同一事务中建 NameKey 与 `NAMES`。当前不做对象合并。

## 6. Relationship

方向约定：**Content 指向它的来源、讨论对象和参与对象；Artifact 指向它用到的节点；Entity 与 Concept 不指向 Content 或 Artifact。**

### 6.1 视角一：四类之间的关联

行为起点，列为终点。

| 起点 \ 终点 | Entity | Concept | Content | Artifact |
| --- | --- | --- | --- | --- |
| **Entity** | `PART_OF`、`DERIVED_FROM`、`CITES`、`FROM`（Benchmark 定义出处） | `IMPLEMENTS`、`FOR_TASK` | 无（方向约定） | 无 |
| **Concept** | 可选 `FROM`（定义出处） | `BROADER`、`HAS_PART`、`ADDRESSES`、`DERIVED_FROM`、`OVERLAPS_WITH`、`SUPPORTS`、`OPPOSES` | 无（方向约定） | 无 |
| **Content** | `FROM`、`ABOUT`、`USES`、`EVALUATES`、`EVALUATED_ON` | `ABOUT`、`EVALUATES`、`ON_TASK` | `ABOUT`、`SUPPORTED_BY`、`SUPPORTS`、`OPPOSES` | `ABOUT`（Observation 关联 Artifact）、`FROM`（以 Artifact 文档为依据） |
| **Artifact** | `USED` | `USED` | `USED` | `USED` |

Observation 的对象关联与依据表达见 4.5。

从矩阵可以读出两点：

- Entity 与 Concept 之间只有少量直连（实现、任务），论文形成的理解基本都经 Content 连接到对象。这与主张 A"复用的是阅读理解"一致。
- 论文与其提出的方法之间没有直连，经 Contribution 的 `ABOUT` 表达。
- Artifact 只有一种出边 `USED`，不参与任何语义关系；前三类节点不指向 Artifact，只有 Observation 在提升工作产物时关联它（4.5）。

### 6.2 视角二：完整关系清单

除另行说明外，关系可带 `description` 与 `source_refs`（字符串列表，见第 1 节）。

#### 6.2.1 实验参与与来源

| Type | 端点 | 逻辑角色 | Property | 状态 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `FROM` | Content / 有明确出处的 Concept / Benchmark → Entity；Observation → Artifact | `source_refs` | `material_ref`、`locators` | 已定 | 固定材料版本与原文位置；终点是材料所属的节点（论文或 Artifact） |
| `ABOUT` | Content → Entity / Concept / Content；Observation → Artifact | `Content.about`、对象的 `described_by` | | 已定 | 讨论关系不表示支持。Observation 经它关联理解或评估的对象；关联多个对象时读取保留完整对象集合，不能拆成对每个对象独立成立的判断 |
| `EVALUATES` | Experiment → Method、Model 等 | `Content.participants` | `role: target / baseline`（必填） | 已定 | 按角色定位被测对象；当前论文表单不写变体标签或逐项来源性质，结果依赖由 `CITES` 描述 |
| `USES` | Experiment → Entity | `Content.participants` | `role`：training_data / evaluation_data / analysis_input / tooling / retrieval_corpus | 已定 | role 缺失时进入 `diagnostics.role_missing` |
| `ON_TASK` | Experiment → Task | | | 已定 | 实验所属任务 |
| `EVALUATED_ON` | Experiment → Benchmark | | | 已定 | 论文声明采用的 Benchmark，见 2.5 |

#### 6.2.2 主张、依据与正反关系

| Type | 端点 | 逻辑角色 | Property | 状态 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `SUPPORTED_BY` | Claim → Experiment / Observation | `Content.evidence` | | 已定 | 作者主张的已存依据，不自动验证支持关系 |
| `SUPPORTS`（正）、`OPPOSES`（反） | Claim → Claim；Proposition → Proposition | `supports` / `opposes` | `description`（必填）、`stated_by`；`paper` 时带 `source_refs`，`agent` 时带 `formed_by`、`formed_at` | 已定 | 正涵盖支持、证明、暗示，反涵盖反对、证伪、不支持；限定条件等细节写在 `description`。不推导传递关系 |

Claim 与 Issue、Proposition 之间用 `ABOUT` 关联，不设专门关系。

#### 6.2.3 资源之间与资源—概念

| Type | 端点 | 逻辑角色 | Property | 状态 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `PART_OF` | Entity → Entity | `Entity.parts` | | 已定 | 资源组成关系 |
| `DERIVED_FROM` | Entity → Entity | | | 已定 | 数据、代码或模型的派生 |
| `CITES` | Paper → Paper | | `source_refs`（含正文中的引用位置）、`description`（这条引用支撑了什么）；不设引用意图枚举 | 已定 | 选择性写入：转引结果时必写，对方法、主张或实验有实际作用时可写，背景引用不写；没有 `CITES` 不等于没有引用（[抽取原则](./extraction_principles.md) §8）。论文结果之间的依赖只记在这里：`description` 写明哪些实验、哪些方法的结果引自对方，I3 据此定位该对读的实验（[Workload 拆解](./intents_decompose.md) I3） |
| `IMPLEMENTS` | Code / Model → Method | `Entity.implements` | `source_refs` | 已定 | 论文自述某个代码或模型基于该方法实现；依据指向论文原文。运行与复现结果不入库。当前论文表单不写 |
| `FOR_TASK` | Dataset / Benchmark → Task | | | 已定 | |

#### 6.2.4 概念之间

| Type | 端点 | 逻辑角色 | Property | 状态 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `BROADER` | Concept → 同 kind Concept | `Concept.broader` | | 已定 | 表达同 kind 的上下位关系，不用于连接方法变体 |
| `HAS_PART` | Method → Method | `Concept.parts` | | 已定 | 整体 → 组件 |
| `ADDRESSES` | Method → Task | `Concept.addresses` | `source_refs` | 已定 | 论文自述该方法针对的任务；依据指向论文原文。当前论文表单不写 |
| `DERIVED_FROM` | Method → Method | | | 已定 | 类别相同不推出派生关系 |
| `OVERLAPS_WITH` | Concept ↔ Concept | | | 已定 | 语义对称 |

#### 6.2.5 系统关系

| Type | 端点 | Property | 状态 | 说明 |
| --- | --- | --- | --- | --- |
| `NAMES` | NameKey → Entity / Concept | | 已定 | 第 5 节 |
| `MATERIAL_OF` | Material → Entity / Artifact | | 已定 | 第 5 节 |

#### 6.2.6 使用产物

| Type | 端点 | Property | 状态 | 说明 |
| --- | --- | --- | --- | --- |
| `USED` | Artifact → Entity / Concept / Content / Artifact | `role`（可选）；引用原文或文档行范围时带 `material_ref`、`locators` | 已定 | 当前版本用到了它：由文档中的引用得出，每次检入重写；不表示支持、讨论或同一（第 8 节） |

## 7. 实现范围与待定事项

当前论文增量的对象、字段、操作集、检查与幂等规则以 [Commit 契约](./commit_contract.md) 为准。图模型列出的其他对象和关系不表示已纳入论文表单，也不表示已完成实现或真实论文验证。

| 事项 | 当前状态 |
| --- | --- |
| 论文表单与入库 | 契约为 paper-form-v4（新增 Claim、Contribution 与 Benchmark 引用）；E09 代码已对齐，尚待重新入库验证 |
| 增补写入 | Observation、Agent 认为的贡献与正反关系经增补表单写入；E09 已实现，尚待真实数据验证 |
| Artifact | 契约见第 8 节与 [算子契约](./operators.md) §4–§5；E09 现有的是旧版（每次调用新建、写入后不修改），有版本的产物待实现 |
| 修订、撤回与合并 | 有据层附锚点与理由时可修订，删除即撤回（[Commit 契约](./commit_contract.md) §5，已实现）；论文新版本已实现；对象的合并与拆分不实现，重复与误合并只测量，作为局限报告 |
| Proposition | 保留；名称待定 |
| Concept 精炼与整理 | 日后必须增加专门的工具或算子，整理 Claim 与 Concept（含 Issue、Proposition）并建立正反关系；当前不实现 |
| 唯一命名空间标识 | 当前由 Commit 在事务内复查；后端键节点方案待维护与并发需求确定 |
| 语义候选阈值 | 当前不设；根据真实查询中的外部否定成本评估 |
| 嵌入计算 | 按 E09 现状在写入时计算；所有自由文本都建向量（第 5 节）。E09 已覆盖 Entity、Concept、Content 与关系描述，Artifact 待随其实现补上 |

## 8. Artifact：使用产物

Artifact 是第四类节点，记录 Agent 使用知识时做出来的东西：结果表、可比性与核查判断、概述与生成的文本，由产物算子（`Leaderboard`、`CompareSettings`、`Verify`、`Summarize`、`Generate`）写入。前三类来自阅读论文，Artifact 来自使用。算子的行为与校验见 [算子契约](./operators.md) §4–§5，本节只规定存储。

**每个版本不可变，产物本身可以演进。** 2026-10-12 之前取溯源模型 OPM 的定义（过程产出的不可变状态），产物写入后不修改；这使一份结果表只能由一个人维护，所以改为有版本、任何写者都可编辑的文档。不可变性落在版本上。

| 项 | 规定 |
| --- | --- |
| Label | 只有主 Label `Artifact`，不分类内类型；类别记在 `op` |
| Property | `id`（`art_<序号>`）、`op`、`op_version`（该类产物当时的工具说明与校验规则的哈希）、`key`（身份键的规范化字符串，有键的产物上唯一约束）、`title`、`abs`（当前版本的标题与摘要）、`formed_by`、`formed_at`（创建者与时间） |
| 版本 | 每次检入是一个提交：登记新版本文档的 `Material`，上一版本的 `Material` 记 `superseded_by`，重写 `USED`，更新 `title`、`abs`。版本号、编辑者与修改说明由提交链推算，不另加字段 |
| 关系 | 只有出边 `USED`（6.2.6），由当前版本文档中的引用得出：对象引用指向该对象；来源引用指向材料所属的节点并在边上带 `material_ref`、`locators`；记录引用指向所属的产物，`material_ref` 固定为引用时的版本 |
| 文档 | 每个版本一份 Markdown 文档，登记为 `Material` 并经 `MATERIAL_OF` 连到 Artifact；头部是 `title`、`abs` 与各类产物的身份字段，正文由写者编辑，格式由种子示例引导 |
| 身份 | 有身份键的产物（Leaderboard：任务、数据集、设置；CompareSettings：被比较的两项；Verify：主张）一个键只有一份，新建时撞键退回已有的那份；Summarize、Generate 没有身份键。不做合并 |
| 编辑 | 任何写者都可编辑；改动他人写的行须写理由，记入提交；`base` 不是最新版本时拒绝，不做自动合并 |
| 检索 | `title` 与 `abs` 进全文与向量检索；默认不出现在 Entity、Concept、Content 的检索结果中，需显式检索 Artifact |
| 过期 | 读取时计算：用到的节点已不在、材料文件哈希变化、所用材料已被新版本取代、所用的有据层记录在这个版本之后被修订，或用到的 Artifact 本身过期，均标为可能过期；不存状态，不修改 |
| 与 Observation | Artifact 是解释层的工作产物；需要作为一条记录留存的判断经增补表单写成 Observation，`ABOUT` 指向该 Artifact、以其当前版本文档的行范围为 `FROM` 依据（4.5） |
