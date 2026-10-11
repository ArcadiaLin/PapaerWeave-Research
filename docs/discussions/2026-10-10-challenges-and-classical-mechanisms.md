# 挑战与经典机制：设计对 C1–C4 的回应、分歧的分层处理与现有工程的复用

> **记录日期：** 2026-10-10。**状态：** 讨论记录。§4 的分层、§5 的起点、§6 的工程取舍已与用户商定；其余为倾向或待定。
>
> 承接 2026-10-09 商定的核心命题（互不协调写入者的共享积累，见 `AGENTS.md`）与 [叙事草稿](../../paper/narrative-draft.md) 中的 C1–C4。本文回答：现有设计能否回应这些挑战；设计是否落在传统多写者数据库的已有机制上，是否需要引证；分歧与权威怎样处理；库从哪里开始；现有工程怎样复用到新故事上。
>
> 本文列出的文献凭记忆整理，出处与年份较有把握，但尚未核对是否已在 `references/refs.bib` 中，也未下载（见 §8）。

## 1. 结论

- **能否解决：** 只能部分解决。C3（分歧与变化）缺口最大，而它恰恰与多写者关系最密切。§4 给出分层处理，补上这个缺口所需的工程很小（§6）。
- **是否落在已有机制上：** 是，几乎每项机制都有直接前身。
- **是否引证：** 必须引证。前身由我们主动认领，再说明 Agent 写入者场景要求哪些改变；否则论文会被看成实体解析、PROV 与数据版本管理的拼接。
- **贡献措辞随之收紧：** 不主张新的并发、provenance 或版本理论。主张的是：找出 Agent 写入者的共享积累需要哪些经典机制，说明它们在哪里必须改（§3），并用实验证明它们起作用（T1 及消融）。
- **库的职责是可问责性，不是权威性**（§4）。
- **现有原型就是系统，新故事不另起工程。** E09 定位为 T1 的实验准备（§6）。

## 2. 逐项对照

| 挑战 | 经典前身 | 当前设计 | 状态 |
|---|---|---|---|
| **C1 独立写入下的身份** | 实体解析与记录链接（Fellegi–Sunter 1969）；人在环中或众包的实体解析（CrowdER，VLDB 2012）；自然键与唯一约束；dataspaces 的按需整合（Franklin、Halevy、Maier 2005）；Wikidata 的 QID 合并与重定向 | `NameKey` 精确键与命名空间标识（[图模型](../designs/v2/graph_model_v2.md) §2.4）；dry_run 给出语义候选，Agent `confirm` 同一与否；`ambiguous` 状态 | **能防不能修。** 对象合并与拆分不实现（[Commit 契约](../designs/v2/commit_contract.md) §8），重复与误合并只测量，作为局限报告。查重在提交锁之外（只读了代码，未实测；见 [评测草案](../designs/v2/evaluation_draft.md) §10），写入者轮流执行可绕开 |
| **C2 自描述的贡献** | provenance：why/where（Buneman、Khanna、Tan 2001）、provenance semirings（Green 等 2007）；W3C PROV 的 Entity / Activity / Agent；引用完整性；科学领域的 nanopublication（Groth 等 2010）与 micropublication（Clark 等 2014） | 契约校验引用与输入；`USED` 边；`Material` 带 `content_hash`；`formed_by`、`params`、`session`；幂等的 `artifact_key`（[算子契约](../designs/v2/operators.md)、Commit 契约 §7） | 设计基本完整；Agent 算子代码已在，完成度与测试尚未按现行契约复核。记录的是声明的输入，不是完整推理轨迹，也不证明判断为真 |
| **C3 分歧与变化** | 过时：物化视图失效与维护（Gupta & Mumick 1995）、真值维护系统 TMS / ATMS（Doyle 1979；de Kleer 1986）。并存：Trio / ULDB 的备选值与 lineage（Widom 2005；VLDB 2006）、CRDT 多值寄存器（Shapiro 等 2011）、Dynamo 的兄弟版本（2007）、Wikidata 的多值 statement、rank 与 reference。修订：双时态数据库 | 读取时按依赖计算 `_stale`（算子契约 §5.6）；`SUPPORTS` / `OPPOSES` 边 | **过时有设计；修订按 §4 分层补上。** 现行 Commit 契约 §5 规定内容变化即冲突、整批拒绝，需按 §6 放宽 |
| **C4 隔离地工作，共享地交付** | 工程数据库的 check-out / check-in 与长事务（Katz 1990）；快照隔离（Berenson 等 1995）；乐观并发控制的提交前校验（Kung & Robinson 1981）；数据版本管理（DataHub 2015、Decibel 2016、OrpheusDB 2017；仓库已有 `2026-Git4Data`、`2013-GraphSnapshot`） | Fork 闭合检查；单父合并提交；逐项核对改前值，冲突交 Agent 决议；`merged_from`（[项目视图](../designs/v2/project_views.md) §5–§6；[版本化知识管理备忘](./2026-10-05-versioned-knowledge-management.md)） | 有设计，未实现 |

C1 与 C3 的缺口性质相同：库能在写入时拦截或提示，但写入之后无法纠正。C1 缺"合并与拆分"（经典做法是重定向与墓碑），这一项不做；C3 缺"修订与撤回"，按 §4 处理。

## 3. Agent 写入者要求的改变

经典机制默认写入者要么是程序（错误是语法性的，可校验），要么是人（慢、少、可信）。Agent 写入者都不符合。以下五点是贡献的落点：

1. **裁决在写入时交还写入者。** 经典实体解析要么全自动，要么事后众包。这里由库在写入时提出候选，写入者当场判断，判断和理由一起留档。约束不只是拒绝写入，还返回修复义务（dry_run → 阻塞项 → `confirm`），而接收方是一个能理解并执行修复的写入者。
2. **错误是语义性的，而且读起来通顺。** 结构校验拦不住误读。因此 provenance 与分歧并存比保证正确更重要，这也是我们不走 truth discovery 路线的理由（§4）。
3. **派生内容重算昂贵且不确定。** 物化视图可以增量维护，因为重算确定、便宜；Agent 写的比较表与报告重算一次要再调 LLM，结果也不一定相同。所以只能标记可能过时，不能自动维护。这是与增量视图维护（IVM）的清晰分界。
4. **读者不会主动查 provenance。** 经典系统把 lineage 当作单独的查询；Agent 读者上下文有限，也不会想到去问。分歧与过时必须随查询结果一起返回（`_stale` 即如此）。
5. **接口就是契约。** 通用 Agent 只看得到 MCP 工具描述，机制能否起作用取决于 Agent 是否会用、是否绕开。经典 DBMS 没有这个问题，所以要用显示偏好或绕开率来测（评测草案 §8.2）。

## 4. 分歧与权威：有据层与解释层

### 4.1 可问责性，而不是权威性

- **权威（authority）：** 谁是对的，哪个值是真的。这是 truth discovery 与信誉系统的问题，需要库来裁决。
- **可问责（accountability）：** 每条内容是谁写的、依据什么、能否回到源头核对、有没有人反对、是否已经过时。这是数据管理问题，即 C2、C3。

库只负责后者。它不判断谁对，也不按使用或引证次数排名。权威不在库里，而在库所指向的外部参照中：固定版本的论文原文与外部标识。

### 4.2 按有无外部参照分层

分界不按 Entity / Concept / Content 与 Artifact 划，而按"有没有可核对的外部参照"划：

| 层 | 范围 | 对错的含义 | 写入者有分歧时 |
|---|---|---|---|
| **有据层** | Entity 的身份（arXiv ID、仓库 URL 等）；`stated_by: paper` 的 Experiment、Claim、Contribution | 是否忠实于原文：可检验的事实，不是科学真理 | 分歧是暂时的错误。单值；附锚点与理由的修订；旧值留在历史中 |
| **解释层** | Observation；`stated_by: agent` 的记录；`SUPPORTS` / `OPPOSES`；全部 Artifact；Concept 中的 Issue、Proposition 与方法层级 | 没有单一真值，合理的分歧长期存在 | 多值并存，各带来源，不裁决 |

这条线在模型中已经存在（`stated_by: paper | agent`），不需要新增实体或字段。

分层也让评测可行：有据层以原文为金标准，冲突检出与修订后读到的值都能客观测量；解释层不测真值，只测分歧是否被保留、读者是否看得到。

### 4.3 前身与反面参照

解释层的做法即 Trio 的备选值、CRDT 多值寄存器与 Wikidata 的 rank 一路："冲突值带来源并存，系统不裁决"。有据层的做法接近带来源的协作编辑：单值、可修订、保留历史。

反面参照是 truth discovery（Li 等 2016 综述），由系统按来源可信度自动裁决冲突。按使用或引证次数排名（如 PageRank）同样不采用，原因有四：

- 流行不等于正确，早期的错误产物被反复复用后排名反而上升，形成错误级联；
- Agent 倾向于取排名靠前的内容，形成反馈环；
- Agent 复用成本低，引用次数容易虚高；
- 这会把问题引向信誉系统，属于另一个研究问题，也难以评测。

使用次数可以作为读取信号之一，与来源、时间、过时与否、独立核对次数一同返回，但不作为裁决。"使用次数与正确性是否相关"可以作为 T1 的观测量。

### 4.4 核对与撤回

- **核对：** 回到原文核对某条记录，结果写成 Verify 或 Check 产生的 Artifact，写明核对的对象与对照的锚点。不需要新增写入类型。权威由此表现为"独立核对的累积"，而不是排名。把 Artifact 的内容采纳为 Observation，不等于独立核对。
- **撤回：** 有据层用现有的删除变更集或 `revert`；解释层写一条 `OPPOSES` 的 Observation。不设计新的撤回语义。

### 4.5 尚待细化（倾向）

- **读取时默认返回什么：** 倾向于有据层返回当前值，附修订历史与未决冲突的提示；解释层返回全部并存的判断及其来源，读者自行选择。
- **并存的单位：** 有据层修订以记录为单位（一个 Experiment 或一条 Claim），改前、改后值由 graph-vc 逐属性记录。

## 5. 起点：库从哪里开始

T1 不预设权威快照，而是从接近空的库开始：

- 论文原文与外部标识已就位；有据层与解释层为空，由写入者读论文后构建。
- 退化发生在构建过程中。若起点是一个完整快照，C1 与有据层分歧几乎测不到，等于跳过命题最关键的一段。
- 读侧阶梯（L0–L4）与 T2 的受控比较，使用 T1 某个检查点的快照；它本身也是 Agent 建出来的。

产品中的对应是三层：

| 层 | 内容 | 来源 | 权威性 |
|---|---|---|---|
| 外部参照 | 论文原文（固定版本的 `Material`）、外部标识（arXiv ID、DOI、OpenAlex ID、Wikidata QID、代码仓库 URL） | 公开来源，按需获取 | 权威在此，库只引用它 |
| 有据层 | Experiment、Claim 等 `stated_by: paper` 的记录 | Agent 读原文转录 | 可对照原文核对 |
| 解释层 | Observation、Artifact 等 | Agent 的判断与综合 | 只可问责 |

**Wikidata 是标识命名空间，不是起点快照。** 它几乎没有实验级、可对照锚点的记录（PatchTST 等方法的覆盖情况待核实）；导入它等于假定身份问题已被他人解决，测不到我们的问题。`identifiers` 已采用 `"<namespace>:<value>"` 形式，加一个 `wikidata:Q…` 命名空间即可链接。产品叙事上，我们管理的是 Wikidata 管不到的那一层（论文内容与 Agent 产物），并以 Wikidata、OpenAlex 等作为身份锚点。

**冷启动的引导。** 产品可以从公开注册表批量导入身份锚点：OpenAlex、Semantic Scholar、arXiv 的 Paper 实体、标识与引用关系；数据集与代码的主页；少量整理过的任务与方法种子（现有的 TSF 种子即属此类）。论文内容层面（实验、结果、条件、主张）没有完整的公开来源，这正是 Agent 的工作。Papers with Code 曾有部分结果排行榜，据记忆已于 2025 年停止服务，其历史数据或可作为有据层结果的部分金标准（待核实）。

**评测约束。** 引导的内容在各组之间相同，A0 以文件形式拿到同样内容；种子绝不能与金标准重合。"空起点 / 引导起点"是否作为 T1 的一个因子，待定。

## 6. 现有工程的复用

现有原型就是系统，新故事不另起工程。E09 是 T1 的实验准备：写入者接入、写入约束与版本日志已经具备，尚未就绪的是两处策略改动、Fork / Merge 与评测运行框架。

### 6.1 部件对照

| 现有部件 | 代码位置 | 原来的说法（本地经验复用 / memory） | 新故事中的角色 | 还要补什么 |
|---|---|---|---|---|
| 数据模型 + `NameKey` 精确键 | `e09/model/`，`graph_model_v2.md` | 经验的结构化索引 | C1：所有写入者共用的身份规则 | 不补 |
| graph-doc + Commit（dry_run → 阻塞项 → `confirm`） | `packages/graph-doc`，`e09/commit/` | 入库管线 | C1 写入时裁决：库提出候选，写入者当场判断 | 一条策略：有据层允许修订（§6.2） |
| graph-vc：带改前、改后值的变更集，提交记录，`revert` | `packages/graph-vc` | 版本历史 | 所有写入的统一日志；C3 修订的载体 | 不补。修订理由与锚点放进提交的 `message` / `meta`，不改模型 |
| Log / Show / Diff / AsOf | `e09/interfaces/` | 历史查询 | 回看历史状态；判断谁在何时写了什么 | 不补 |
| DB 算子：Search / Resolve / Traverse / ReadEvidence | `e09/operators/db/` | 检索经验 | 不在场的读者的读侧接口（L0–L3） | 不补 |
| Agent 算子 → Artifact（`USED`、`Material` 哈希） | `e09/operators/agent/`，`e09/artifact/` | 可复用的产物 | C2 自描述的贡献；解释层天然多值并存 | 不补 |
| Verify / Check 算子 | `operators/agent/verify.py`、`check.py` | 判断类产物 | 核对记录（§4.4） | 不补 |
| `_stale` 读取时计算 | `e09/artifact/stale.py` | 材料变化提示 | C3 过时提示 | 一个原因：输入记录被修订（§6.2） |
| 薄图、厚文档 | `Material` + 文档目录 | "文件系统 + 数据库索引"的 memory 架构 | 原样保留：文件层存内容，图层存身份、引用与提交日志 | 不补 |
| MCP server + pi 工作目录 | `e09/mcp/`，`make workspace` | 通用 Agent 接入 | 写入者 = 带固定任务的 pi session 序列；`session` / `formed_by` 已在记录上 | 评测框架：多写入者调度（轮流执行） |
| Fork / Merge skill | `project_views.md` | 项目视图 | C4 | 按计划实现 |
| I3 的三组（S / S-Cypher / R0） | `experiments/e09/i3/` | 单实例对照 | A3 / A2 / A0 的原型 | 扩展成 T1 的配置 |

表中 `e09/` 指 `experiments/e09/src/e09/`。

解释层基本是零工程：Observation 没有自然键，不同写入者的 Observation 本来就并存；Artifact 每次调用都新建一个，也天然并存。

A0（文件 + Git）与 A3 共用文件层，二者之差正好是图层上的机制。

### 6.2 已商定的改动

- **有据层修订：** 放宽 Commit 契约 §5。`stated_by: paper` 的记录在附锚点与理由时允许修订，二者存入提交的 `message` / `meta`；未附的仍然拒绝。这是 `e09/commit/checks.py` 中的一条策略，不是新机制。
- **`_stale` 增加"输入已修订"：** 现在只检查文档、材料、节点被删与输入产物过时。新增的原因用 graph-vc 日志比对产物形成之后的提交即可。

### 6.3 不做或推迟

- 排名与权威：不做（§4.3）。
- C1 的对象合并与拆分：不实现，只测量重复率与误合并率，写入局限。
- 撤回：沿用现有机制（§4.4）。
- 并发：写入者轮流执行。
- Fork / Merge：倾向于 T1 第一阶段只走直写共享库的路径，分支与推回事件在实现后加入（待确认）。

### 6.4 真正的工程量

真正的工程量在评测运行框架：多写入者调度、注入事件脚本、检查点上的探针，以及 A0、A1、A2 的配置。这些属于评测工程，不改变系统本身。

## 7. 对叙事与评测的影响

- **贡献措辞：** 叙事草稿的 Claim 与贡献改为"经典机制的选择与改造"，在 Related Work 中主动列出前身。
- **Related Work 的组织：** 从按路线分（学术图谱、Agent Memory、语义算子、版本管理）改为按机制分，每个挑战一行，写"经典前身 → Agent 场景下的改变 → 我们的设计"。§2 的表可以作为底稿。
- **消融的含义：** 每项消融等于拿掉一个经典机制。T1 因此回答"在 Agent 写入者场景下，哪些经典机制仍然必要"。即使结果为负（例如只有身份查重有效），也是有价值的发现。
- **金标准按层定义：** 有据层对照原文；解释层只看分歧是否保留、是否可见（§4.2）。
- **起点与引导：** 见 §5。

## 8. 待核对的文献

以下按挑战分组，均为候选，需核对出处并决定是否收入 `references/refs.bib`：

- **C1：** Fellegi & Sunter, A Theory for Record Linkage (JASA 1969)；Wang 等, CrowdER (VLDB 2012)；Franklin、Halevy、Maier, From Databases to Dataspaces (SIGMOD Record 2005)；Vrandečić & Krötzsch, Wikidata (CACM 2014)。
- **C2：** Buneman、Khanna、Tan, Why and Where (ICDT 2001)；Green、Karvounarakis、Tannen, Provenance Semirings (PODS 2007)；W3C PROV-DM (2013)；Groth、Gibson、Velterop, The Anatomy of a Nanopublication (2010)；Clark、Ciccarese、Goble, Micropublications (J. Biomed. Semantics 2014)。
- **C3：** Gupta & Mumick, Maintenance of Materialized Views (IEEE Data Eng. Bull. 1995)；Doyle, A Truth Maintenance System (AI 1979)；de Kleer, An Assumption-Based TMS (AI 1986)；Widom, Trio (CIDR 2005)；Benjelloun 等, ULDBs (VLDB 2006)；Shapiro 等, CRDTs (SSS 2011)；DeCandia 等, Dynamo (SOSP 2007)；Li 等, A Survey on Truth Discovery (SIGKDD Explorations 2016)；双时态数据库（Snodgrass 一系）。
- **C4：** Katz, Version Modeling in Engineering Databases (ACM Computing Surveys 1990)；Berenson 等, A Critique of ANSI SQL Isolation Levels (SIGMOD 1995)；Kung & Robinson, Optimistic Concurrency Control (TODS 1981)；Bhardwaj 等, DataHub (CIDR 2015)；Maddox 等, Decibel (VLDB 2016)；Huang 等, OrpheusDB (VLDB 2017)；已有 `2026-Git4Data`、`2013-GraphSnapshot`。
- **起点相关：** OpenAlex、Semantic Scholar 的公开数据；Papers with Code 的历史数据（服务状态待核实）。

## 9. 待定

1. 读取时的默认返回与并存单位（§4.5）；
2. "空起点 / 引导起点"是否作为 T1 的因子（§5）；
3. T1 第一阶段是否只走直写路径（§6.3）；
4. §8 文献的核对、下载与入 `refs.bib`；
5. Agent 算子代码按现行契约复核。
