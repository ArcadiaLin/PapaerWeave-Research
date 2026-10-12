# Intent 分解：共享积累的工作负载与读侧访问设计

> **目的：** 从有任务依据的研究 intent 出发，确定必须取得的信息与约束，推导访问算子的结构条件、路径与对象视图，以及产物算子的使用位置，再共同设计语义对象、检索契约和属性图映射。
>
> **在当前命题中的定位：** 核心命题是互不协调写入者的共享积累（见 `AGENTS.md` 与 [叙事草稿](../../../paper/narrative-draft.md)）。六类 intent 是这一命题的**工作负载之根**，有三种用途：生成写入者的任务、生成陌生读者的探针、决定检索面（§7.1）。intent 是工作负载，不是能力清单：“算子支持这六类 intent”本身不构成贡献，因为通用图库配上合适的查询同样可以支持。本文 §1–§6 的分解、检索面与数据流对应读侧挑战 C5（跨写入者的可发现性），也是 T1 探针的设计依据。
>
> **状态：** 本文规定六类代表性 intent 的分解与数据流；算子的定义与契约见 [算子契约](./operators.md)。实验访问只返回实验级记录、锚点和参与绑定；指标不作为结构化访问条件。E09 已实现对象解析、材料读取、两种表单的入库，以及 `Search`、`Traverse`、`ReadEvidence`（测试在 `experiments/e09/tests/operators/`）；`FetchArtifact` 与产物算子待实现。2026-10-12 按 [算子契约](./operators.md) 的修订改写 §4.1、§4.3 与 §5：产物改为有版本、可共同编辑，数据流改为“先读共同产物，再按需回到原文并写回”，并以 FIND、READ、MAINTAIN 三个过程写出（§4.3.2）。旧版见 Git `18955fe`。

面向 Agent 的研究任务，本研究设计建立在属性图之上的**语义数据访问层**。它在明确的输入输出与约束契约下，组织结构化查询、语义检索和关系遍历，返回候选对象、关联上下文及来源依据。外部 Agent 负责解释需求和开放语义判断，中间件执行显式操作与已声明约束。在共享积累中，读者往往不在写入现场，也不知道内容当初按什么目的、措辞和粒度组织，访问层要让它仍能找到别人写下的内容。

本文负责把这一定位落实为任务分解；总体动机与研究范围见 [叙事草稿](../../../paper/narrative-draft.md) 与 `AGENTS.md`（[研究顶层设计](research_design_v2.md) 是此前的框架，仅作背景）。**相对稳定的是 intent 与必要信息；对象划分、检索字段、关系模式和算子表达共同调整。**

```text
研究 intent → 必要信息与约束 → 可复用的访问需求
                                    ↕
            语义对象契约 ↔ 访问算子的条件、路径与视图；产物算子的使用位置
                                    ↓
                     图查询、索引检索与材料读取
```

## 1. 代表性 Intent 与相对稳定的信息需求

### 1.1 任务来源及采用范围

| Intent | 来源直接支持的任务 | 本文采用的范围 |
| --- | --- | --- |
| **I1 发现适合当前需求的工作与方法** | PaperFindingBench：根据包含内容和元数据条件的自然语言描述找论文集合。[S1] | 将候选论文进一步联系到方法及其前提；资源适用性判断由 Agent 完成 |
| **I2 理解方法的机制、条件与细节** | QASPER：NLP 从业者提出全文信息需求，回答者给出答案及证据。[S2] | 取得具体问题所需的知识和材料；允许长尾信息仍在原文中 |
| **I3 组织实验结果并判断比较口径** | TDMS-IE：抽取任务、数据集、指标和分数以构建 leaderboard。[S3] | 结果整理有直接依据；条件对照和可比性判断是本文扩展 |
| **I4 综合同一问题下的路线与发现** | ScholarQA-CS：多论文综合回答；ArxivDIGESTables：生成文献比较表。[S4][S5] | 组织跨论文信息与引用，不把发现原创研究问题作为数据库操作 |
| **I5 核查主张的依据与成立范围** | QASPER 的证据问答；SciFact 的支持/反驳证据及理由识别。[S2][S6] | SciFact 仅支撑任务形式，其生物医学内容不能直接证明 CS 场景覆盖度 |
| **I6 找到资源并判断能否作为实验起点** | CORE-Bench 的代码与数据执行任务；PaperBench 对代码、执行和结果匹配的不同要求。[S7][S8] | 采用资源与配置信息需求；资源发现是本文补充的前置步骤，执行与核验交给外部 Agent，其结果不入库 |

这六类覆盖候选集合、细节答案、实验对照、文献综合、证据判断和资源准备六种信息产物。它们可以组合：方法选择可以包含 I1–I3，解释异常结果可以调用 I3、I5。这里主张**有任务依据的代表性**，不主张频率代表性或对全部研究行为的完备覆盖。来源证明需求存在，不证明本文模型或混合检索优越。

### 1.2 先确定信息，再决定放在哪种节点中

| Intent | 完成任务必须取得的信息 | 必须保留的区别 |
| --- | --- | --- |
| I1 | 工作/方法候选、用途、前提、来源 | 相关不等于适用；方法不等于同名代码或模型 |
| I2 | 机制、数据与资源要求、设置、原文位置 | 对象定义与某次具体使用不同；未记录不等于不存在 |
| I3 | 被测对象、数据、指标、结果、实验条件 | 方法与实验、数值与条件一一对应到实际记录；同数据集不等于同口径 |
| I4 | 共同问题、各项回答、方法区别、具体发现和引用 | 同一问题可有不同回答；共同认识不能覆盖来源差异 |
| I5 | 待核查说法、相关主张、支持/限定/反驳材料 | 主题相关不等于同一命题；已存判断不等于本次验证 |
| I6 | 资源身份、配置、论文声明 | 论文声称公开与找到实现分开；成功运行、结果复现属于外部执行的发现，不在库中 |

这些信息可以保存为属性、独立内容单元或带依据的关系。例如，实验结果可以先作为一份实验报告中的内容，也可以在需要独立访问时拆成结果记录；**信息要求不随这种拆分自动改变，但访问路径和操作粒度会改变。**

## 2. 从信息需求到访问契约

### 2.1 算子的粒度：少量原语覆盖访问需求

“生成综述”包含开放判断，过大；“沿某条物理边走一步”暴露存储细节，过小。本稿曾为每类信息取得任务设想一个预设语义的算子（`Context`、`Experiments`、`Evidence`、`Implementations`）；2026-10-04 按功能覆盖收敛为少量中间件算子，intent 推导的领域语义落在它们的结构条件、路径约束与对象视图中（[算子契约](./operators.md)）：

| 访问需求 | 现行表达 | 返回的信息产物 | 使用位置 |
| --- | --- | --- | --- |
| 说法解析 / 需求发现 | `Resolve` / `Search` | 已解析引用及诊断 / 带匹配依据的发现候选 | I1–I6 的 lookup / discover |
| 已知对象，取得相关内容和来源 | `Traverse`（如 `ABOUT`、`FROM` 入边），或 `Search` 的 `about`、`from` 条件 | 对象、相关内容、参与关系与来源 | I1/I2/I4/I6 |
| 按被测对象及评测资源取得实验记录 | `Search(Content, kinds={Experiment}, where={evaluates, uses})` | 实验视图、参与角色、材料位置与诊断 | I3；也可供 I1/I6 使用 |
| 取得主张的已存依据和相关立场 | `Traverse` 沿 `SUPPORTED_BY` 与 `SUPPORTS` / `OPPOSES` | 有方向的主张关系、依据及来源 | I5；也可供 I4 使用 |
| 按方法取得实现资源 | `Traverse` 沿 `IMPLEMENTS` 入边 | 实现对应及其依据；当前无写入路径 | I6 |
| 读原文 | `ReadEvidence` | 固定版本材料中的行 | 全部 |

Agent 对材料的整理与判断写进产物（§4.3）：有版本、可共同编辑的 Artifact，后来的读者从这里接着做。接口是否值得独立存在，仍由复用范围和可检验契约决定，不能只因起了名字就认定形成贡献。

### 2.2 为什么关系必须进入检索面

**论证条件：** 两个图中，代码资源的全部本地属性相同，但图一记录该资源实现方法 $M$，图二记录它实现另一方法。对于“找出库中已记录为实现 $M$ 的资源”，正确结果不同。只观察资源本地属性的算法无法区分这两个输入，因而无法保证回答该查询。

这证明：**对于依赖已存关系的需求，检索契约必须取得关系信息，或取得忠实维护了该信息的派生表示。** 把关系写进检索文本也是一种派生表示，但文本相似不能代替明确的关系约束，更新时还需维持一致性。

这一论证不证明三分类唯一或最优，也不证明数据库能判断实现关系是否真实；后者属于构建质量与外部核查。

### 2.3 三种约束分别处理

| 需求成分 | 中间件行为 | 外部 Agent 行为 |
| --- | --- | --- |
| 已记录的标识或关系条件 | 精确匹配、关系模式求值、返回匹配依据 | 确定应查询哪个对象及条件 |
| “与需求相关”的开放文本 | 词面与向量召回，返回候选及匹配记录 | 判断是否真正适用，必要时改写查询 |
| 实验是否可比、证据是否支持结论 | 提供描述全集与材料，不隐式推断 | 给出带依据的判断、未知项或后续操作 |

本文使用“约束求值”表示对已声明条件的执行；不把开放科学判断统称为数据库内部的“约束推理”。不存在相关边表示当前图中没有匹配记录，不等于现实中关系不成立。

## 3. 语义对象模型：描述面包含检索面

### 3.1 描述全集、检索子集与类内统一

设对象 $o$ 的描述字段全集为 $D(o)$，所属类别为 $T$，该类检索字段契约为 $R_T$：

$$
\begin{aligned}
R_T &\subseteq \mathrm{fields}(D(o)) \\
D(o) &= \text{检索字段及其值} + \text{其余描述字段及其值}
\end{aligned}
$$

这里的字段是**逻辑字段**：既可以由节点属性提供，也可以由关系或有限子图映射得到。例如 `implements` 是资源的关系字段，不要求存成节点上的字符串属性。$R_T$ 定义字段类型、缺失状态和系统可执行的匹配方式，并不要求每项都有非空值。

- **类内：** 共享检索字段、索引构建规则和关系访问契约；$\mathrm{fields}(D(o)) \setminus R_T$ 允许随 kind 或对象异构。
- **类间：** 自身特性导致检索字段不同，或同类字段的匹配、扩展与结果组织方式不同。
- **消费边界：** Agent 可以读取整个 $D(o)$，包括检索字段。系统存取整个 $D(o)$，但只按已声明契约解释其中可计算的部分。

`metadata` 至多是剩余异构字段的存储容器，**不等于整个描述面**。某个异构字段若需要直接参与数据库筛选或排序，必须显式进入检索契约；字段提升会同时影响构建、校验和算子。

### 3.2 三类候选的字段与检索差异

所有对象共享内部引用 `ref`（即 `id`，不设修订号）、`family`、`kind` 和来源引用。内部 ID 只定位记录，不证明对象同一性。以下是各类在此基础上的检索契约；关系字段返回目标引用及关联记录，不以自由文本替代。

> **工程映射。** `family` 与 `kind` 是逻辑字段，属性图中以双 Label 存储：主 Label 为 family，次级 Label 为 kind，不另存同名属性。本文中的小写 kind 值对应首字母大写的次级 Label，例如 `Content/experiment` 存为 `(:Content:Experiment)`，`Entity/dataset` 存为 `(:Entity:Dataset)`，`Entity/benchmark` 存为 `(:Entity:Benchmark)`。算子签名中的 `type`、`kind`、`kinds` 参数含义不变，执行时翻译为 Label 条件。完整映射见 [Graph Model V2](./graph_model_v2.md)。

| 类别 | 标量或文本检索字段 | 关系检索字段（逻辑角色） | 默认检索与组织方式 |
| --- | --- | --- | --- |
| **Entity：资源对象** | `identifiers`、`name`、`aliases`、`description` | `parts`、`implements`、`described_by` | 标识匹配、名称/别名匹配与资源描述召回；按实现关系过滤；返回资源及资格依据 |
| **Concept：定义对象** | `name`、`aliases`、`definition`；陈述型为 `text` | `broader`、`parts`、`addresses`、`supports`、`opposes`、`described_by` | 术语匹配与定义/范围语义召回；按显式参数扩展已存概念关系；返回概念及扩展路径 |
| **Content：来源化内容** | `text`、`source_refs`、`stated_by`、`formed_by` | `about`、`participants`、`evaluated_on`、`supports`、`opposes`、`evidence`、`described_by` | 内容全文/语义召回与来源、参与对象限制；按记录和来源组织，保留条件与实际对应 |

这三类共享底层组件，**不共享一套无差别的检索字段和通道**。Entity 与 Concept 使用 `(normalized_name_or_alias, type, kind, scope)` 唯一键精确匹配，Content 不把标题或“实验 1”当作别名，也没有默认名称身份召回通道。所有类别已知内部 ref 时都可直接用 `Traverse` 读取，这与 alias 检索不同。

关系字段集合在类内统一；不适用的角色显式标记，未记录与未加载也要区分。例如 Paper 没有实现角色并不要求它伪造 implements 值。类内不同 kind 不通过临时拼接私有字段悄悄改变检索器。

精确键在写入时强制唯一：普通注册若与另一对象冲突，拒绝该次写入并返回键、已有对象及拟注册对象，保持原键有效；唯一检查与写入原子执行，同键同对象的重复注册为幂等操作。外部可选择显式合并对象、使用经确认的另一作用域或放弃注册。仅批量导入或事后核查发现既有冲突时，将该键隔离为 `ambiguous`，暂停精确解析并保留冲突对象。唯一命中返回已解析引用和 `origin=rule`；这是以读取时直接采用身份换取构建正确性的设计取舍。构建评价（主张 A）抽样核查 alias 精度，并注入错误 alias 测量下游退化。切分名的 scope 为父数据集，方法、资源等其他对象默认全局，kind 的例外由领域配置声明。

名称规范化采用版本化配置 `name-key-v1`：按配置记录的 Unicode 版本执行 NFC，将 White_Space 属性字符组成的连续空白折叠为一个 ASCII 空格并去除首尾空白；保留大小写、连字符及其他标点，不做 NFKC 或字符删除。因此 `BM-25` 与 `BM25`、`BERT` 与 `bert` 是不同键，可经确认分别注册为同一对象的 alias。读写使用同一配置，原字符串及 `normalizer_ref={id,revision,unicode_version}` 随注册记录和 match_trace 保存。配置升级先在新索引中重算并检查冲突，再显式切换活动版本；同一活动索引内只使用一个规范化版本，也只使用一个 Unicode 版本。

> **工程映射（E09）。** Unicode 版本取实现所用字符库的实际版本并如实记录，原型使用 Python 3.12 的 `unicodedata`，即 Unicode 15.0。属性图的属性不能存 map，`normalizer_ref` 编码为单个字符串，如 `name-key-v1@unicode-15.0.0`。

**Entity。** Paper、Dataset、Benchmark、Code、Model 共用资源模型；Paper 表达书目对象，不包办整篇论文的信息。identifiers 保存 `{namespace,value}`，匹配与唯一性规则按命名空间声明。模型不表达资源版本，论文写明的版本按原文锚点读取。Paper 的摘要可直接作为 description，其他资源使用用途与内容介绍，无需改名 abstract。作者、许可细节、安装说明等其余字段允许异构。

**Concept。** Method、Task 以定义和适用范围为核心，Issue、Proposition 是陈述型（Proposition 名称待定）。当前使用 definition 建立语义索引（原型的向量输入另含名称与 alias，见 §6.2）。组件细节与解释注释可以异构。Concept 也可以拥有严谨的标识符；SKOS 已支持概念 URI、标签、定义及语义关系 [S12]，所以不能用“概念没有 ID”证明分类。区别在于资源指称与概念定义匹配所需的规则不同。一个有 ID 的概念仍可能与另一有 ID 的概念含义重叠。

**Content。** Claim 记录论文作者的主张，Experiment 记录论文报告的实验，Contribution 记录论文自述或 Agent 认为的贡献（以 `stated_by` 区分），Observation 记录阅读者或 Agent 形成的理解、结论与评估。text 是可独立理解的内容描述，必要时由外部构建过程从表格等材料生成，并保留依据；实验的具体设置、数值和结果表按来源锚点读取。Observation 来自阅读与跨论文分析，保留形成者、时间、关联对象和依据，不承载仓库检查、执行或复现结果；其自由文本不要求全部转换为 T/F/U。相似内容不自动合并来源，也不因被称为“证据”就成为已验证事实。

Issue 与 Proposition 共用 Concept 契约：一个是待回答的问题，一个是带范围的命题；Claim 经 ABOUT 关联到它们，命题之间可有正反关系（SUPPORTS / OPPOSES）。此划分需要任务检验，不因跨论文使用就独立成为新类别。图中的第四类 Artifact 记录的是使用产物，不是阅读得到的语义对象（[Graph Model V2](./graph_model_v2.md) 第 8 节）。

Benchmark 以独立身份表达具名评测资源。自身规定的评测流程和官方模式放在 `description` 中并附定义材料锚点；论文实际使用方式由 Experiment 描述和定位，图不维护用法汇总副本。成员数据集与任务可以分别经 PART_OF、FOR_TASK 关联，但不能由此推导每个数据集与每个任务均对应。具体入库及实验使用关联仍待确定。

### 3.3 对象、关系与物理图的映射

```text
SemanticType = {
  descriptive_contract, retrieval_contract,
  identity_and_provenance_rules, graph_mapping
}
SemanticObject(ref)      ↦ 一个节点，或有稳定引用的有限子图
SemanticAssociation(ref) ↦ 一条边，或表达关联事实的有限子图
```

映射规则声明锚点、组成角色、跨对象角色及返回边界。邻居不是自动属于对象内部，同一节点或边可以被多个视图引用，不能由此重复计数或推断共同所有权。

| 逻辑含义 | 可选物理表示 | 上层访问含义 |
| --- | --- | --- |
| 一个 Entity 及其标识 | 资源节点 + 名称键节点及关系 | `Search` / `Traverse` 返回资源视图，不要求 Agent 拼标识节点 |
| 一份实验 Content | 研究问题级实验节点 + 参与关系 + 来源锚点 | 实验视图带参与绑定与材料位置；结果行按原文读取 |
| 资源实现方法的关联 | 实现边，或关联节点连接资源、方法和来源 | `Traverse` 返回关联事实与依据 |

“实现关系”若因需要来源反查而物化成节点，并不自动新增一个语义对象类别。只有任务需要独立检索、引用其具体陈述时，才考虑将该陈述另暴露为 Content，并保留它与关联事实的对应。

SourceRef 至少包含 `{entity_ref, material_ref, locator}`；material_ref 固定材料版本，书目记录不能替代原文版本。来源不可读、缺失或已撤回需显式返回。构建者提交语义判断，中间件校验引用、端点与声明过的约束。

### 3.4 关系语义

以下为逻辑角色的一种物理词汇映射，不要求 Agent 直接使用边名：

| 逻辑角色 | 示例关系模式 | 执行限制 |
| --- | --- | --- |
| Entity.implements | 资源 → IMPLEMENTS → Concept(method) | 匹配指定方法，不由同名或共同论文来源推导 |
| Entity.parts | 成员数据集 → PART_OF → 数据集或 Benchmark | 保存成员定义、父资源及来源；不能由 Benchmark 成员关系推断任务与数据的逐项对应 |
| Concept.broader / parts / addresses | 概念 → BROADER / HAS_PART / ADDRESSES → 概念 | 声明方向、深度、循环处理；不把所有边当成等价 |
| Content.about / source_refs | 内容 → ABOUT → Entity / Concept / Content；内容 → FROM → 材料实体 | 讨论关系不表示支持；来源保留版本与定位 |
| Content.participants / evaluated_on | 实验 → EVALUATES / USES → 对象；实验 → EVALUATED_ON → Benchmark | 保留方法、数据的角色与局部对应，禁止假想笛卡尔积；指标不入结构 |
| Content.evidence | 主张 → SUPPORTED_BY → 实验/观察 | 返回已存依据，不自动验证支持关系 |
| supports / opposes | Claim → SUPPORTS / OPPOSES → Claim；Proposition → SUPPORTS / OPPOSES → Proposition | 保留方向、`description` 与 `stated_by`；不推导传递关系 |
| 对象的 described_by | 内容 → ABOUT → Entity / Concept / Content | 返回有关描述与 Observation；Observation 关联多个对象时保留完整对象集合，是否足以回答问题由外部判断 |

## 4. 算子与执行表达

### 4.1 算子契约与本文的分工

算子的定义、输入输出、校验与图模式映射以 [算子契约](./operators.md) 为准；本文只说明 intent 如何使用它们。2026-10-12 修订后，算子分两部分：

- 中间件算子 `Search`、`Resolve`、`Traverse`、`ReadEvidence`、`FetchArtifact`、`Commit`；
- 产物算子 `Leaderboard`、`CompareSettings`、`Verify`、`Summarize`、`Generate`。产物是有版本、可共同编辑的 Artifact，有身份键的产物一个键只有一份。

早期设想的预设语义算子与 Agent 判断记号按下表改写：

| 原设想 | 现行表达 |
| --- | --- |
| `Get(refs)` | `Traverse(refs)`（空路径） |
| `Context(refs, roles)` | `Traverse` 的声明路径，或 `Search` 的 `about`、`from` 等结构条件 |
| `Experiments(subjects, dataset)` | `Search(Content, kinds={Experiment}, where={evaluates, uses}, expand={parts})`，诊断 `role_missing`、`expandable` 随结果返回 |
| `Evidence(claims)` | `Traverse` 沿 `SUPPORTED_BY` 出边与 `SUPPORTS` / `OPPOSES` 双向 |
| `Implementations(method)` | `Traverse` 沿 `IMPLEMENTS` 入边；当前没有写入路径 |
| `SelectSources` | 外部普通程序：从结果的 `source_refs` 中按任务规则选取，再交给 `ReadEvidence` |
| `A_map` | `Leaderboard`（结果行）、`Summarize`、`Generate` |
| `A_pred` / `Agent_pred` | `CompareSettings`（可比性）、`Verify`（主张）。同一对象的确认不写产物：读取时由 Agent 在调用循环中确认，入库时由 `Commit` 的查重退回写者；其余一次性的判断也留在调用循环中 |
| `A_policy` | Agent 自身的调用循环，在声明的动作空间内选择补检、读取或停止，不单设算子 |
| 普通程序的排序、透视与分组 | 外部普通程序，对 Leaderboard 的行执行；中间件不对产物内容排序、分组或计数 |

2026-10-08 版的 `Extract`、`Filter`、`Check`、`MatrixConstruct`（以及更早的 `Rank`）已去掉，原因见 [算子契约](./operators.md) §8。

预设语义算子不再单列，是因为它们都可以写成 `Search` 的结构条件或 `Traverse` 的路径；intent 推导出的领域语义体现在结构条件、对象视图与路径约束中。`Resolve` 的返回状态与下游路由见 [算子契约](./operators.md) §3.2，下文“名称先 Resolve”均指这一路由；语义候选由 Agent 确认。

### 4.2 混合检索内部：关系有三种不同作用

| 作用 | 例子 | 处理方式 |
| --- | --- | --- |
| 硬约束 | 已记录实现 $M$ 的代码资源 | 对候选求值，返回满足条件的 witness；相关性分数不能抵消约束失败 |
| 召回/排序线索 | $M$ 的已存直接下位方法 | 按声明方向与深度扩展，保留来源路径及扩展标记 |
| 结果装配 | 返回实验的评测数据和材料位置 | 装配语义对象视图，不仅返回命中的单节点 |

```text
contract = 取得 type 的检索契约
Q = 校验 query、where、expand 是否符合契约
C = scope 内按类型、显式属性及关系条件取得的可行对象集合

Entity:  标识精确匹配；name/aliases 匹配；description 全文/向量召回
Concept: name/aliases 匹配；definition（陈述型为 text）全文/向量召回
Content: text 全文/向量召回；source_refs 与参与关系限制

按本类契约合并候选、处理显式关系扩展并排序
重新校验所有返回项的硬约束，装配 bindings、witnesses 与来源
返回结果及截断、缺失和续取信息
```

query 可写为 `{identifier?, mention?, text?}`；纯文本简写为 text。各类只接受本契约支持的分量，不能把 Concept/Content 查询强行套进资源标识通道。query 可省略，此时按结构条件枚举，而非对空文本编码。精确标识通道只执行已注册的匹配规则，非唯一命名空间的命中只缩小候选、不单独确定身份；满足 `(normalized_name_or_alias,type,kind,scope)` 唯一约束的命中具有精确身份语义；导入或核查发现的既有非唯一键标 ambiguous，其他词面、模糊与语义命中保留候选 `value=U`。类内相同通道使用同一预处理和编码配置，缺失文本关闭对应通道。

词面与向量排行可采用 RRF [S9]；精确匹配采用独立且声明过的优先规则，不能重复计分。关系信号若参与排序，须声明含义及权重，不能将“存在路径”默认为证据强度。跨类排行不直接比较原始分数。

逻辑上先满足硬约束再取 top-$k$；实现可以索引先行或图过滤先行。近似召回再过滤可能漏掉可行候选，固定超取倍数不保证条件内 top-$k$，需报告预算与召回限制。语义检索和图遍历已有组合实现 [S13]；本文需要检验的增量在于任务契约、对象装配、组合正确性及使用成本。

### 4.3 产物算子在数据流中的位置

**将 Agent 的工作纳入伪代码，不等于将其纳入中间件内部。** 产物的内容由外部 Agent 写在文档里，中间件只校验引用、键与出处，并登记版本。访问算子与产物算子可以出现在同一程序中：外部执行环境按规则路由，中间件不调度 LLM 判断。

与 2026-10-08 版的根本区别：产物不再是一次调用留下的工作痕迹，而是**共同维护的状态**。数据流先找已有的产物、读它、在它上面接着做；只在缺失、过期或不同意时回到原文，再把结果写回。后来者因此可以少读一次原文（T2），而写回的内容带着出处与编辑记录，可以核查。

| 组 | 算子 | 身份键 | 在数据流中的作用 | 边界 |
| --- | --- | --- | --- | --- |
| 结果 | `Leaderboard` | （任务、数据集、设置） | 结果数值的共同存放处：读取时取行，缺行时读原文补录 | 只转录，带出处；不判断可比 |
| 判断 | `CompareSettings` | 被比较的两项 | 两行结果在各维度上是否一致，以及报告值之间的关系 | 不检索、不补材料、不改结果行 |
| 判断 | `Verify` | 主张 | 主张在给定证据下是否成立、在什么范围内成立 | 未找到支持不等于反驳 |
| 文本 | `Summarize` | 无 | 带引用的综合，可含比较表 | 不暗中增加判断标准 |
| 文本 | `Generate` | 无 | 回答、草稿、方案 | 出现的引用须存在 |

字段投影、引用去重、按明确条件筛选、排序、透视、数值计算与已规定的分支，由普通程序对产物的行执行。Leaderboard 的行键与度量列是被强制的结构，所以这一步不需要 Agent。最终回答可以消费已有判断，但不应改变其取值、范围或依据；不同意时编辑那份产物并写理由（算法 3）。

**记法。**

```text
x ← f(…)            赋值；f 是算子调用或普通程序
Op(doc, why)        产物算子：只校验，返回改动、错误与警告
Op(doc, why, c)     产物算子：写入新版本；c 为 confirm，改动他人的行时是 {reason}，否则为 true
a@v                 产物 a 的第 v 个版本；a#k 是当前版本中行键为 k 的行（记录引用）
⊥                   没有结果
X.T / X.F / X.U     判断类产物（CompareSettings、Verify）中结论为 T / F / U 的项
[写回]              把结果存为共同产物的步骤；只读的读者跳过，结果只留在本次回答中
```

判断取值的含义与校验见 [算子契约](./operators.md) §4.1。

#### 4.3.1 统一状态维度

每条状态记录携带 `{unit_key, field_or_condition, states, missing_in?, reason, basis_refs}`；`resolution=missing` 必填 `missing_in: request | store | material`。各维度独立，未涉及的维度省略。执行状态使用 `ok/partial/error`。

| 维度 | 取值及判定对象 |
| --- | --- |
| `access` | `matched/empty/unprocessed`：本次访问是否有命中或尚未处理；截断另记 coverage |
| `material` | `available/missing/deferred/error`：目标材料是否已成功读取、缺位置、预算待读或读取失败 |
| `value_source` | `stored/shared/rule/new`：值来自图中的记录、共同产物中已有的行或判断（记下版本 `a@v`）、确定性推导，或本次读原文新写的；派生值同时保留输入来源链 |
| `freshness` | `current/stale`：所用的记录或产物是否可能过期，`stale` 时带 `_stale` 的原因（如所引论文已有新版本、依据的记录被修订） |
| `agreement` | `single/multi`：同一格或同一主张上是否有多个值，及各值的来源（读取时的附注） |
| `resolution` | `resolved/missing/unresolved/ambiguous/conflicting`：字段/映射已确定、缺值、有原值待解析、多候选或互斥记录 |
| `value` | `T/F/U`：判断类产物对声明条件的取值，如可比性、主张是否成立 |

缺请求字段时返回待明确项；缺库内角色时报告数据不足与诊断；缺材料时按已声明规则补读或停止。实现资源的相似候选与已存实现关联分别保留，只有后者可以满足实现关系硬条件。`stale` 与 `multi` 必须随回答返回，不能当作无条件成立的值使用。

同一条件复核后，结果写成同一份产物的新版本（改动他人的判断须写理由，包括 $T$ 转 $U$），前一版本留在历史中；执行失败不写入，保留原判断并标记复核未完成。

#### 4.3.2 共同产物的读与维护

三个过程在下文六条数据流中反复出现。它们是外部执行环境中的程序，调用的都是现有算子；Agent 只在标明的地方写内容或做判断。

```text
算法 1  FIND(op, key, anchors)                  ▷ 找到某个键上已有的共同产物
输入：产物类别 op；身份键 key（无键产物为 ⊥）；与之相连的对象 anchors（如数据集、主张）
1  A ← Traverse(anchors, [{rel: USED, dir: in, kinds: {Artifact}, where: {op: op}}])
2  if key ≠ ⊥: return A 中 _key = key 的那一份（至多一份），没有则 ⊥
3  A ← A ∪ Search(Artifact, query=任务描述, where={op: op})
4  return A                                      ▷ 无键产物可能有多份，由 Agent 选用
```

```text
算法 2  READ(a)                                 ▷ 读一份共同产物，连同读取时现算的信息
1  (doc, hint) ← FetchArtifact(a)                ▷ hint：版本、编辑者、他人的改动、附注
2  stale ← Traverse([a]).nodes[a]._stale
3  return (doc, hint.notes, stale)               ▷ 调用方把 notes 中的多值格与 stale 记入 agreement、freshness
```

```text
算法 3  MAINTAIN(op, target, anchors, change, why)   ▷ 检出—编辑—检入
输入：target 为身份键，或 Agent 选定的一份已有产物，或 ⊥（新建）；change 为要做的编辑；why 为 update_abstract
1   a ← target 是产物 ? target : FIND(op, target, anchors)
2   if a ≠ ⊥: (doc, _, _) ← READ(a); doc ← Agent 把 change 写进 doc
3   else: doc ← Agent 照种子示例新写一份，头部写身份字段，再写进 change
4   r ← op(doc, why)                                    ▷ 只校验
5   if r 因身份键已有产物而拒绝: a ← r.existing; goto 2
6   if r 因 base 不是最新版本而拒绝: goto 2              ▷ 重新取出，把 change 合并进去；不做自动合并
7   while r 有错误 and 预算未尽: doc ← 按 r.errors 的行号就地修改; r ← op(doc, why)
8   if r.warnings ≠ ∅ and Agent 认为需要改: 修改 doc; goto 4     ▷ 如数字不在所引的行中
9   c ← (r.others ≠ ∅) ? {reason: Agent 写的理由} : true
10  return op(doc, why, c)                              ▷ 写入新版本 a@v+1
```

第 5、6 行的回退与第 7 行的修正都计入预算；预算耗尽时不写入，保留未完成状态。

**按判断结果路由。** router 是外部执行环境中的确定性分派逻辑，不是另一个隐含 LLM。它按已声明的结果状态与规则选择下一步；只有确实需要新的策略选择时，才回到 Agent 的调用循环。以“选出可比的结果、对未知项补材料”为例：

```text
J ← 一组通过校验的 CompareSettings（或 Verify）；校验失败进入错误出口
对 resolution=missing：按 missing_in 路由到用户补充 / 数据不足诊断 / 补读或停止
T_items, F_items, U_items ← 按结论分区
下一步只消费 T_items，并按单元键回连；保留 F 的依据
对 U：执行已声明的补材料规则后，仅对受影响的项经 MAINTAIN 编辑同一份产物；无规则时由 Agent 按预算决定补查或停止
单独保留并处理 partial/error 与未处理项
```

组合时遵守以下规则：

1. **显式依赖。** 下一步只消费通过校验的产物及其对应输入；不能丢掉对象对、条件和来源绑定。`U`、错误和未处理项不得隐式进入普通否定分支。
2. **有界执行。** 调用前声明材料访问、配对与重试预算，每次调用从任务总预算中扣除。预算耗尽保留未完成状态，不能以此代替否定答案。空处理单元直接返回空结果，不调用产物算子。
3. **无隐式副作用。** 数据读取、产物的检入与 `Commit` 都是独立可见的步骤。读取已有的判断与写入新的判断分别标记（`value_source` 为 `shared` 或 `new`）。
4. **先读后写。** 有身份键的产物，写之前先 FIND；已有且不过期的行与判断直接使用，不重新从原文生成。同一单元与条件在没有新材料时不重复判断。
5. **限制重写。** 不默认允许下推、重排、拆批、合批或替换产物算子；这些改变可能影响 Agent 所见上下文。相同输入下也不假定确定性、传递性或全序。
6. **控制扩张。** 每个写入产物的位置须说明为何需要新的整理或判断；不能用 `Generate` 承担本可对 Leaderboard 行确定执行的筛选与排序，也不能把整个 intent 藏进一次 `Generate`。

#### 4.3.3 调用位置约定

| 调用位置 | 算子与必须声明的单元、条件和范围 |
| --- | --- |
| 候选确认（I3.1、I6.1、I6.2 及写入查重） | 不写产物。读取时由 Agent 在调用循环中对候选逐个确认；入库时由 `Commit` 的查重退回候选，确认记在提交中。经确认的新写法经 `Commit` 注册 alias |
| I1 适用性判断 | 不单独写判断产物；回答写成 `Generate`，每个候选的适用与否（$T/F/U$）及依据写在其中 |
| I2 细节 | `Summarize`：一个问题项一段，段内带引用，不把不同实验设置合成一个值；某条说法是否成立另写 `Verify` |
| I3 结果行 | `Leaderboard`：先 FIND、READ；论文未转录或转录不完整时，读原文后经 MAINTAIN 补录 |
| I3 可比性与报告值关系 | `CompareSettings`：以两行（记录引用）为一项，维度由种子给出；已有且不过期则读，缺维度或过期则编辑 |
| I4 问题范围与综合 | 问题范围由 Agent 在调用循环中判断；`Summarize` 产出带来源的综合，可含按维度的比较表，路线间的分歧写明、不合并 |
| I5 证据核查 | `Verify`：每条主张一份；已有则读并核对，过期或缺失则写，不同意时在同一份中写明分歧（I5） |
| I6 资源整理 | `Generate`：资源、配置事实与未解决项，各附引用 |
| 共同补查策略 | Agent 自身循环只调用本轮提供的算子，或停止；读取范围、参数类型、目标项与预算均由执行环境校验 |

这些约定使数据流可包含可替换的 Agent 实现，同时保留独立评价边界：固定产物的内容可检查路由和数据执行；固定输入材料可评价产物的质量；端到端评价再观察二者组合。

## 5. 六类 intent 的数据流

**记号：** 下列调用均隐含固定快照 $G$、允许材料范围与预算 $B$；所有子查询遵守同一范围。$\mathrm{refs}(X)$ 提取对象引用，$\uplus$ 合并记录并保留不同路径与来源。产物中的值按版本记下来源（`value_source=shared` 时为 `a@v`）。已给出的 $m$/$a$/$b$/$d$ 是经确认的引用；下文 Resolve(read/write) 是携带目标 type、kind 与 scope 的简写。若输入只有名称，先 Resolve(read)；id/alias 唯一命中直接采用引用，语义候选由 Agent 确认。FIND、READ、MAINTAIN 见 §4.3.2。

**每条流分两半。** 先读共同产物（FIND、READ），把已有的行与判断连同 `stale`、多值附注一起取来；只在缺失、过期或不同意时回到原文，再把结果写回（MAINTAIN，标 `[写回]`）。写回不是任务提示要求的（写者是否发现并维护共同产物是评测的观测量），但它决定后来者能否少读一次原文。

每个 intent 的来源证明需求存在，以下算子序列是本稿设计，不是 benchmark 自带的标准分解。若发生补查，外部执行者使用共同控制片段：

```text
while 有未解决项且 B 尚有预算:
    action = Router(当前结果, 未解决项, 已声明转移规则)
    若没有适用规则:
        action = Agent 在允许的动作中选择补检、读取已有来源或停止（u, 当前结果, 未解决项, B）
    校验 action 的类型、参数、引用范围及剩余预算；非法则进入有界修正或错误出口
    若 action=停止: break
    delta = 外部执行者调用 action 指定的访问算子或 ReadEvidence
    更新当前结果与预算；仅对受影响的项经 MAINTAIN 编辑对应的产物
```

循环不由中间件调度；普通路由不调用模型，产物算子没有内部工具循环。停止时保留未知项、执行错误、未处理项、未访问范围与未检查配对，不能以预算耗尽代替否定答案。产物的检入先经中间件校验（[算子契约](./operators.md) §4.1），新版本才能被下一步使用；修正也计入预算。

### 5.1 共同材料选择规则与判断点审计

本节区分三类工作：**数据处理**按字段、绑定和规则执行；**语义计算**产生新的解释或判断；**编排介入**重新决定执行策略。契约明确的产物算子可以成为预先编排程序中的节点，其前后校验与路由也可以连续执行。连续执行段以需要新规划的位置为边界，不以每次模型调用为边界。“仍需判断”仅针对当前表示与规则，不表示该步骤永远无法结构化。

下文 `SelectSources` 是普通程序的候选辅助函数，不是中间件算子（[算子契约](./operators.md) §8）。`source_policy` 由任务配置给定，声明待核查项生成规则、材料优先级、稳定的同序处理规则、已读材料处理及预算。规则只消费显式字段，不判断材料是否在语义上足以回答问题。

```text
SelectSources(targets, inputs, source_policy, B)
  targets: 带 unit_key / condition_id 的待核查项
  inputs: 保留主体—记录—固定版本材料位置绑定的已有结果
  → 按绑定取得候选位置，记录 target_keys
  → 按材料版本与位置去重，保留各目标到该位置的多对多绑定
  → 按 source_policy 排序并在剩余预算内选取
  → {source_refs, bindings, states, coverage}
```

抽取 Agent 在入库时为来源化记录写入材料锚点；I3 的实验锚点覆盖表、图与正文位置，成本计入主张 A。SelectSources 只消费已有绑定，定位不足记 `material=missing`；coverage 与 AccessResult 同构。任务配置提供问题项，必要的自由需求解释显式计费；复核对象可包括已有正负判断。

| Agent 调用类 | 让渡读取时验证、提高构建正确性后的替代方式 | 不可替代的残余 |
| --- | --- | --- |
| 指称解析 | 作用域 alias 与写入唯一约束 | 新说法、冲突键的语义确认 |
| 取值规范化 | 作用域 alias 与版本化规则 | 未收录条件、作用域歧义 |
| 需求解释 | 跨任务复用的任务模板 | 模板未覆盖的自由需求 |
| 开放判断 | 复用共同产物中带条件、未过期的判断与规则 | 新证据、新适用范围、不同意已有判断和开放结论 |

前三类通过构建正确性压缩运行时调用；开放判断是保留语义计算的主体。

#### 5.1.1 配置来源、成本与公共输入

本节审计支持主张 B 的可用性、组合语义保持及规则/词表复用；主张 A 的理解经验复用另需与每次重读对照并计入构建成本。任务配置也是评价输入，须记录来源、版本及生成成本。固定知识快照上的受控比较向算子、直接 Cypher 和查询模板基线提供相同配置、词表、材料及预算；端到端比较另计配置生成与知识构建成本。不能把人工提供的绑定规则计为算子自动发现的收益。

| 配置层 | 内容与提供者 | 成本归属 |
| --- | --- | --- |
| 跨任务领域配置 | 系统设计者维护的角色目录、规范化词表与状态转移规则 | 记录构建、修订及跨任务复用范围，不假定一次编写永久适用 |
| 任务实例输入 | 用户或 benchmark 设计者明确给出的比较条件、读取策略与预算 | 所有基线共享；缺失项保留未明确，不由默认值悄悄补齐 |
| 运行时解释 | 外部 Agent 从自然语言生成问题项、条件绑定或策略选择 | 需要留痕的解释写进 `Generate` 产物，策略选择在 Agent 的调用循环中；模型调用、人工修正及失败均计入成本 |

#### 5.1.2 I3：按步骤审计实验比较

表格定义步骤契约，下文同编号伪代码给出执行顺序；所有产物的检入经中间件校验，空批次跳过，错误和未处理项独立保留；状态统一见 §4.3.1。当前逐步审计覆盖 I3/I6。

| 步骤 / 执行者 | 输入与输出 | 执行与状态约定 |
| --- | --- | --- |
| I3.1 明确条件 / 程序 | 请求 → 方法、数据集引用，任务、设置及必需比较条件 | 读取任务配置或显式解释需求；方法与数据名称经 Resolve 解析，候选由 Agent 确认。缺请求字段返回 `resolution=missing, missing_in=request`，不自行选择标准 |
| I3.2 找共同产物与实验 / 中间件（`Traverse`、`Search`、`FetchArtifact`） | （任务、数据集、设置）与方法引用 → Leaderboard 及其附注，实验、参与角色与来源锚点 | FIND 沿数据集的 `USED` 入边找到那张表，READ 取出文档、附注与 `_stale`；`Search` 按 `evaluates`、`uses` 取实验，`role_missing` 与 `expandable` 诊断分别返回；报告值关系分析另经 `Traverse` 沿 `CITES` 取得依赖线索 |
| I3.3 覆盖核对 / 程序 | Leaderboard 的“Papers covered”与实验的来源论文 → 待补录的论文 | 不在“Papers covered”中、标为不完整，或其行的出处已被新版本取代的论文进入待补录集合；没有表时全部待补录。只读这些论文，已转录的不再读 |
| I3.4 选材与读取 / 外部程序与 `ReadEvidence` | 待补录论文的实验锚点 → 已读材料与目标绑定 | 消费已有锚点；缺位置、待读和读取失败分别记 `material=missing/deferred/error`，不隐式检索新来源 |
| I3.5 补录结果行 / `Leaderboard`（MAINTAIN） | 表、图、正文和脚注 → Leaderboard 的新版本 | 每行按行键写出方法、变体、论文、预测长度、look-back，以及角色、来源（`run` / `cited`）、度量与 `source`；校验警告数字不在所引的行中时修改后再交。只读的读者不写回，新行记 `value_source=new` |
| I3.6 可比性 / `CompareSettings`（FIND、MAINTAIN）与程序 | 待比较的行对 → 逐维度判断，及可比项 | 程序按任务规则与预算形成候选行对；每对先 FIND，已有且不过期、维度齐全则直接用；否则读两行出处附近的设置说明后编辑。程序按必需条件做强三值合取；共同实验不证明条件相同 |
| I3.7 比较与输出 / 程序、`CompareSettings`、`Generate` | 可比的行、数值与附注 → 比较表、报告值关系和未决项 | 程序按度量方向排序、透视，只对可比且方向明确的行作数值比较。报告值关系的预期类别写在 `CompareSettings` 的 `relation` 中，观测由程序比较数值得出；`Generate` 组织回答，带上 `stale` 与多值格 |

图只负责定位实验与材料，结构中保存被测方法及角色、数据集和任务，不保存结果数值与比较条件。结果行在共同的 Leaderboard 中，条件判断在 CompareSettings 中，两者都是解释层的共同产物，带出处与编辑记录。程序负责去重、预算、字段校验、三值合取、排序与透视。

结果行以 Leaderboard 的行键标识（记录引用 `a#key`），保留论文、固定材料版本与行号；方法与论文写成已确认的 id，否则保留原说法与未解决状态。变体、指标、切分和协议参数以带依据的文字表达，不伪造库内 ref。

条件对齐记在 CompareSettings 的维度行中：两侧的原值、是否一致（$T/F/U$）与依据。相同说法只在上下文与作用域一致时视为一致；同名不能推出相同含义。单位换算仅在口径已明确、且任务提供适用规则时由程序执行，并记录规则版本。

必需比较条件由任务与领域配置声明。例如检索评测需说明数据版本与切分、候选集合或检索语料、指标定义及重排序设置；时间序列任务需说明任务模式、回看窗口、预测长度等相关条件。未声明或材料不足的条件不能默认一致。配置的来源、版本与构建成本独立记录。

#### 5.1.3 I6：按步骤审计实现资源取得

| 步骤 / 执行者 | 必需输入与输出绑定 | 规则及可观察分支 | 剩余语义计算 / 重新规划条件 | 消除该语义调用所需表示及代价 |
| --- | --- | --- | --- | --- |
| I6.1 明确目标 / 程序 | 方法及用途要求 → 请求 | 读取目标配置或解释用途，名称经 Resolve 解析，候选由 Agent 确认；缺请求字段 resolution=missing、missing_in=request 时返回待明确项 | 用途解释在 Agent 的调用循环中 | 任务模板；付需求填写成本 |
| I6.2 实现取得与候选发现 / 中间件及外部程序 | 方法引用、标识/别名 → 已有整理、已存实现绑定与相似候选三个集合 | 先经 FIND 读他人对该方法资源的整理（`Generate`）；`Traverse` 读取方法及 `IMPLEMENTS` 入边；只有自由描述时由 Agent 读出资源说法，再按 Entity/code 或 Entity/model Resolve，论文给出的仓库或模型链接作为 url 标识与名称一并传入，候选由 Agent 确认；开放用途用 `Search` 发现；`Traverse` 取得描述、Observation 与来源 | 资源说法的识别与新实现关系的确认需要判断；已声明搜索耗尽后，扩展来源才需策略选择 | 方法—实现—依据绑定；付关系验证与维护成本，相似命中不能替代绑定 |
| I6.3 选材与读取 / 外部程序与 `ReadEvidence` | 配置项—材料位置 → 有绑定的材料 | 已有整理中带出处且未过期的配置项不再读；其余按配置项生成 targets，选材读取，记录 `material=missing/deferred/error/available` | 已有锚点不足记 material=missing；需要新来源时按补读规则或由 Agent 决定 | 报告/记录的材料锚点；付入库提取和材料变更维护成本 |
| I6.4 配置整理与输出 / 程序、`Generate` | 配置、已有记录与整理 → 资源/配置/未解决项 | 结构化字段投影由程序完成，文本配置由 Agent 读出，写成 `Generate` 并带引用；返回未解决项与 coverage | 自然语言整理可以预编排；执行、核验或持久写入须独立工作流，本流不自动发起 | 类型化配置及字段来源；付格式适配与评价成本 |

#### 5.1.4 审计后的契约与测量项

| 契约或测量项 | 对应步骤 | 约定与检查 |
| --- | --- | --- |
| 结果单元与条件身份 | I3.5–I3.6 | 图只到实验级；行级结果写进 Leaderboard，以行键标识，属于解释层的共同产物（§6.1） |
| 共同产物的复用 | I3.2–I3.5、I5、I6.2 | 记录每次是否找到已有产物、直接使用了多少行与判断、补录了多少；对照 A0 中写者是否找到仓库里已有的表（采用率） |
| 产物身份的收敛 | I3.2、I3.5–I3.6 | 新建时撞键被退回的次数；同一（任务、数据集、设置）上出现几张表，同一方法裂成几组行（表格碎片化） |
| Resolve 三级命中 | I3.1、I6.1、I6.2 | id/alias/semantic 命中比例待实例测量，另报冲突键、按说法键去重后的语义确认次数，以及候选被外部全部否定的比例 |
| 条件到材料的绑定 | I3.3、I6.3 | 入库提供记录级锚点并计入 A，任务按这些锚点选材；锚点足以定位的比例待实例测量 |
| 访问诊断与覆盖传播 | I3.2、两条流的选材步骤 | coverage 保留输入链；role 诊断限定 EVALUATES subjects 与已选数据范围，只回传 count/refs |
| 规则与 Agent 判断的来源 | I3.5–I3.7 | 保存规则版本与判断类产物的版本（含依据与编辑记录）；分别记录构建、规则执行和本次语义成本 |
| 证据计数 | I3.7 | 按 I3 的关系口径检查：同源报告是否被计成两份证据，不可比的差异是否被当成矛盾；S 与 R0 分别统计这两类错误。报告值关系判定由 Agent 完成，两组的差别只在定位成本 |

**写路径前置约定。** 写入以批为单位，由 `Commit(delta, mode: dry_run | apply)` 执行，身份解析分两处：

- 外部 Agent 填写增量前，可用 Resolve(write) 逐个说法查重；精确命中后继续语义查重，由 Agent 确认重复对象或补 alias。
- `Commit` 的 dry_run 对整批统一解析，既看库内也看批内：同批两个对象注册同一键、同批多个新对象共用一个非唯一标识，只有在整批层面才看得到，逐个调用 Resolve 发现不了。dry_run 返回新建、更新、不变、冲突与查重候选；有冲突时 apply 拒绝整批。

经确认的新说法以独立显式写入注册 alias，原子检查规范化配置下的作用域唯一键；新冲突拒绝写入并返回冲突对象，原键保持有效；仅导入或核查发现的既有冲突隔离为 ambiguous。唯一命名空间的标识以列表存在对象上，后端约束管不到列表元素，由 `Commit` 在写入事务内复查。入库抽取同时写入实验锚点，保留材料版本与来源；alias 与锚点成本计入主张 A。由于语义阶段不设阈值，每个新对象写入时都有语义近邻需要外部排除，这也是主张 A 的固定构建成本。

E09 已实现种子增量、paper-form-v4 论文增量与 supplement-form-v1 增补增量的 `Commit`，尚待按当前抽取口径重新入库验证。论文抽取范围见 [抽取原则](./extraction_principles.md)，表单、编译规则与检查见 [Commit 契约](./commit_contract.md)。有据层的记录附锚点与理由时可以修订，删除即撤回；论文出了新版本时挂上新材料，旧材料记 `superseded_by`（[Commit 契约](./commit_contract.md) §3、§5）。Observation 等解释层记录只由形成者本人修改，他人另写一条并存。对象的合并与拆分不做，重复与误合并只测量。产物不经 Commit，经产物算子检入（同上 §7）。

这两条流可预编排到哪些位置，由上述状态及配置决定：已有处理规则的缺失、分页和错误可直接路由；没有适用规则才交给策略选择或返回未解决项。模型调用数、判断单元/条件数、重新规划次数，以及配置构建/规范化成本分别统计。本节固定设计契约，未扩展 schema 实现。

所有链条中的最终组织，若仅是投影、排序、分组或模板呈现，应由普通程序对产物的行完成；`Summarize`、`Generate` 只做自然语言组织。把多个判断合为一次调用只减少往返，是否减少新判断还需按处理单元及条件分别统计。

### I1 发现适合需求的工作与方法

> 只有少量领域标注，寻找可用于专业文献检索的适配方法，并查清资源前提。

**依据与输入输出：** [S1] 支持需求驱动的论文发现；方法输出与资源适用性是本文扩展。输入需求 $u$；输出候选工作/方法、$T/F/U$ 适用性及依据。

**必要信息与表示：** 论文为 Entity、方法定义为 Concept、贡献、主张及实验为 Content；资源前提可能在任何对象的剩余描述字段或原文中。

```text
q ← Agent 从 u 拆出方法描述、论文描述与资源条件
G ← FIND(Generate, ⊥, ∅)；对其中与 u 相关者 READ        ▷ 他人对相近需求的回答，作为起点；带 stale
M ← Search(Concept, query=q.method_query, kinds={Method})
P ← Search(Entity, query=q.paper_query, kinds={Paper})
C ← Traverse(refs(P), [{rel: FROM, dir: in, kinds: {Contribution, Claim}}])         ▷ 论文的贡献与主张
X ← Traverse(refs(M) ∪ about(C), [{rel: EVALUATES, dir: in}])                      ▷ 评测这些方法的实验
L ← Traverse(refs(M), [{rel: USED, dir: in, kinds: {Artifact}, where: {op: Leaderboard}}])；READ 各表 ▷ 这些方法出现在哪些结果表中
E ← ReadEvidence(按复核规则从 M、C、X 的 source_refs 中选取；G 中已有依据且未过期的项不再读)
J ← Agent 对每个候选判断是否满足任务与资源限制（T/F/U 及依据），不单独写产物
新增材料时：仅对受影响的候选重新判断，保留未处理及错误状态
ans ← MAINTAIN(Generate, ⊥, refs(M), 回答：候选、J 的每项判断与引用, why)     [写回]
return {ans, J, 来源, 覆盖范围, 未解决项}
```

论文的贡献与主张经 `FROM` 入边取得，其讨论对象在 Content 视图的 `about` 中，中间绑定保留在 `bindings`。未记录的资源依赖不能解释为无需资源；是否继续补查由 Agent 的调用循环决定。

**访问要求：** Entity 与 Concept 使用不同检索契约，`Traverse` 跨类取得相关内容；方法在哪些结果表中出现，沿 `USED` 入边取得；适用性由 Agent 判断，写在回答中。

### I2 理解机制、条件与细节

> 已找到方法 $M$，查明其“少样本”设置实际用了什么标注、额外语料和教师模型。

**依据与输入输出：** [S2] 支持全文信息需求与证据问答。输入 $m$、问题 $u$；输出对应实验的细节答案及未知项。

```text
M ← Traverse([m])
C ← Traverse([m], [{rel: ABOUT, dir: in}])                    ▷ 讨论 m 的 Content
X ← Traverse([m], [{rel: EVALUATES, dir: in}])                ▷ 评测 m 的实验
T ← Search(Content, query=u, where={about: m})
W ← Traverse([m], [{rel: USED, dir: in, kinds: {Artifact}, where: {op: [Summarize, Verify]}}])   ▷ 他人对 m 的整理与核查
for each w ∈ W 中与 u 相关者: (doc_w, notes_w, stale_w) ← READ(w)
targets ← 任务声明的问题项；自由文本问题先由 Agent 拆成问题项
targets ← targets 中 W 没有回答、或回答已过期的项
E ← ReadEvidence(按 targets 从 C、X、T 的 source_refs 中选取)
D ← Agent 读 E，按问题项写出 {item, value, condition, source}；不同实验设置不合成一个值
ans ← MAINTAIN(Summarize, ⊥, [m], 每个问题项一段，段内带引用；已有回答引用其版本, why)   [写回]
return {ans, 引用, 未解决项, C/X/T/W 的覆盖范围}
```

**必要信息与表示：** 定义由 Concept 提供，具体设置由 Content 及其上下文提供；不要求每种预处理步骤独立成节点。`about:m` 仅匹配已声明的 ABOUT 关系；实验另经 `EVALUATES` 入边取得。两者覆盖不足时可显式扩大为已知来源范围搜索，不能把宽范围命中自动视为关于 $M$。

**访问要求：** 按问题取得内容与上下文，检索文本不必包含最终答案；他人的整理先读，只对没回答或已过期的问题项读原文。

### I3 组织结果并判断可比性

> 比较方法 $A$、$B$ 在数据集 $D$ 上的结果，确认切分、候选集合和重排序设置是否一致。

**依据与输入输出：** [S3] 支持任务、数据、指标和分数整理，可比性为扩展。输入 $a$/$b$/$d$、问题 $u$；输出逐实验的数值与条件、比较或不可比较理由，以及报告值之间的关系口径。

```text
spec ← 读取领域配置和任务条件（parts 默认不展开）；a、b、d 先 Resolve(read)，候选由 Agent 确认；缺项记 missing_in=request  # I3.1
key ← (spec.task, d, spec.setting)                                                                    # I3.1
L ← FIND(Leaderboard, key, [d])                                                                       # I3.2
(doc, notes, stale) ← (L ≠ ⊥) ? READ(L) : (⊥, ∅, ∅)                                                    # I3.2
X ← Search(Content, kinds={Experiment}, where={evaluates: [a, b], uses: d}, expand=spec.expand)        # I3.2
role_diag, expandable ← X.diagnostics.role_missing, X.diagnostics.expandable                           # I3.2
dep ← Traverse(X 的来源论文, [{rel: CITES, dir: both}])；保留 description、source_refs 与 coverage       # I3.2
gap ← {p ∈ papers(X) : p 不在 doc 的 Papers covered 中，或标为不完整，或其行在 stale 中被标为 superseded}  # I3.3
E ← ReadEvidence(按 spec 从 gap 中实验的锚点与 dep 的 source_refs 中选取)                                # I3.4
R_new ← Agent 读 E，按行键写出缺的行（method、variant、paper、role、origin、lookback、pred_len、度量、source） # I3.5
L ← MAINTAIN(Leaderboard, key, [d], 追加 R_new，更新 Papers covered, why)                       [写回]  # I3.5
R ← doc 中 a、b 的行 ∪ R_new                                                                            # I3.5
pairs ← 程序按 spec 在 R 中形成候选行对（同一预测长度，方法分属 a、b）                                     # I3.6
for each (r1, r2) ∈ pairs:                                                                             # I3.6
    K[r1, r2] ← FIND(CompareSettings, {r1, r2}, [L])
    if K[r1, r2] = ⊥ or 已过期 or 缺 spec.conditions 中的维度:
        读 r1、r2 出处附近的设置说明（look-back、切分、归一化、训练数据、评测协议）
        K[r1, r2] ← MAINTAIN(CompareSettings, {r1, r2}, [L], 写入或补全各维度的判断与依据, why)  [写回]
ok ← {(r1, r2) : 程序对 spec.conditions 中各维度的 same 做强三值合取 = T}                                 # I3.6
T ← 程序：对 ok 中的行按度量方向排序，按方法 × 预测长度透视                                                # I3.7
vp ← notes 中“同一格有几个值”且来自不同论文的值对                                                         # I3.7
for each (v1, v2) ∈ vp:                                                                                 # I3.7
    预期 ← 一方 origin=cited 且来历指向另一方的论文 ? 同源 : K[v1, v2].relation（按上面的循环取得或写入）
    观测 ← 程序比较数值：一致 / 不一致；解释按下表
ans ← MAINTAIN(Generate, ⊥, [L], 比较表 T、可比性依据、报告值关系、stale 与未决项, why)           [写回]  # I3.7
return {ans, T, K, 报告值关系, role_diag, expandable, dep, states, coverage, 来源, 未解决及未处理项}       # I3.7
```

**必要信息与表示：** 方法为 Concept、数据集为 Entity、实验为 Content。指标不建节点；结果数值在共同的 Leaderboard 中，一张表对应（任务、数据集、设置），缺的行由读者按锚点补录。实验视图给出参与角色和对应材料，不能把实验中所有方法与数据的边直接交叉成结果行。

同一 Experiment 共现仅是配对线索，不直接给出可比结论。外部 Agent 按任务声明的条件检查数据版本与切分、评测协议、指标含义和方向等，缺字段不能视为相等，原字符串不同也不能直接判为不可比。抽取事实和判断质量独立评价。

**访问要求：** 算子保证返回满足已存对象和数据关联的实验，保留实际参与绑定，并沿数据集找到那张 Leaderboard；行级对应和条件判断由 Agent 读锚点建立，写回共同产物后，后来者不必再读同一处。

**报告值之间的关系口径。** 论文之间的转引与复述常不严谨：同一组数字在另一篇论文中可能抄错、取自不同版本或印错。口径只回答"按论文自己的陈述，两个报告值**本该**是什么关系"，实际是什么关系由读表得到；所谓不一致，就是本该相同、实际不同。不判断哪个数字是对的。

**图的责任。** 图定位涉及同一方法与数据集的实验，通过 `CITES` 及描述提供论文结果依赖线索，并给出表、图和正文的位置。四类报告值关系全部由 Agent 读原文判定；该口径也是评测时的参考框架。

取结果键相同的两个报告值（方法、变体、数据集、指标，以及任务要求的其他键，如预测长度 $T$），先定**预期类别**：

| 预期类别 | 判据（Agent 读原文） | 图提供的线索 |
| --- | --- | --- |
| 同源 | 一方声明引自另一方所在的论文；或两者出自同一论文，方法、变体与条件相同 | 两篇论文之间的 `CITES` 及其描述；同一论文中评测同一方法的实验 |
| 独立、同条件 | 两者都是实际运行，变体与条件相同 | 同一方法与数据集的实验列表 |
| 不可比 | 已知有条件不同：回看窗口、单变量与多变量、监督方式、训练数据、切分 | 无，条件在原文中 |
| 未知 | 来源或条件原文未说明 | 无 |

再由读到的数值定**观测**（一致或不一致），两者组合成解释：

| 预期 \ 观测 | 一致 | 不一致 |
| --- | --- | --- |
| 同源 | 同一份证据传了两次，只算一份 | 转引偏差：候选解释为抄错、版本不同或印刷错误，只标出，不裁决 |
| 独立、同条件 | 复现一致，可算两份证据 | 复现差异，本身是有意义的发现 |
| 不可比 | 数值相同不说明什么 | 差异不构成矛盾 |
| 未知 | 可能是转引，回答中标为推断 | 不下结论 |

- **为什么有意义。** 研究者要的是证据怎样计数：一个比较结论背后有几份独立证据，哪些只是同一次运行被转述，哪些差异可以忽略。它对应同一结果被重复计数、条件被静默合并这两类组合错误。
- **S 与 R0 的差别在哪里。** 判定本身两组都靠读原文；差别在于找到该对读的两处，以及判定能否留给后来者：Leaderboard 的多值附注直接列出值对，CompareSettings 留下判定。定位方面，S 从 `CITES` 与实验分组取得定位线索："PatchTST 的哪些实验引用了 DLinear 论文的结果"，R0 要通读全文找到转引声明。小规模材料下 R0 可以通读全文；定位收益及其随规模的变化需要实测。
- **边界。** 预期类别写在 CompareSettings 的 `relation` 中（以两行结果为一项），属于解释层的共同产物，不是论文知识；同一格的多个值由 Leaderboard 读取时的附注直接给出。需要作为一条独立记录留存时，经增补表单写成 Observation（`about` 指向该产物，以其文档为依据）。
- **不承诺。** 只有转引或重复报告让两个数字发生重叠时，不一致才能被发现，没有重叠的错误查不出来。由数值相等推出转引属于推断。版本只能作为候选解释：库只知道自己存的材料版本，转引方用的版本通常不知道。

实例（见 [I3 首个实例的问题集](../../discussions/2026-10-03-i3-first-instance-question-set.md) 的参考答案）：

- PatchTST 表 3 中的 DLinear 与 Pyraformer：同源，第 128 行写明转引自 DLinear 论文。DLinear 在 ILI 以外的数据集上数值相等，是同一份证据传了两次；Pyraformer 的 MSE 错后一格，DLinear 的 ILI 数值在库中这一版 DLinear 论文里找不到，都是转引偏差。
- PatchTST 表 8 与 DLinear 表 5 在 ETTh1、$T=720$ 上的数值：同源，转引偏差。
- DLinear 表 9 与表 2 在 ILI、$T=36$ 上的数值：同一论文内同源，转引偏差。
- PatchTST 重跑的 FEDformer 与 DLinear 表 2 中的 FEDformer：前者在六个回看窗口中取最好，后者 $L=96$，不可比，差异不构成矛盾。

定位的结构部分对应以下图查询，可由 `Traverse`（`CITES` 入边，再 `FROM` 入边、`EVALUATES` 出边）组合得到（待 E09 重新入库后验证）：

```cypher
// 引用了 $paper 结果的论文中，评测方法 $m 的实验，以及 $paper 自己评测 $m 的实验
MATCH (a:Paper)-[c:CITES]->(b:Paper {id: $paper})
MATCH (e:Experiment)-[:FROM]->(a), (e)-[:EVALUATES]->(m:Method {id: $m})
OPTIONAL MATCH (e2:Experiment)-[:FROM]->(b), (e2)-[:EVALUATES]->(m)
RETURN a.id AS citing, c.description AS dependency, e.exp_key AS citing_experiment, collect(e2.exp_key) AS cited_experiments
```

它给出"该对读哪几处"，不给出"是否同源"：后者由 Agent 读 `CITES` 描述与两处原文判定。

### I4 综合同一问题下的路线与发现

> 围绕“少标注条件下如何改善领域检索”，整理路线、条件、实验发现与分歧。

**依据与输入输出：** [S4][S5] 支持多论文综合及比较表。输入问题 $u$、可选维度；输出带来源的表格与综合，说明覆盖范围。

```text
Q ← Search(Concept, query=u, kinds={Issue})
J ← Agent 判断 Q 中哪些与 u 是同一问题范围（T/F/U 及依据）
W ← FIND(Summarize, ⊥, refs(J.T))；对其中与 u 相关者 READ        ▷ 已有的综述：看清覆盖范围与过期
C1 ← Traverse(refs(J.T), [{rel: ABOUT, dir: in, kinds: {Claim, Contribution, Observation}}])
C2 ← Search(Content, query=u, kinds={Claim, Experiment})
S ← Traverse(C1 ∪ C2 中的主张, [{rel: SUPPORTED_BY, dir: out}])
dims ← 读取任务配置中的比较维度；未明确时返回待明确项
new ← C1 ∪ C2 中不在 W 覆盖范围内、或 W 中依据已过期的记录
E ← ReadEvidence(按 dims 从 new 及其 S 的 source_refs 中选取)
R ← Agent 按 dims 写出各路线的要素与分歧，保留缺项与未检查的配对
w ← Agent 选定接着编辑的那份综述（范围一致时），否则 ⊥
ans ← MAINTAIN(Summarize, w, refs(J.T), 按维度的比较表与综合，段内带引用；写明这次补了什么, why)   [写回]
return {ans, 引用, 覆盖范围, 未解决项}
```

**必要信息与表示：** Issue 是 Concept 的可选聚合入口，来源化回答是 Content，论文是 Entity。没有已确认 Issue 时 C1 为空，但 C2 仍可发现内容。Concept 检索与 Content 检索不混为一个无类型候选池。比较维度未确定时先返回待明确项，不在组织答案时暗中增加判断标准；配对规则、每个维度的谓词及未检查配对须保留。

**访问要求：** 经 `ABOUT` 入边取得关于该问题的主张，可包含相反立场；语义分组与综合由 Agent 完成并写成 `Summarize`，不把共同问题等同共同结论；范围一致时接着编辑已有的综述，而不是另写一份。

### I5 核查主张的依据与成立范围

> “困难负样本能改善检索效果”有哪些依据、限定条件和不同发现？

**依据与输入输出：** [S2][S6] 支持证据核查形式；SciFact 的原领域不直接证明 CS 覆盖度。输入说法 $u$；输出来源化依据、不同发现及判断范围。

```text
P ← Search(Concept, query=u, kinds={Proposition})
J ← Agent 判断 P 中哪些表达同一命题及适用范围
C1 ← Traverse(refs(J.T), [{rel: ABOUT, dir: in, kinds: {Claim}}])
C2 ← Search(Content, query=u, kinds={Claim})
S ← Traverse(refs(C1 ∪ C2), [{rel: SUPPORTED_BY, dir: out}])                 ▷ 已存依据
O ← Traverse(refs(C1 ∪ C2), [{rel: [SUPPORTS, OPPOSES], dir: both}])         ▷ 一跳正反关系，保留方向
for each c ∈ C1 ∪ C2:
    V[c] ← FIND(Verify, c, [c])
    if V[c] ≠ ⊥: (doc, notes, stale) ← READ(V[c])
    if V[c] = ⊥ or stale ≠ ∅:                                                ▷ 没有核查，或所依据的记录被修订、材料被取代
        E ← ReadEvidence(按逐主张核查要求从 c、S、O 的 source_refs 中选取)
        V[c] ← MAINTAIN(Verify, c, [c], 写入或更新结论、范围与依据, why)                 [写回]
    elif Agent 读过依据后不同意已有结论:
        V[c] ← MAINTAIN(Verify, c, [c], 保留原结论与依据，加上自己的结论与依据，结论改为 U, why)   [写回]
ans ← Agent 组织依据、限定条件与不同发现，引用 V 与 O；需要留存时 MAINTAIN(Summarize, ⊥, refs(C1 ∪ C2), …)   [写回]
需要作为一条独立记录留存时：经增补表单写 Observation 或 Agent 的正反关系（引用 V[c]）
return {ans, 有方向的关联与引用, 覆盖范围, 未解决项}
```

**必要信息与表示：** 共同命题为 Concept，具体主张与实验/观察为 Content。`Traverse` 只取一跳已存主张关系与直接依据；更深扩展需对新得到的引用显式再调用并计入预算，不能无限闭包。

**访问要求：** 已存支持关系与已有的 Verify 都不等于本次验证成功；相似度不表示支持。Verify 一条主张只有一份：不同意时在同一份中写明分歧并保留原结论，不悄悄覆盖。Agent 可以改写查询搜寻相反发现，但单次未召回不证明不存在反例。

### I6 取得实现资源及其依据

论文声称公开、找到实现、成功运行与结果复现是不同发现。当前模型只保存实现对应及其来源；运行与复现由外部执行者完成，结果不入库。阅读形成的资源评估可作为 Observation 读取，但不能当作运行成功。

> 准备采用方法 $M$，寻找代码或模型及必要配置，并取得其原文依据。

**依据与输入输出：** [S7][S8] 支持资源与配置信息需求；资源发现是前置扩展，执行与核验不在本流程内。输入 $m$、用途 $u$；输出实现资源、潜在候选、配置依据与未解决项。

```text
spec ← 读取目标配置；名称先 Resolve(read)，候选由 Agent 确认；缺请求字段记 missing_in=request          # I6.1
M ← Traverse([m]); R ← Traverse([m], [{rel: IMPLEMENTS, dir: in}])     ▷ 已存实现关联；当前无写入路径，通常为空  # I6.2
G ← FIND(Generate, ⊥, [m])；对其中整理过 m 的资源者 READ                ▷ 他人整理的地址与配置，带 stale      # I6.2
mentions ← Agent 从 M、相关 Content 与材料读出资源说法（名称、链接、类型、依据）                          # I6.2
H ← 对 mentions 按说法键去重后 Resolve({identifier?: 链接, mention}, kind=Code 或 Model, mode=read)；候选由 Agent 确认；开放用途另用 Search(Entity, kinds={Code, Model}) 发现  # I6.2
C ← Traverse(refs(R) ∪ refs(H), [{rel: ABOUT, dir: in, kinds: {Observation, Contribution}}])          # I6.2
E ← ReadEvidence(按 spec 配置项选取的 source_refs；G 中带出处且未过期的项不再读)                         # I6.3
cfg ← Agent 读 E，写出发布地址与必要配置，各项带引用                                                    # I6.4
ans ← MAINTAIN(Generate, G 中范围一致的那份或 ⊥, [m], cfg、R、H、C 与未解决项, why)          [写回]   # I6.4
return {ans, states, coverage, 未解决及未处理项}                                                       # I6.4
```

**必要信息与表示：** 资源共用 Entity 契约；实现对应由 `IMPLEMENTS` 表达并带来源；论文的发布声明与配置按锚点读取。

**访问要求：** `IMPLEMENTS` 的实现关联是硬条件；`Search` 的相似候选不会自动升级为实现。CORE-Bench 的成功执行和 PaperBench 的结果匹配属于外部执行的发现，不由本流程产出或入库。已存 Observation 只作为带范围的阅读评估返回。

## 6. 映射到属性图：保持契约，允许改变存储

### 6.1 任务参数到图模式

以 `Search(Content, kinds={Experiment}, where={evaluates: [a, b], uses: d}, expand={parts: depth})` 为例（原设想写作 `Experiments(subjects, dataset)`）。固定快照中 ref 唯一确定记录；以下为实验级映射核心，尚未执行验证。先按反向 PART_OF 枚举 depth 内资源路径，得到 `$selected_ids`（严格时仅 d）与 `$extra_ids`（可展开但未选资源），保留每个目标的 witness。显式展开只沿 `PART_OF`，循环路径按节点引用截断。三支共享 subjects、快照、范围与预算。

```cypher
MATCH (e:Content:Experiment)-[tested:EVALUATES]->(m:Concept)
WHERE m.id IN $subject_ids
MATCH (e)-[used:USES]->(d:Entity)
WHERE used.role = 'evaluation_data' AND d.id IN $selected_ids
RETURN DISTINCT 'matched' AS bucket, e, m, tested, d, used
UNION ALL
MATCH (e:Content:Experiment)-[tested:EVALUATES]->(m:Concept)
WHERE m.id IN $subject_ids
MATCH (e)-[used:USES]->(d:Entity)
WHERE used.role = 'evaluation_data' AND d.id IN $extra_ids
RETURN DISTINCT 'expandable' AS bucket, e, m, tested, d, used
UNION ALL
MATCH (e:Content:Experiment)-[tested:EVALUATES]->(m:Concept)
WHERE m.id IN $subject_ids
MATCH (e)-[used:USES]->(d:Entity)
WHERE used.role IS NULL AND d.id IN $selected_ids
RETURN DISTINCT 'role_missing' AS bucket, e, m, tested, d, used
```

`matched` 装配为结果，其余分支只按实验引用去重返回 count/refs 与 coverage；role_missing 的缺失来源为 store。extra_ids 为 parts 在 depth 内的资源集合减去 selected_ids（按引用去重），默认仍枚举其额外命中用于报告；展开后 witness 标记 PART_OF。预算截断下报告已见数量。matched 直接保留命中的 m 与 tested（含 target/baseline 角色），按完整绑定去重；装配只补取任务、来源等其余已存上下文。诊断分支在输出 count/refs 时才按实验引用去重。当前论文表单不写切分关系；I3 的版本与切分可比性由 Agent 按材料判断，不能以缺失推定相等。

**结果精度停在实验级。** 实验访问只返回实验及其锚点与参与绑定。行级对应由 Agent 按锚点读原文后写进 Leaderboard（I3.5），是解释层的共同产物；实验内的共同参与不得被当作行级对应。

### 6.2 类内索引与关系访问

| 类别 | 索引配置 | 图访问配置 |
| --- | --- | --- |
| Entity | 已注册 identifier 精确索引；name/aliases；description 全文与向量 | 实现、组成、描述与观察视图 |
| Concept | name/aliases；definition（陈述型为 text）的固定编码 | 定义体系限制、指定概念关系扩展、回答/命题表达 |
| Content | text 全文与向量；来源引用定位 | 讨论对象、实验参与绑定、主张关系与依据装配 |
| Artifact | title、abs 全文与向量；默认不进入前三类的检索结果 | `USED` 谱系；读取时计算是否可能过期 |

可共享索引引擎、编码模型和融合组件，也可按类别建立索引；同类 kind 遵守同一配置。图遍历已有后端支持，全文与向量索引采用后端接口 [S10]。异构嵌套描述可序列化或拆图存储，不能假设任意嵌套 map 都是 Neo4j 属性 [S11]。

配置需记录字段映射、文本修订、编码模型与预处理版本；关系变化也可能改变候选资格或派生文本，必须使相关派生视图失效或更新。嵌入计算部署边界待定，不影响中间件不调度语义判断 Agent 的约定。

> **原型配置（E09）。**
>
> - **名称词面通道：** 查询 NameKey 原字符串（`raw`）的全文索引，再经 `NAMES` 取得对象。对象上没有 aliases 列表（[Graph Model V2](./graph_model_v2.md) 第 5 节），所以这一通道不查对象本身。
> - **文本通道：** Entity 查 description，Concept 查 definition（陈述型为 text），Content 查 text，Artifact 查 title 与 abs；关系的 description 同样在写入时建向量（[Graph Model V2](./graph_model_v2.md) 第 5 节）。E09 已覆盖 Entity、Concept、Content 与关系描述，Artifact 待随其实现补上。
> - **向量通道：** 输入文本按类别固定，为名称、由 NameKey 装配的 alias 与该类的文本字段，note 不参与；编进名称与 alias，是为了只给称呼时语义阶段仍有可比内容。写入侧不加任务说明，查询侧加。
> - **失效：** 注册或撤销 NameKey 会改变向量输入，与文本修订一样使该对象的派生向量失效。每个对象以 `embedding_key`（模型名与输入文本的哈希）判断是否需要重算。
> - **按 kind 过滤：** 向量索引按主 Label 建立，先取较大的候选池再按 kind 过滤，可能漏掉 kind 内的可行候选（§4.2），过滤方式记入 coverage。
> - **部署：** 嵌入由外部服务计算（Qwen3-Embedding-8B），向量作为检索派生属性存于对象上，不属于内容属性。

## 7. Workload、设计取舍与验证

### 7.1 六类 intent 的三种用途

#### 7.1.1 生成写入者的任务

T1 中每个写入者是一个带固定 intent 任务的 pi session 序列。不同 intent 的写入者以不同的粒度和关注点写到同一批对象上，这正是身份（C1）与分歧（C3）压力的来源；写入者数 $K$ 因此操作化为 intent 任务的多样性，而不只是 session 的数量。2026-10-12 的测试设计把写入者具体化为 3–4 个伪用户：每个伪用户有持续的身份与工作背景（对应某个 intent），论文按入库顺序随机分给他们，由他们自行维护这个库；任务提示只给工作背景，不要求维护共同产物（[讨论稿](../../discussions/2026-10-12-task-operators-and-leaderboard.md) §8，细节随评测草案修订）。

各 intent 的典型写入（候选，随评测协议确定）：

| Intent | 典型写入 | 主要落在 |
| --- | --- | --- |
| I1 发现工作与方法 | 回答与候选的适用性判断（`Generate`），必要时补录论文 | 解释层；补录时进入有据层 |
| I2 理解机制与条件 | 读取依据后的整理（`Summarize`）、对说法的核查（`Verify`），Observation | 解释层 |
| I3 组织结果并判断可比性 | 论文表单入库的 Experiment；补录共同的 Leaderboard；可比性判断（`CompareSettings`） | 有据层与解释层 |
| I4 综合路线与发现 | 综合与报告（`Summarize`、`Generate` 产物） | 解释层 |
| I5 核查主张 | Claim，核查结论（`Verify`，每条主张一份），`SUPPORTS` / `OPPOSES` | 有据层与解释层 |
| I6 取得实现资源 | Code、Model、Dataset 等资源实体及其标识 | 有据层（方法与代码的对应关系当前论文表单不写） |

无论哪种 intent，所需论文不在库中时，写入者都要先读论文、按论文表单入库。这一步是有据层写入与 C1 压力的主要来源。写入者之间的重叠由语料分配控制（重叠率档位见 [评测草案](./evaluation_draft.md) §4.2）。

#### 7.1.2 生成陌生读者的探针

探针按六类 intent 的任务形式设计，有公开任务作为依据，不是为本系统量身定制的。为了测到退化，探针要落在多写者交汇处：

- 被两个以上写入者、在不同 intent 下写过的对象；
- 经历过修订、撤回或写入者分歧的有据层记录；
- 输入已被修订的产物；
- 被几个写入者编辑过的共同产物，尤其是同一格有多个值、或他人的行被改过的地方；
- 所需内容由另一 intent 的写入者写下的问题（检验 C5）。

金标准按层定义：有据层对照原文锚点；解释层不测真值，只测分歧是否保留、读者是否看得到。

#### 7.1.3 决定检索面

§1–§6 从读需求推出对象的检索面与访问算子。由此提炼的访问负载如下（编号用 Q，以免与写入者 W1、W2… 混淆）：

| 访问负载 | 固定输入与期望输出 | 主要检查 |
| --- | --- | --- |
| Q1 对象定位 | 名称/标识/定义、类型、范围 → 候选与匹配方式 | 资源指称、概念含义、内容相关性分别标注 |
| Q2 关系约束检索 | 查询描述 + 已确认引用/关系条件 → 满足条件的候选与 witness | 硬约束正确性、条件内召回、缺失与截断 |
| Q3 上下文导航 | 对象引用 + 声明路径 → 内容、参与绑定与来源 | 多跳对应、对象去重及路径保留 |
| Q4 实验/证据组织 | 方法或主张引用 → 实验与依据 | 实验级对应、关系方向、来源与未记录情况 |
| Q5 材料读取与组合 | 来源引用 → 固定版本材料，再供外部判断 | 材料可用性、引用正确性、Agent 与系统错误分离 |
| Q6 回答与报告 | 任务 + 上述访问 + 共同产物 → 带引用的回答、表格与判断（Artifact） | 正确性、可核查性（引用能否追到记录与原文）、依据充分性、判断单元完整、可复用性 |

每个实例还必须固定数据状态、预算、参考结果及允许的信息访问。更新负载不再另选：它由带 intent 任务的写入者加上注入事件（误读后修订、撤回、材料变化、写入者分歧、分支与推回）构成，见评测草案 §2.3。

### 7.2 分类与算子如何一起调整

| 发现的问题 | 模型选择 | 算子与代价变化 |
| --- | --- | --- |
| 实验结果需要从表格解释 | 库内保存实验索引，结果按原文锚点读取 | 计入每次临时抽取与比较的成本，评价定位是否节省整体访问成本 |
| 按数值筛选 | 当前不支持库内数值过滤 | 需读取材料并在临时结果上处理，计入读取、抽取与判断成本 |
| Entity 与 Concept 接口实际无差异 | 合并公共操作，保留必要类型；或调整分类 | 不能仅靠领域名称证明三套检索契约必要 |
| 某种关联需独立引用和核查 | 为关联事实保留稳定引用，必要时暴露 Content 陈述 | 允许检索关联依据，不由物理中间节点数量决定分类 |

本稿支持三类的理由是**资源指称、定义与范围、来源化表达与上下文**分别要求不同的字段和关系处理。该理由支持一个可检验的设计选择，不宣称三类具有普遍完备性。类内统一也应接受反例：若某 kind 总需私有检索路径，需检查类别边界或契约粒度。

### 7.3 验证什么，而非只展示什么

主评测是 T1（见评测草案）。下表的设计主张降为诊断与消融，用来解释 T1 的结果，不单独构成贡献。

| 设计主张 | 对照与指标方向 |
| --- | --- |
| 类内统一、类间差异有价值 | 对比无差别字段/通道、按 kind 定制、候选三类契约；检查各类召回、错误及构建维护成本 |
| 关系参与检索确有必要和收益 | 节点文本检索、关系硬过滤、关系扩展、完整视图装配消融；检查正确性与召回，不只看答案流畅度 |
| 访问算子支持正确访问 | 同一知识、同一 Agent 和预算下，对比充分说明的 Cypher、查询模板与候选算子（即 A2 与 A3 的读侧差异）；检查结果正确性与错误类型，交互、执行与修复成本如实报告 |
| 共同产物被找到并接着维护 | 同一语料与写者安排下，对比 A3 与 A0：写者是否找到已有的表并在上面补录（采用率）、同一键上出现几份产物（碎片化）、他人的行被改动时是否附理由 |
| 产物算子提高回答与报告质量 | 同一知识与 Agent 下，对比有无产物算子的回答与报告：正确性、可核查性、依据充分性与可复用性；调用与 token 成本作为代价报告，不主张成本优势 |
| 图映射保持信息语义 | 用独立参考绑定检查结果、来源与对应；不能只验证 schema 合法 |
| 混合检索和文本选择有效 | 词面、向量、融合消融；摘要直用与规范化文本比较，计入生成成本 |
| 连续组合减少编排与重复判断 | 按 §5.1 审计固定实例，分别记录重新规划次数、模型调用/往返、处理单元与条件数、材料量和成本；同时检查正确性、覆盖及构建维护成本 |
| 外部判断与执行能够分别评价 | 固定算子输入评价中间件，再独立评价 Agent 的意图转换与判断，最后评价端到端 |
| 累积知识值得维护 | 计入初始构建、增量更新、索引/视图维护及复用总成本（T2） |
| 跨写入者可发现（C5） | 探针所需内容由另一 intent 的写入者写下时，对比各组的找到率与正确率；检查措辞与粒度不一致时的召回 |

已有向量检索与图遍历组合 [S13]，所以“组合技术”不是充分的新颖性论证。读侧按“经典机制的选择与改造”表述：前身是 dataspaces 的按需整合、数据库上的关键词搜索与混合检索；改变在于读者是受上下文所限的 Agent，内容来自互不协调的写入者，分歧与过时须随结果返回。不预设比 Cypher 表达力更强，也不要求完整新代数。

### 7.4 当前验证重点

E09 是 T1 的实验准备。当前优先：

- 按现行契约复核已实现的访问算子；实现 `FetchArtifact`、产物算子与产物的版本（[算子契约](./operators.md) §9）；
- 有据层修订已实现；`_stale` 的“输入已修订”原因与产物的 `superseded` 待实现；
- I3 实例（DLinear 与 PatchTST）保留为先导：它的三组设置 S / S-Cypher / R0 是 A3 / A2 / A0 的原型；
- 按 §7.1 确定写入者任务与探针，与评测草案的待定项一并商定。

资源定位、概念范围查询等实例仍需固定输入、所需信息和独立参考输出。

## 来源与可追溯位置

- **[S1] AstaBench**：官方 Literature Understanding Benchmarks 中 PaperFindingBench 的任务定义。[任务说明](https://allenai.org/asta/bench)。
- **[S2] QASPER**：*A Dataset of Information-Seeking Questions and Answers Anchored in Research Papers*，§2–3、Table 1。[论文](https://aclanthology.org/2021.naacl-main.365/)。
- **[S3] TDMS-IE**：*Identification of Tasks, Datasets, Evaluation Metrics, and Numeric Scores for Scientific Leaderboards Construction*。[论文](https://aclanthology.org/P19-1513/)。
- **[S4] ScholarQABench / ScholarQA-CS**：专家研究问题、rubric 和引用评价。[作者介绍](https://allenai.org/blog/openscilm)，[数据与评价代码](https://github.com/AkariAsai/ScholarQABench)。
- **[S5] ArxivDIGESTables**：*Synthesizing Scientific Literature into Tables using Language Models*。[论文](https://aclanthology.org/2024.emnlp-main.538/)。
- **[S6] SciFact**：*Fact or Fiction: Verifying Scientific Claims*。[论文](https://aclanthology.org/2020.emnlp-main.609/)。用于核查任务形式，领域内容与本项目有区别。
- **[S7] CORE-Bench**：使用代码和数据进行计算复现并回答输出问题。[官方说明](https://github.com/siegelz/core-bench)。
- **[S8] PaperBench**：*Evaluating AI's Ability to Replicate AI Research*，§2.2–2.4 的复现阶段与不同要求类型。[论文](https://cdn.openai.com/papers/22265bac-3191-44e5-b057-7aaacd8e90cd/paperbench.pdf)。
- **[S9] RRF**：*Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods*。[论文](https://doi.org/10.1145/1571941.1572114)。
- **[S10] 索引接口**：[Neo4j 全文索引](https://neo4j.com/docs/cypher-manual/current/indexes/semantic-indexes/full-text-indexes/)、[向量索引](https://neo4j.com/docs/cypher-manual/current/indexes/semantic-indexes/vector-indexes/)。
- **[S11] 属性类型限制**：[Neo4j Property, structural, and constructed values](https://neo4j.com/docs/cypher-manual/current/values-and-types/property-structural-constructed/)。

- **[S12] 概念标识与关系**：[W3C SKOS Reference](https://www.w3.org/TR/skos-reference/)，§3、§5、§7–8。用于说明概念可有 URI、标签、定义与关系，不作为本三分类的直接依据。
- **[S13] 图与检索组合的已有实现**：[Neo4j GraphRAG User Guide](https://neo4j.com/docs/neo4j-graphrag-python/current/user_guide_rag.html)，VectorCypherRetriever / HybridCypherRetriever。用于界定已有能力，不证明本文接口的效果。

[S1]: https://allenai.org/asta/bench
[S2]: https://aclanthology.org/2021.naacl-main.365/
[S3]: https://aclanthology.org/P19-1513/
[S4]: https://allenai.org/blog/openscilm
[S5]: https://aclanthology.org/2024.emnlp-main.538/
[S6]: https://aclanthology.org/2020.emnlp-main.609/
[S7]: https://github.com/siegelz/core-bench
[S8]: https://cdn.openai.com/papers/22265bac-3191-44e5-b057-7aaacd8e90cd/paperbench.pdf
[S9]: https://doi.org/10.1145/1571941.1572114
[S10]: https://neo4j.com/docs/cypher-manual/current/indexes/semantic-indexes/vector-indexes/
[S11]: https://neo4j.com/docs/cypher-manual/current/values-and-types/property-structural-constructed/

[S12]: https://www.w3.org/TR/skos-reference/
[S13]: https://neo4j.com/docs/neo4j-graphrag-python/current/user_guide_rag.html
