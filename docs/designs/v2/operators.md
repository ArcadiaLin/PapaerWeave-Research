# 算子契约

> **状态：** 设计已定（2026-10-12 修订），E09 实现待跟进：各算子的实现状态见第 9 节，正文中未实现的部分标“待实现”。
>
> 本文规定全部算子的定义、输入输出、校验与图模式映射。算子分两部分：
> - **中间件算子**（Search、Resolve、Traverse、ReadEvidence、FetchArtifact、Commit）：对知识库的定位、导航、读原文、取产物文档与入库；
> - **产物算子**（Leaderboard、CompareSettings、Verify、Summarize、Generate）：面向任务，每个算子对应一类产物。产物是有版本、可共同编辑的文档，持久化为第四类节点 Artifact。
>
> 2026-10-12 的修订依据 [`docs/discussions/2026-10-12-task-operators-and-leaderboard.md`](../../discussions/2026-10-12-task-operators-and-leaderboard.md)（下称“讨论稿”）：
> - 原来的 Agent 算子（Extract、Summarize、Generate、Check、Verify、Filter、MatrixConstruct）改为面向任务的产物算子；
> - 产物从“写入后不可修改”改为有版本、可共同编辑；
> - 新增 FetchArtifact；
> - 产物的格式由种子示例、工具说明与轻度校验引导，只在系统要用到的地方要求结构（讨论稿 2.1）。
>
> 旧版见 Git `d36aa54`。对象与关系见 [Graph Model V2](./graph_model_v2.md)，入库见 `docs/experiments/e09/operators/commit.md`（早先的表单契约见 [Commit 契约](./commit_contract.md)），intent 与数据流见 [Workload 拆解](./intents_decompose.md)。

## 1. 总览

### 1.1 两部分算子

| 部分 | 算子 | 谁执行 | 结果 |
| --- | --- | --- | --- |
| 中间件算子 | `Search`、`Resolve`、`Traverse`、`ReadEvidence` | 中间件，确定性执行 | 任务内返回，不写库 |
| 中间件算子 | `FetchArtifact` | 中间件，确定性执行 | 把产物文档写到工作目录，不写库 |
| 中间件算子 | `Commit` | 中间件，确定性执行 | graph-doc 入库 |
| 产物算子：结果表 | `Leaderboard` | Agent 编辑文档，中间件校验并登记版本 | 新建产物，或给已有产物加一个版本 |
| 产物算子：判断 | `CompareSettings`、`Verify` | 同上 | 同上 |
| 产物算子：文本 | `Summarize`、`Generate` | 同上 | 同上 |

Agent 能用的工具就是这 11 个算子，另有版本记录的读取接口（[读取接口](./versioning_interfaces.md)）。中间件算子回答“库里有什么、原文写了什么”；产物算子记录“Agent 用这些做了什么”，并让后来者在同一份产物上接着做。

### 1.2 职责边界

- **中间件不调用 LLM。** 产物的内容（结果行、判断、概述）由 Agent 写在文档里交给中间件；中间件只做确定性的事：校验引用与出处、比对版本、计算编辑提示与读取时的附注，并持久化。这与 AgenticScholar 不同：后者的这些算子是系统内部的一次 LLM 调用。
- **所有写入经同一版本底层。** 每次写入先校验，再经 graph-vc 在一个事务中写入并产生一个提交记录（版本历史），提交后补算向量。`Commit` 是提交 graph-doc 的算子；产物算子不是 `Commit`，但它们登记产物版本时使用同一底层（第 5.5 节）。校验不通过时不写入，返回错误。
- **引用只接收已确认的 id。** 名称先经 `Resolve`，语义候选由 Agent 确认后才能作为引用；库中还没有的对象先经 `Commit` 新建。
- **关系存在不是证据强度。** 路径、参与关系与 `USED` 只说明记录了这些关联；`SUPPORTED_BY`、`SUPPORTS` / `OPPOSES` 记录的是作者或 Agent 的陈述，不经验证。
- **空结果不等于原文没有。** 论文表单选择性录入，按批次记录的 `coverage` 区分"原文没有报告"与"没有录入"（[Commit 契约](./commit_contract.md) §6）。数值、条件与结果行不在图中，由 Agent 读原文后写进 `Leaderboard`（第 4.2 节）。

### 1.3 设计取向：灵活，但不完全灵活

产物文档的格式由种子示例、工具说明与轻度校验引导，不由中间件强制。**只在系统要用到的地方要求结构，其余一律自由。** 被要求的结构只有三种，每一种都说得出是哪个机制在用它：

- **键**：让不同写者收敛到同一份产物、同一行（产物的身份键与行键，第 4.1 节）；
- **引用**：让产物连进图里，可以沿关系找到、可以计算过期（第 5.2、5.6 节）；
- **出处**：让值可以对照原文核查（来源引用，第 2.1 节）。

其余的列、段落与说明文字都由写者决定。

**种子示例。** 库的起始状态里每类产物至少有一份示例，由 `seed` 写入：种子论文（Informer、SCINet）在各数据集上的 Leaderboard，以及 CompareSettings、Verify 各一份。示例要包含难写的情况，如 look-back 写成说明文字的行。A0 同样拿到这些示例（作为文件），但不附任何“须一致维护”的提示（讨论稿第 7 节）。`Generate` 只要求“引用必须存在”，是最自由的产物，相当于通用的编辑。

这些要求使产物可以核查、可以接着做，代价是更多的调用与 token。因此评测与叙事以回答和报告的质量为主（正确性、可核查性、依据是否充分、能否复用），不主张单次任务的成本优势；成本作为代价如实报告。

## 2. 共同约定

### 2.1 引用

| 引用 | 形式 | 指向 |
| --- | --- | --- |
| 对象引用 | `<kind 前缀>_<序号>`，如 `method_0027`、`exp_0012`、`art_0003` | 一个节点；由入库分配，当前不修订、不合并 |
| 来源引用 `source_ref` | `<material_id>::<章节>::<start>:<end>` | 一份固定材料（论文原文或 Artifact 文档）中的行范围；由 `FROM {material_ref, locators}` 或 `USED {material_ref, locators}` 逐个定位拼出 |
| 记录引用 | `<artifact id>#<key>` | 产物文档中的一条记录（如 `Leaderboard` 的一行、`CompareSettings` 的一个维度），`key` 为该记录的行键（第 4.1 节），指向当前版本中的这一行 |

正文中的引用处直接写引用本身，放在方括号里，例如 `[exp_0012]`、`[art_0003#method_0014+PatchTST/64+paper_0020+96+512]`、`[material_1ec346c934e6::5.3 ...::245:290]`。产物文档与最终回答都用这一写法，不另设脚注编号。

### 2.2 对象视图

`Traverse` 返回的对象视图就是 graph-doc（读写同形，格式见 `docs/experiments/e09/operators/commit.md` §2 与 §6 R）：`nodes` 以对象 id 为键，字段按写入时的拼写给出，原样交回 `Commit` 为 `noop`。

- **字段。** `kind`、`name`、`aliases`（由 NameKey 装配，不含与 `name` 规范化后相同的写法）、`identifiers`、`stub`、`year`、`material`、`definition` / `description` / `text`、`anchors`、`stated_by`、`note` 等；自然键（`exp_key`、`content_key`）与 `embedding` 等派生属性不出现。
- **关系。** 每个节点带它**全部**的模型出边，一个关系键列出该类型出边的完整集合（只列一部分交回时会删掉其余的边）；边上的属性写在边里，如 `{to, role}`、`{to, locators}`。入边不出现在节点上，经 `Traverse` 沿入边走到对方节点，对方节点的出边里就有这条边。
- **只读字段**以 `_` 开头，交回时被忽略：有材料的节点与 `FROM` 边的 `_material`（材料 id），Agent 形成的记录与正反关系的 `_formed_by`、`_formed_at`。
- **Artifact** 只由产物算子写入，字段全部只读：`_op`、`_op_version`、`_key`（身份键，没有时省略）、`_title`、`_abs`、`_formed_by`（创建者）、`_formed_at`、`_version`（`{n, commit, by, at, abstract}`，当前版本）、`_editors`（各编辑者及其版本）、`_material`、`_document`（当前版本的文档路径）、`_stale`（第 5.6 节）与 `_USED`（`{to, role?, locators?}`，带来源引用的边另有 `_material`）。版本与编辑者由提交记录推算，待实现。

Observation 的 `ABOUT` 始终给出完整的对象集合：某个对象命中不代表结论对它单独成立。

### 2.3 AccessResult

`Traverse` 返回读视图：一份 graph-doc，`nodes` 是结果涉及的对象视图（第 2.2 节），`meta` 是 AccessResult。`Search` 返回结果视图（第 3.1 节），只有摘录，不带关系；它的 `meta` 是下表中的一部分，其余字段写入日志：

```text
AccessResult = {query, items, bindings, source_refs, missing, coverage, continuation, diagnostics}
```

| 字段 | 内容 |
| --- | --- |
| `query` | 本次请求的参数 |
| `items` | 主体结果的 id，按结果顺序去重；下一步取 `refs(X)` 默认只取这里的引用 |
| `bindings` | 每个结果的取得依据：`Search` 为精确命中的方式，或各通道的名次与融合分（按结果 id 给出；按结构条件枚举时为空；只写入日志），`Traverse` 为每条路径，写成节点与关系交替的列表，如 `[method_0028, <-EVALUATES-, exp_0001, -USES->, dataset_0006]`；边上属性在起点一侧节点的出边里 |
| `source_refs` | 结果涉及的来源引用（写成材料 id 的形式），按出现顺序去重；只定位，不读取 |
| `missing` | 库中不存在的引用参数：`{ref, param, missing_in: store}` |
| `coverage` | 参数、范围、预算、已匹配与返回数量、是否截断、通道状态、快照（当前提交的 id） |
| `continuation` | 截断时的续取位置；为空表示已取完 |
| `diagnostics` | 不进入结果、但调用方需要知道的数量与引用，例如角色缺失、可展开的额外匹配 |

`Traverse` 的 `nodes` 是本页路径上的全部节点（起点、中间节点与终点）。

### 2.4 预算、错误与会话

- **预算**是一次调用返回的主体结果数上限；截断必须可见（`Traverse` 在 `coverage` 中，`Search` 为非空的 `continuation`），续取时传回 `continuation`，其余参数不变。
- **容量。** MCP 客户端会截断过长的工具结果（pi 为 20 KB），所以 `Search` 与 `Traverse` 的结果另有 16 KB 的容量上限，`meta.size` 给出上限与实际大小。`Search` 截短摘录（第 3.1 节）；`Traverse` 的对象视图要原样交回 `Commit`，不截断字段，放不下时从本页末尾去掉路径，续取位置随之前移。
- **读取所在的提交。** `Search` 的 `meta.snapshot` 与 `Traverse` 的 `meta.coverage.snapshot` 是读取所在的提交，可以交给版本记录的读取接口 `AsOf`、`Diff`（[读取接口](./versioning_interfaces.md)）。读取前后各读一次主分支的头提交：两次相同才给出它；读取期间有写入时为 `null`，`diagnostics.snapshot` 说明原因，重新调用即可得到。
- **契约错误**（未知参数、类型不符的引用、该类别不支持的条件、图模型中不存在的端点组合）直接报错，不返回部分结果。所有算子没有完成时的返回同形：`{status, errors}`，`status` 为 `rejected`（请求没有被执行，什么也没有写入）、`blocked`（`Commit` 的阻塞项）或 `conflict`（提交时与并发写入冲突），`errors` 的每一项为 `{rule, at, msg}`，`at` 指向出错的参数或节点，`Commit` 的阻塞项另带 `candidates` 与 `fix`。请求的顶层形状不对（未知参数、缺少必填参数）记为 `format`，参数的取值不对记为 `schema`。
- **数据缺失**（引用不在库中、关系无记录）返回空集合与覆盖信息，不当作错误。
- **执行失败**（向量服务不可用、索引缺失）记入通道状态（`Search` 为 `meta.failed`）；因失败而没有结果时不当作空结果。
- **会话**：产物算子的会话标识 `session` 与形成者 `formed_by` 记在产物版本的提交上，用于按会话追溯产物。二者是调用环境的信息，由调用方给出（MCP 服务：进程启动时生成的会话与环境变量 `E09_FORMED_BY`；命令行：`--session`、`--formed-by`），不是算子参数；算子作为工具时，参数中也没有 `op`，工具名就是算子名。

## 3. 中间件算子

### 3.1 Search

**用途：** 在一个类别内按查询与结构条件发现对象。lookup 用 `Resolve`，沿关系走用 `Traverse`。

```text
Search(type, query?, kinds?, where={}, expand={}, scope="global", budget, continuation?) -> AccessResult
```

| 参数 | 说明 |
| --- | --- |
| `type` | `Entity`、`Concept`、`Content` 或 `Artifact`，一次一个类别 |
| `query` | `{identifier?, mention?, text?}`；只给字符串时视为 `text`。省略时按结构条件枚举，按 `id` 排序 |
| `kinds` | 类内类型，如 `{Experiment, Claim}`；Artifact 没有 kind，用 `where.op` |
| `where` | 结构条件，见下表；多个条件取合取，同一条件给列表时取析取；Content 上的多个条件绑定同一条记录 |
| `expand` | 放宽 `where` 中的引用条件：`narrower: depth`（Concept，反向 `BROADER`）、`parts: depth`（Entity，反向 `PART_OF`），深度 1–3 |
| `scope` | `"global"` 或论文 id 列表；论文列表只作用于 Content（`FROM` 这些论文的记录） |

**查询分量与通道：**

| 类别 | 接受的分量 | 通道 |
| --- | --- | --- |
| Entity | `identifier`、`mention`、`text` | 标识精确匹配；名称词面（NameKey）；description 全文与向量 |
| Concept | `mention`、`text` | 名称词面；definition（陈述型为 text）全文与向量 |
| Content | `text` | text 全文与向量 |
| Artifact | `text` | `title` 与 `abs` 的全文与向量 |

标识与 NameKey 精确命中按声明的优先规则排在前面，不参与融合计分；其余通道按 RRF 融合，跨类别不比较原始分数，不设阈值。向量索引按主 Label 建立，先超取再按 kind 与 `where` 过滤，可能漏掉条件内的可行候选，超取倍数与过滤方式记入 `coverage`。

**结构条件：**

| 类别 | 条件 | 图模式 |
| --- | --- | --- |
| Entity | `part_of: ref` | `(x)-[:PART_OF]->(ref)` |
| Entity | `for_task: ref` | `(x)-[:FOR_TASK]->(ref)` |
| Entity / Concept | `stub: bool` | `x.stub` |
| Concept | `broader: ref` | `(x)-[:BROADER]->(ref)` |
| Content | `about: ref` | `(x)-[:ABOUT]->(ref)` |
| Content | `from: paper_ref` | `(x)-[:FROM]->(paper)` |
| Content | `stated_by: paper \| agent` | Contribution 的 `stated_by` |
| Content | `formed_by: str` | Agent 形成的记录的 `formed_by` |
| Experiment | `evaluates: ref`，可加 `role: target \| baseline` | `(x)-[:EVALUATES {role}]->(ref)` |
| Experiment | `uses: ref` | `(x)-[:USES {role: evaluation_data}]->(ref)` |
| Experiment | `on_task: ref` | `(x)-[:ON_TASK]->(ref)` |
| Experiment | `evaluated_on: ref` | `(x)-[:EVALUATED_ON]->(ref)` |
| Claim | `supported_by: ref` | `(x)-[:SUPPORTED_BY]->(ref)` |
| Artifact | `op`、`formed_by`（创建者） | Artifact 属性 |
| Artifact | `edited_by: str`（任一版本的编辑者，待实现） | 由提交链推算 |
| Artifact | `used: ref` | `(x)-[:USED]->(ref)` |

**诊断：** 写了 `uses` 条件时，另报 `role_missing`（`USES` 指向该数据集但没有 `role` 的实验）与 `expandable`（评测数据落在其组成部分上、本次没有用 `expand.parts` 选中的实验），只给数量与引用。

**默认不查 Artifact。** `type` 为 Entity、Concept、Content 时结果中不出现 Artifact；要找已有的工作产物，显式写 `type=Artifact`。

**输出：** 结果视图 `{results, meta}`，不是 graph-doc。Search 只负责发现：每个结果给识别字段与检索字段的开头摘录，不带关系；对象的完整字段与全部关系用 `Traverse` 读取（`path` 为空即读取起点对象），原文用 `ReadEvidence` 读取。

| 类别 | 识别字段 | 摘录字段 |
| --- | --- | --- |
| Entity | `id`、`kind`、`name`、`year` | `description` |
| Concept | `id`、`kind`、`name` | `definition` 或 `text` |
| Content | `id`、`kind`、`paper`（`FROM` 的论文 id）、`anchors`、`source_refs` | `text`，另有 `note` |
| Artifact | `id`、`op`、`title`、`document`（文档路径）、`version`（版本号、最近的编辑者与提交）、`stale`（有时） | `abs` |

摘录字段即该类别全文与向量检索的字段；Content 另带 `note`，原文中的问题（印刷错误、推断的设置）常记在这里。

**容量。** MCP 客户端会截断过长的工具结果（pi 为 20 KB，截掉中间部分，且不能配置），所以整份结果按 YAML 字节数控制在 16 KB 以内：先放下各结果的识别字段与 `meta`，放不下时从末尾去掉结果、续取位置随之前移；余下的容量平均分给各结果的摘录，摘录本来就短的结果省下的部分再平均分给其余结果；一个结果内先给 `text` 再给 `note`。超出份额的字段在 UTF-8 字符边界截断，末尾写 `…`，其后的 `<字段>_bytes` 给出原文长度。

`meta` 为 `returned`、`matched`、`continuation`、`snapshot`、`size`（`{limit, used, cut}`，`cut` 是被截断的字段数），以及非空时的 `missing`、`diagnostics`、`expanded`（`expand` 实际放宽到的引用）与 `failed`（失败的通道及原因）。取得依据与覆盖信息（通道状态、候选池、向量超取）写入日志 `e09.search`（MCP 服务写在 stderr 与 `E09_MCP_LOG`）。

**不做的事：** 不接受自然语言的 `where`；不按语义判断"是否适用"；Benchmark 引用不当作数据集条件。

### 3.2 Resolve

**用途：** 把一个说法解析为 Entity 或 Concept 的引用。`Commit` 的查重也调用它（write 模式）。

```text
Resolve(query={identifier?, mention?, text?}, kind, scope="global", mode=read | write)
  -> {status: resolved | ambiguous | candidates | none | unprocessed, refs, similar?, issues?, failed?}
ref = {id, kind, name, aliases?, about?}
```

**输出：** 解析视图。`refs` 的每一项带名称、别名与说明的开头（`about`，description 或 definition 的前 200 字节），供 Agent 判断候选是不是它要找的对象，完整字段用 `Traverse` 读取；`similar` 是精确命中以外的语义近邻（write 模式的查重、read 模式 ambiguous 时）；`issues` 是标识与名称冲突等数据问题；`failed` 是执行失败的通道。匹配过程（各阶段的键与命中、各通道的名次与融合分、`states`、`coverage`）写入日志 `e09.resolve`；`Commit` 的查重直接使用这份完整结果。

- **只解析 Entity 与 Concept。** Content 与 Artifact 没有称呼，用 `Search` 定位。
- **三级解析：** 已注册标识（唯一命名空间单个命中即 resolved，非唯一命名空间只缩小候选）→ NameKey 精确键（active 键唯一命中即 resolved）→ 名称词面、文本、向量三通道按 RRF 融合的语义候选。标识与名称同时给出时取交集；名称命中了对象而交集为空时记 `resolution=conflicting`。
- **mode：** read 模式前两级 resolved 即停止；write 模式仍跑语义查重，近邻在 `similar` 中。
- **不设阈值。** 库中没有的对象通常以 `candidates` 返回；"库中没有"由 Agent 对候选逐个否定得出；入库时由 `Commit` 的查重把候选退回写者确认。因执行失败而没有引用时为 `unprocessed`，不当作 `none`。

| 返回 | 下游处理 |
| --- | --- |
| `resolved` | 直接采用引用 |
| `ambiguous` | Agent 在 `refs` 中确认；`resolution=conflicting` 时另作数据问题报告，不自动采用任一侧 |
| `candidates` | Agent 逐个确认；全部否定时记 `resolution=missing`、`missing_in=store` |
| `none` | 保留为未解决项，需要时经 `Commit` 新建对象 |
| `unprocessed` | 进入错误出口 |

同一任务中按说法键 `(raw, kind, scope)` 去重。新写法经确认后，经 `Commit` 的 `register` 注册为 alias。

### 3.3 Traverse

**用途：** 从已确认的引用出发，沿声明的关系走到相关对象，保留路径与边上属性。路径为空时只返回起点的对象视图（即"按 id 读取"）。

```text
Traverse(start, path=[], budget, continuation?) -> AccessResult
hop = {rel, dir: out | in | both, kinds?, where?, edge?, depth?: 1–3}
```

| 参数 | 说明 |
| --- | --- |
| `start` | 起点引用列表，可混合类别 |
| `path` | 0–3 跳；每跳一个 `hop` |
| `hop.rel` | 关系类型或其列表，只能取下表中的类型 |
| `hop.dir` | 方向；对称关系 `OVERLAPS_WITH` 忽略方向 |
| `hop.kinds` | 该跳终点的类型限制，如 `{Experiment}`、`{Artifact}` |
| `hop.where` | 终点的结构条件，与 `Search` 同表 |
| `hop.edge` | 边上属性条件，如 `{role: target}`、`{stated_by: agent}`；边上属性是列表时（`USED` 的 `role`、`locators`）按包含匹配 |
| `hop.depth` | 只用于传递性关系（`BROADER`、`PART_OF`、`HAS_PART`、`DERIVED_FROM`）的可变长匹配；不重复走同一条边，环在此截断。`USED` 不是传递性关系，沿产物的输入链往回走时逐跳写出 |

**可走的关系：** `FROM`、`ABOUT`、`EVALUATES`、`USES`、`ON_TASK`、`EVALUATED_ON`、`SUPPORTED_BY`、`SUPPORTS`、`OPPOSES`、`PART_OF`、`DERIVED_FROM`、`CITES`、`IMPLEMENTS`、`FOR_TASK`、`BROADER`、`HAS_PART`、`ADDRESSES`、`OVERLAPS_WITH`、`USED`。系统关系 `NAMES`、`MATERIAL_OF` 不对外开放：别名在视图中，文档在 Artifact 视图的 `_document` 中。

**校验：** 每一跳按图模型的端点表（[Graph Model V2](./graph_model_v2.md) §6）检查起点类型、关系、方向与终点类型能否成立，不成立是契约错误，例如从 Method 出发沿出边走 `EVALUATES`。

**输出：** 读视图（第 2.3 节）。`items` 为最后一跳的终点（去重）；`nodes` 为本页路径上的全部节点；`bindings` 为每条路径，写成节点与关系交替的列表，关系带方向（`-REL->` 或 `<-REL-`）。边上属性（`role`、`description`、`stated_by`、`locators` 等）在起点一侧节点的出边里，原样给出。正反关系保留真实方向，不推导传递关系。预算按路径计，截断时报告已见数量；容量见第 2.4 节。

**常用路径：**

| 想取得 | `Traverse` |
| --- | --- |
| 对象本身 | `Traverse([x])` |
| 讨论某对象的主张 | `Traverse([m], [{rel: ABOUT, dir: in, kinds: {Claim}}])` |
| 评测了某方法的实验 | `Traverse([m], [{rel: EVALUATES, dir: in}])` |
| 主张的依据实验及其数据 | `Traverse([c], [{rel: SUPPORTED_BY, dir: out}, {rel: USES, dir: out}])` |
| 主张的正反关系 | `Traverse([c], [{rel: [SUPPORTS, OPPOSES], dir: both}])` |
| 论文的引用与被引 | `Traverse([p], [{rel: CITES, dir: both}])` |
| Benchmark 的成员数据集 | `Traverse([b], [{rel: PART_OF, dir: in, depth: 2}])` |
| 用过某篇论文的工作产物 | `Traverse([p], [{rel: USED, dir: in, kinds: {Artifact}}])` |
| 某数据集上的 Leaderboard | `Traverse([d], [{rel: USED, dir: in, kinds: {Artifact}, where: {op: Leaderboard}}])` |
| 对某条主张的核查 | `Traverse([c], [{rel: USED, dir: in, kinds: {Artifact}, where: {op: Verify}}])` |

### 3.4 ReadEvidence

**用途：** 按来源引用读取固定材料中的行。论文原文与 Artifact 文档都是材料，读法相同。读整份产物文档用 `FetchArtifact`（第 3.6 节）更方便。

```text
ReadEvidence(source_refs, at?) -> {items, missing, coverage}
```

引用的开头写材料 id，或写带材料的节点 id（论文或 Artifact），两者等价。按 Material 节点的路径与内容哈希读取，只定位与读取，不解释内容；读到的每行带行号，便于引用其中更小的范围。逐项记录材料状态：`available`（读到，且文件哈希与入库时一致）、`missing`（引用格式不对、库中没有该材料或文件不在）、`error`（文件哈希变了或行号越界；不返回可能错位的文本）。`missing` 列出状态为 `missing` 的引用，各状态的数量在 `coverage` 中。

读的是产物文档时，结果另带一行编辑提示（第 5.6 节），待实现。

**只读产物文档的读者条件。** 服务启动时设 `E09_EVIDENCE_SCOPE=artifacts`，ReadEvidence 只读产物文档：引用落到论文材料时返回 `missing`，原因写明“这里只能读产物文档，不能读论文”。T1 的 `store_only` 读者用这一设置（[冻结记录](../../decisions/2026-10-11-t1-pilot-2-freeze.md) §6）。

`at`（提交 id 或 `main`）给出时，按该提交时的状态解析引用，`coverage.at` 给出固定下来的提交。它用于读取 `AsOf` 旧视图中的材料：即使材料节点或它的归属关系后来被删除，也能读到；文件仍按登记的哈希核对（[读取接口](./versioning_interfaces.md) 第 6.2 节）。

### 3.5 Commit

**用途：** 把论文知识与 Agent 的理解入库。提交物是 graph-doc（读写同形的子图，交上来的就是想要的状态），设计见 `docs/experiments/e09/operators/commit.md`：graph-doc → dry_run 返回 graph-plan（修改、阻塞项及候选与改法、提示）→ Agent 按阻塞项修改后重交 → apply（graph-vc 单事务提交，产生一个提交记录，提交后补算向量）返回 graph-result。新建、修改、删除与合并都用同一写法；早先的论文表单与增补表单（[Commit 契约](./commit_contract.md)）已转成 graph-doc。

graph-doc 可以引用 Artifact：Observation 的 `ABOUT` 可指向 Artifact，`FROM` 可指向 Artifact 并带其文档的行范围，这是把工作产物提升为长期记录的途径（第 5.7 节）。Artifact 本身不能经 `Commit` 新建或修改，只能经产物算子；删除被 `USED` 指向的节点时，dry_run 提示用过它的 Artifact 将显示为可能过期。

**返回相关的共同产物（待实现）。** 提交后，graph-result 列出这次提交涉及的对象上挂着的共同产物，让写者知道自己刚写的内容与哪些产物有关。当前只沿一条路径：本次写入或修改的 Experiment → 它 `USES` 的评测数据集 → 以该数据集为身份键的 `Leaderboard`；另列出“还没有 Leaderboard 的数据集”。

```text
Shared artifacts on objects this commit touches:
  leaderboard art_0003 "ETTh1 multivariate long-term forecasting" — v3, last edited by bob (commit_000041)
  ... 7 leaderboards in all (datasets used by exp_0031)
  no leaderboard yet for: ILI
```

这是查询结果，不是要求：任务提示不要求写者维护 Leaderboard。是否沿更多路径（方法、主张）返回，待看采用率再定（讨论稿第 13 节）。

### 3.6 FetchArtifact（待实现）

**用途：** 把产物的文档取到工作目录，供阅读与编辑。它是检出：编辑后经对应的产物算子检入（第 4.1 节）。

```text
FetchArtifact(artifact | [artifact, ...], at?)
  -> {items: [{artifact, path, version, hint}], missing}
```

- 文档写到工作目录的 `./artifacts/<标题>.md`；同名文件已存在时覆盖，并在返回中说明。
- 写出的文档头部多两行 `id` 与 `base`（取出时的版本所在提交），检入时据此核对；写者不应修改这两行。
- `at`（提交 id）给出时取该提交时的版本，只供阅读：检入时 `base` 不是最新版本会被拒绝。
- `hint` 是编辑提示（第 5.6 节）：版本号、最近的编辑者与修改说明、各编辑者，以及“自你上次编辑以来别人改了哪些行”。Leaderboard 另带读取时现算的附注（第 4.2 节）。
- 一次可取多份：一篇论文往往涉及多张 Leaderboard。
- 只取产物文档，不取论文，所以在只读产物文档的读者条件下也可用。

```text
FetchArtifact(artifact: art_0003)
→ wrote ./artifacts/ETTh1 multivariate long-term forecasting.md
  art_0003 · version 3 · last edited by bob (commit_000041): "Add Autoformer's own results from Autoformer Table 1"
  editors: seed (v1) · bob (v2, v3)
  You have not edited it before.
  To change it: edit the file, then call Leaderboard(artifact_doc, update_abstract). Do not edit the id and base lines.
```

工作目录与路径规则与草稿文件相同（[草稿文件](./draft_files.md) §6）。

## 4. 产物算子（待实现）

### 4.1 共同契约

**检出、编辑、检入。** 产物是工作目录里的一份 Markdown 文档。写者用 `FetchArtifact` 取出已有的产物（第 3.6 节），或照着种子示例新写一份；用自己的文件工具编辑；再调用对应的产物算子检入。

```text
<Op>(artifact_doc | [artifact_doc, ...], update_abstract, confirm?)   # 调用环境另给 session、formed_by
  -> {status: checked, items: [{doc, artifact?, action: create | update | noop, changes, others, errors, warnings}]}
   | {status: committed, commit, items: [{doc, artifact, version, document, notes}]}
   | {status: rejected | conflict, errors}
```

| 参数 | 说明 |
| --- | --- |
| `artifact_doc` | 工作目录中的文档路径，或路径列表。头部带 `id` 与 `base` 时是更新，不带时是新建。路径规则与草稿文件相同（[草稿文件](./draft_files.md) §6） |
| `update_abstract` | 这次改了什么、为什么。必填，进入提交的 `message`，也作为编辑提示显示给后来者（第 5.6 节） |
| `confirm` | 省略时只校验：返回每份文档的改动、错误与警告，不写入（`checked`）。`true` 时写入。改动了他人写的行时须写成 `{reason: <理由>}`（见下） |
| `session`、`formed_by` | 会话标识与编辑者，由调用环境给出（第 2.4 节） |

- **先校验、后写入**，与 `Commit` 的 dry_run → confirm 相同。警告在写入前就给出，不会为了改一个笔误多出一个版本。
- **一次可交多份。** 每份各自校验；任一份有错误时整次不写入。全部通过时在一个提交中写入，每份产物各得一个新版本。
- **文档按原样保存。** 中间件不重新生成文档：去掉头部的 `id`、`base` 两行后，交上来的就是新版本的内容。写者的排版、多加的列与段落都保留。
- **与最新版本相同**时为 `noop`，不产生版本。

**`changes` 与 `others`。** 校验时把交上来的文档与基础版本逐行比对：

- 表格中的行按该类产物的**行键**对齐（第 4.2–4.6 节），分出新增、修改、删除的行；
- 表外的文字按行比对，同 `git blame`；
- `others` 列出被改动或删除的、由他人写入的行，以及每一行最近的编辑者。种子写入的行也算他人的行。

**改动他人的内容须写理由。** `others` 非空时，`confirm` 须写成 `{reason: <理由>}`，否则拒绝。理由记入提交的 `meta`，并出现在编辑提示里。用了新证据时在理由中写出引用（按第 2.1 节的写法，会被校验），不强制。这与 `Commit` 修订有据层记录时要写理由相同（[Commit 契约](./commit_contract.md) §5）；不同的是这里不强制锚点，因为产物属于解释层。改自己写的行不受限制。

**轻度校验。** 只拦会破坏库的东西，其余只警告：

| 情况 | 处理 |
| --- | --- |
| 头部的 `id`、`base` 被改，或 `base` 不是该产物最新版本的提交 | 拒绝（`conflict`）：提示重新 fetch，把自己的改动合并进去后再交；不做自动合并 |
| 新建的产物，其身份键已有一份产物 | 拒绝，返回已有那份的 id，让写者去 fetch 它 |
| 更新时改了身份字段（如 Leaderboard 的 `dataset`），且新键已有一份产物 | 拒绝，同上。新键没有产物时允许，等于改键，并在 `changes` 中列出 |
| 文档中出现的对象 id、产物 id 或记录引用不在库中 | 拒绝（`reference`） |
| 来源引用格式错误、所指材料不存在或行号越界 | 拒绝（`reference`） |
| 改动或删除了他人写的行，`confirm` 中没有 `reason` | 拒绝（`others`） |
| 各类产物自己的轻度规则（第 4.2–4.6 节） | 拒绝（`schema`） |
| 数字没有出现在所引来源的那几行中 | 警告 |
| 文档结构与种子示例不同（缺列、多列），或某列的写法与示例不同（如该写数字处写了文字） | 警告，并给出示例的写法 |

“数字是否出现在所引的行中”是确定性的检查，不需要 LLM，能抓住大部分抄错。

**产物的身份键。** 共同维护的前提是写者收敛到同一份产物上。每类产物有自己的身份键，由头部字段算出，按字符串规范化（去首尾空白、统一大小写与空白）后比较，不做模糊匹配。新建时同键已有产物，就像 `Commit` 的查重退回候选一样，把已有的那份退回写者。

| 产物 | 身份键 | 行键 |
| --- | --- | --- |
| `Leaderboard` | （任务、数据集、设置） | 方法、变体、论文、预测长度、look-back |
| `CompareSettings` | 被比较的两项（无序） | 维度 |
| `Verify` | 被核查的主张 | 无，按行比对 |
| `Summarize`、`Generate` | 无：每次新建都是一份新的产物 | 无，按行比对 |

行键的各字段按字符串比较，可以写说明文字（如 look-back 写“best of 24–720”），只警告不拒绝。记录引用 `<artifact id>#<key>` 中的 `key` 是行键各字段以 `+` 相连，空字段留空，如 `art_0003#method_0001++paper_0001+24+96`。不用逗号与分号，因为它们在方括号中分隔多个引用。

**返回。** `checked` 时，每份文档给出：动作；`changes`（新增、修改、删除的行数，修改与删除的行逐一列出）；`others`；`errors`；`warnings`。`committed` 时给出提交 id、每份产物的 id 与新版本号、新版本的文档（路径与 `material_ref`），以及读取时现算的附注 `notes`（第 4.2 节）。

**错误**的形状与 `Commit` 的阻塞项相同：`{rule, at, msg}`，`at` 写成 `<文件>:<行号>`，写者就地改那几行再交。`rule` 为 `format`、`schema`、`reference`、`others`、`identity`（身份键已有产物）或 `conflict`。

**判断的取值。** `CompareSettings` 与 `Verify` 的结论沿用三值：`T` 表示在声明的条件与依据下成立；`F` 表示有依据判断不成立；`U` 表示依据不足、相互冲突或条件含义不明。`T` 与 `F` 须给出依据（引用），`U` 须写明原因。

**文档头部。** 所有产物都是“头部 + 正文”。头部是 YAML：`id`、`base`（只在取出的文档中出现）、`title`、`abs`，以及各类产物的身份字段。`title` 与 `abs` 是检索文本。

### 4.2 Leaderboard

**用途：** 共同维护的结果表。一份对应一个（任务、数据集、设置），如“ETTh1 多变量长期预测”，跨论文、跨预测长度。论文中的结果数值经它进入库，取代原来的 `Extract` 与 `MatrixConstruct`。服务 I3；对应 PapersWithCode 的评测表。

```markdown
---
id: art_0003
base: commit_000057
title: ETTh1 multivariate long-term forecasting
abs: MSE and MAE reported for methods on ETTh1 (multivariate), by paper and forecasting horizon.
task: task_0001          # Long-term time series forecasting
dataset: dataset_0002    # ETTh1
setting: {variate: multivariate}
metrics: {MSE: lower, MAE: lower}
---
## Results

| method | variant | paper | role | origin | lookback | pred_len | MSE | MAE | source |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| method_0001 Informer |  | paper_0001 Informer | target | run | 96 | 24 | 0.577 | 0.549 | material_a1::4.2::120 |

## Papers covered

| paper | tables | complete | note |
| --- | --- | --- | --- |
| paper_0001 Informer | Table 1 (material_a1::4.2::112:140) | yes | horizons 24, 48, 168, 336, 720 |
```

- **列：** `variant` 记变体或配置名（如 `PatchTST/64`），变体不建节点；`role` 区分论文提出的方法（`target`）与基线（`baseline`）；`origin` 区分论文自己跑的（`run`）与转录他文的（`cited`）。
- **“Papers covered”** 记录每篇论文转录了哪些表、是否完整。“论文没有报告这一格”与“没人转录这一格”由此区分。
- **强制的部分及用它的机制：**

  | 强制的部分 | 用它的机制 |
  | --- | --- |
  | 头部的 `task`、`dataset`、`setting` | 身份键：一个键只有一张表 |
  | 头部的 `task`、`dataset` 写成 id | `USED` 边：从数据集出发能找到它的表；`Commit` 返回相关产物（第 3.5 节） |
  | 行键 | 逐行归属与编辑规则；判断“同一篇论文的同一格出现两个值” |
  | `method`、`paper` 写成 id（后面可跟名字） | 同一方法的行聚到一起；表格碎片化的测量 |
  | 每个数值行带 `source` | 数字是否在所引行中的检查；所引论文换版本时的附注 |

- **自己的轻度规则：** 新增与修改的行须带 `source`，且 `source` 落在该行 `paper` 的材料中；`metrics` 中声明的列须为数字或留空。
- **读取时现算的附注**，不写进文档，随 `FetchArtifact` 与检入的返回给出：

  ```text
  --- computed at read (not part of the document) ---
  rows by contributor: seed (40) · bob (+48, commit_000041) · alice (+32, commit_000057)
  superseded sources: 4 rows cite FiLM v3; v4 exists (commit_000090) — rows 61–64
  cells with several values: Autoformer · 96 · MSE: 0.449 (Autoformer paper) / 0.435 (PatchTST paper)
  ```

  “同一格有几个值”要分开两种情况：同一篇论文的同一格有不同的值，说明有人抄错了；不同论文对同一方法报告不同的值，是正常的并存。
- **待定：** 消融表是同样写进 Leaderboard（加一列 `table: main | ablation`），还是每篇论文另建一份结果表。

### 4.3 CompareSettings

**用途：** 判断两组结果是否可比：look-back、数据切分、归一化、训练数据、评测协议等是否一致。服务 I3；由原来的 `Check` 改来。维度由种子示例给出，不再每次自定，这样不同写者的判断能对到同一处。

```markdown
---
title: PatchTST/64 vs TiDE on ETTh1
abs: Whether PatchTST/64 and TiDE results on ETTh1 are comparable.
items:
  - art_0003#method_0014+PatchTST/64+paper_0020+96+512
  - art_0003#method_0031++paper_0033+96+720
verdict: U
---
| dimension | left | right | same | basis |
| --- | --- | --- | --- | --- |
| lookback | 512 | 720 | F | [material_p1::4.1::164] [material_t1::4.1::223] |
| split | 6:2:2 | 6:2:2 | T | ... |
| normalization | ... | ... | U | not stated in TiDE |
```

- **强制的部分：** `items`（被比较的两项，写成 Leaderboard 的记录引用或实验 id），用作身份键，也让读者从 Leaderboard 的格子找到对它的可比性判断；表中每个维度一行、`same` 为三值，`T` 与 `F` 带依据；`verdict` 为三值。
- **维度：** 种子给出 `lookback`、`split`、`normalization`、`training_data`、`protocol`，另可加 `other` 等行。
- **报告值关系（可选）：** 两项是不同论文对同一方法、同一格报告的值时，头部可写 `relation: same_source | independent | incomparable | unknown`，即“按论文自己的陈述，这两个值本该是什么关系”（[Workload 拆解](./intents_decompose.md) I3）。
- 详细格式下一轮随种子一起定。

### 4.4 Verify

**用途：** 一条主张在给定证据下是否成立、在什么范围内成立。服务 I2、I5。

```markdown
---
title: Verify "channel independence reduces overfitting" (PatchTST)
abs: ...
claim: claim_0042
verdict: T
scope: on the 8 datasets of Table 3, with look-back 336/512
---
<依据与推理，引用写在方括号里>
```

- **强制的部分：** `claim`（被核查的主张的 id），用作身份键，也让从 Claim 出发能看到对它的核查；`verdict` 为三值；`T` 与 `F` 时正文至少有一处引用，`U` 时写明原因。
- 核查一条记录是否忠实于原文，写成 `Verify`；把产物内容采纳为 Observation 不算独立核查。

### 4.5 Summarize

**用途：** 忠实压缩多份材料或记录。服务 I4。

- **强制的部分：** 每个段落至少有一处引用（段落以空行分隔，只有标题的段落不计；方括号中的内容全部是引用时才算引用）。这是忠实压缩的检查。
- 没有身份键：每次新建都是一份新的产物；仍然可以被他人编辑。

### 4.6 Generate

**用途：** 最灵活的产物：回答、草稿、点子、方案。服务撰写类任务，用 LLM judge 按 rubric 评，rubric 中单列“出处”一项。

- **强制的部分：** 只有“出现的引用必须存在”。不要求每段带引用。
- 返回 `stats`：段落数、带引用的段落数。引用比例只是报告项，不是校验。

## 5. Artifact

### 5.1 定位

Artifact 是第四类节点，与 Entity、Concept、Content 并列：记录 Agent 使用知识时做出来的东西。前三类来自阅读论文，Artifact 来自使用。它不分子类型，不用语义关系连接其他节点，只记录“用什么做出了什么”。

**每个版本不可变，产物本身可以演进。** 2026-10-12 之前的设计取 OPM 的定义（过程产出的不可变状态），产物写入后不修改；这使一份结果表只能由一个人维护，多写者共同积累无从谈起，所以改为有版本、可共同编辑的文档。OPM 的不可变性落在版本上。

### 5.2 节点与关系

```text
(:Artifact {id: art_<序号>, op, op_version, key?, title, abs, formed_by, formed_at})
(a:Artifact)-[:USED {role?: [..], material_ref?, locators?: [..]}]->(x)    x 为任意 Entity、Concept、Content 或 Artifact
(m:Material {path, content_hash})-[:MATERIAL_OF]->(a:Artifact)            每个版本一份文档
```

| 属性 | 说明 |
| --- | --- |
| `op` | 产物的类别，即检入它的算子 |
| `op_version` | 该类产物当时的工具说明与校验规则的哈希。说明或规则改了，旧版本仍能知道自己是在哪套规则下写入的 |
| `key` | 身份键（第 4.1 节）的规范化字符串；有键的产物上唯一约束 |
| `title`、`abs` | 当前版本头部的标题与摘要，参与检索与向量；每次检入更新 |
| `formed_by`、`formed_at` | 创建者与创建时间 |

- **版本不加字段。** 每次检入在同一个提交中：登记新版本文档的 Material 与 `MATERIAL_OF`；把上一版本的 Material 记上 `superseded_by`（与论文换版本的做法相同）；按新版本重写 `USED` 边；更新 `title`、`abs`。版本号、各版本的编辑者与修改说明都由提交链推算。
- **`USED` 由文档中的引用得出**，不另外声明：头部的 id 字段与正文中方括号里的引用。对象引用指向该对象，`role` 取它所在的头部字段（如 `dataset`、`claim`）；来源引用指向材料所属的节点，边上带 `material_ref` 与 `locators`；记录引用指向所属的产物，边上的 `material_ref` 固定为引用时那个产物的当前版本。同一终点只有一条边，`role` 与 `locators` 都是列表。`USED` 只表示“这个版本用到了它”，不表示支持、讨论或同一。

### 5.3 文档

每个版本的文档登记为一个 Material（路径与内容哈希），可以用 `ReadEvidence` 读取、用来源引用引用其中的行。

- 文档存放在材料根目录下的 `artifacts/`，按标题与版本命名（如 `ETTh1 multivariate long-term forecasting.v4.md`），让读文件的 Agent 从文件名就能认出内容；文件名不能用的字符换成空格，过长时按字节截断。Material id 由内容哈希给出，与文件名无关。文件不进 git，版本由提交链记录。
- `FetchArtifact` 写到工作目录的文件名不带版本号，头部加 `id` 与 `base` 两行；检入时去掉这两行再保存。
- `op`、编辑者、时间不写进文档。

### 5.4 身份与幂等

- **有身份键的产物**按键收敛：新建时同键已有产物，拒绝并退回已有的那份（第 4.1 节）。不做合并：两份同键的产物不会同时存在。
- **没有身份键的产物**（`Summarize`、`Generate`）不查重。新建时内容与某份已有产物的某个版本完全相同（同一 `op`、同一编辑者），视为重试，返回已有的产物。
- **更新**按 `base` 做乐观校验：`base` 不是最新版本的提交时拒绝（`conflict`）。写者轮流执行，这种情况很少，但机制要有。
- 产物不能经 `Commit` 新建、修改或删除。删除产物（例如撤回整份）当前不提供。

### 5.5 写入

产物算子带 `confirm` 且校验通过后，经与 `Commit` 相同的版本底层（graph-vc）写入：

1. 写文档：每份新版本的文档先写临时文件再改名；内容相同的文档已有 Material 时沿用；
2. 在一个事务中：新建的产物分配 id、写节点；每份产物登记新版本的 Material，把上一版本记为 `superseded_by`，重写 `USED` 边，更新 `title`、`abs`；产生一个提交记录：`source` 为 `operator:<op>`，`author` 为 `formed_by`，`message` 为 `update_abstract`，`meta` 记各产物的 id、版本与会话、`confirm` 中的理由，`files` 记文档的路径与哈希；
3. 提交后补算 `title` 与 `abs` 的向量；失败不回滚，只在 `warnings` 中提示。

事务失败时文档文件留在原处：没有节点引用它，不影响库，重试时内容相同而直接复用。

### 5.6 检索、编辑提示与过期

- **默认不进入 Search 的结果**，见第 3.1 节；经 `Search(type=Artifact)`、沿 `USED` 的 `Traverse` 或 `Commit` 的返回（第 3.5 节）取得。
- **编辑提示**由提交链与相邻版本的比对算出，不写进文档：
  - `FetchArtifact` 给出完整的提示：版本号；最近的编辑者、提交与修改说明；各编辑者及其版本；“自你上次编辑以来别人改了哪些行”（第 3.6 节）；
  - `Search` 的结果与 `ReadEvidence` 读产物文档时，附一行：`art_0058 · v4 · last edited by writer-i3 at commit_000071 · 3 editors`。

  “自你上次编辑以来别人改了哪些行”最有用：同一个写者隔几次会话回来，马上知道自己写的东西被谁动过。
- **过期在读取时计算，不存状态。** 视图的 `_stale` 逐项列出“可能过期”的原因 `{ref, reason}`：

  | `reason` | 含义 | 状态 |
  | --- | --- | --- |
  | `document` | 当前版本的文档文件不在，或内容与登记的哈希不同 | 已实现 |
  | `removed` | 当前版本引用的对象（或记录所属的产物、来源引用的材料）已不在库中 | 已实现 |
  | `material` | 所用材料的文件不在，或哈希与登记的不同 | 已实现 |
  | `superseded` | 所用材料已被新版本取代：论文有了新版本，或所引产物有了新版本；另带 `by` | 论文已实现，产物待实现 |
  | `revised` | 所用的有据层记录在这个版本形成之后被修订过（比较之后的提交） | 待实现 |
  | `stale input` | 所用的产物本身可能过期（递归计算） | 已实现 |

  过期只是提示，不修改、不删除。产物的成本高、重算不确定，所以标记而不维护。

### 5.7 提升为长期记录

Artifact 是解释层的工作产物；Observation 是由提交者明确写入的理解。需要作为一条记录留存的判断，经 `Commit` 写成 Observation：`ABOUT` 指向该 Artifact，`FROM` 指向该 Artifact 当前版本的文档并带行范围（如 `{to: art_0003, locators: ["Results::12:20"]}`）。读取时两者分开呈现，不把 Artifact 当作已确认的结论。

## 6. 使用约定

- **按需使用。** 回答中含数值、比较或判断时使用产物算子；简单的定位与阅读问题直接用中间件算子回答。
- **先找已有的产物。** 新建之前，先经 `Search(type=Artifact)`、沿数据集或主张的 `Traverse`，或 `Commit` 的返回，看是否已有可以接着编辑的那一份。有身份键的产物，新建时撞键会被退回。
- **照着已有的写。** 格式由种子示例与已有的产物示范；工具说明写明强制的部分，其余由写者决定。
- **回答引用产物。** 最终回答中的数值、比较与判断应来自产物，每个数字都能经方括号中的引用追到行与原文。
- **任务提示不要求维护产物。** 写者是否发现并维护共同的产物，是评测的观测量（采用率），不是指令。

## 7. 典型组合

以下组合用于检查算子是否覆盖六类 intent 的使用，不是固定流程。

| Intent | 组合 |
| --- | --- |
| I1 发现适合需求的方法 | `Search(Concept, kinds={Method})` → `Traverse` 取讨论它们的主张与实验 → `ReadEvidence` → `Generate`（回答） |
| I2 理解机制与细节 | `Resolve` → `Traverse([m])` 及其 `ABOUT` 入边的 Content → `ReadEvidence` → `Summarize`（机制要点）或 `Verify`（某条说法是否成立） |
| I3 组织结果并判断可比性 | `Resolve` → `Traverse([dataset], [{rel: USED, dir: in, kinds: {Artifact}}])` 找到 Leaderboard → `FetchArtifact` → 读原文、编辑 → `Leaderboard` 检入 → `CompareSettings`（可比性）→ `Generate`（回答） |
| I4 综合同一问题下的路线 | `Search(Concept, kinds={Issue})` → `Traverse` 取 `ABOUT` 它的主张与贡献 → `ReadEvidence` → `Summarize` |
| I5 核查主张的依据 | `Search(Content, kinds={Claim})` → `Traverse`（`SUPPORTED_BY`、`SUPPORTS` / `OPPOSES`，以及 `USED` 入边上已有的 `Verify`）→ `ReadEvidence` → `Verify`（新建或编辑已有的那一份） |
| I6 取得实现资源 | `Resolve` → `Traverse`（`IMPLEMENTS` 入边，当前无数据）或 `Search(Entity, kinds={Code, Model}, query)` → `ReadEvidence` → `Generate`（地址与设置） |

入库时维护 Leaderboard 的完整过程见讨论稿 §6.1。

## 8. 本版不纳入

| 事项 | 原因与替代 |
| --- | --- |
| 预设语义的读取算子（Experiments、Evidence、Context、Implementations、Get） | 由 `Search` 的结构条件、`Traverse` 的路径与对象视图覆盖，不单列 |
| 关系检索 | 关系的 `description` 已建向量，但没有 workload 需要按关系检索；`Traverse` 返回边上的说明 |
| `Extract`（自由 schema）、`MatrixConstruct`、`Filter`、`Check` | 自由 schema 的抽取结果各写各的，无法合并，结果数值改写进 `Leaderboard`；矩阵由 `Leaderboard` 取代；身份确认由 `Commit` 的查重退回候选；`Check` 改为维度固定的 `CompareSettings`。旧版见 Git `d36aa54` |
| AgenticScholar 的 Rank、GroupBy、Aggregate 等对记录做计算的算子 | 中间件不对产物内容排序、分组或计数；排名与结论写在 `Generate` 中，可比性先经 `CompareSettings` 判断 |
| 产物的自动合并 | `base` 过期时拒绝，由写者重新 fetch 后合并 |
| 产物的删除与清理 | 当前不提供；按价值信号清理留待有真实使用数据后再定 |
| Concept 精炼与整理 | 日后增加专门的工具或算子，整理 Claim 与 Issue、Proposition 并建立正反关系 |

## 9. E09 实现对照

模块都在 `experiments/e09/src/e09/` 下。每个算子一个文件，定义一个 `Operator`（`operators/base.py`：名称、参数的 JSON Schema 与执行），按名称登记在 `operators.OPERATORS` 中。
通用 Agent 经 MCP 服务 PaperWeave（`python -m e09.mcp`）使用算子：每个算子一个工具，给模型看的文字（`instructions`、
工具的标题与说明、参数说明）都在 `mcp/server.yml`，启动时与算子的结构装配成工具；`Commit` 只在 `E09_ENABLE_COMMIT=1`
时列出。工具的每个顶层参数都声明一种确定的 JSON 类型（列表参数是数组，`query` 是对象，`Commit.doc` 是 YAML 文本），
不用 `anyOf`：按 `type` 转换参数的工具调用解析器（如 sglang 解析 qwen 的工具调用）会把只有 `anyOf` 的参数当作字符串。
算子本身仍接受单个字符串、`scope="global"` 等写法。
顶层的对象与数组参数在暴露的 schema 中也接受字符串：`Operator.call` 执行前按算子的 schema 兜底修复参数（`operators/repair.py`：JSON 文本解析并补齐末尾缺少的括号、字面量转换、枚举的大小写与 `true`/`false` 判断），来源引用的写法偏差由 `model/refs.py` 的 `normalize_ref` 兜底；修复不告诉 Agent，只记在服务日志中（stderr 与 `E09_MCP_LOG`）。命令行入口 `python -m e09`
的请求以 `op` 为算子名；直接给 graph-doc 时视为 `Commit`。两个入口经同一个 `Operator.call`，结果相同。共用的支持放在与
`operators/` 同级的包中，依赖方向为 `operators → commit、artifact、query → store、model`。

| 算子 | 模块 | 状态 |
| --- | --- | --- |
| `Search` | `operators/db/search.py` | 已实现，含 `type=Artifact` 与有据层记录的 `_revised`；产物的编辑提示待实现 |
| `Resolve` | `operators/db/resolve.py`，三级解析在 `query/resolve.py` | 已实现；`Commit` 的查重也用它 |
| `Traverse` | `operators/db/traverse.py` | 已实现，含 `USED` 与 `_revised` |
| `ReadEvidence` | `operators/db/read_evidence.py` | 已实现，可读 Artifact 文档，含 `E09_EVIDENCE_SCOPE`；编辑提示待实现 |
| `Commit` | `operators/db/commit.py`，写入管线在 `commit/` | 已实现：graph-doc → graph-plan / graph-result，经 graph-vc 提交；`doc_file`、论文新版本已实现；返回相关的共同产物待实现 |
| `FetchArtifact` | — | 待实现 |
| `Leaderboard`、`CompareSettings`、`Verify`、`Summarize`、`Generate` | — | 待实现。现有的 `operators/agent/` 是旧版的 7 个 Agent 算子（Extract、Summarize、Generate、Check、Verify、Filter、MatrixConstruct，写入后不可修改），新算子实现后替换；`Summarize`、`Generate`、`Verify` 的引用校验可沿用 |

| 支持 | 模块 |
| --- | --- |
| 结构条件、RRF 融合、读视图与只读字段、Search 的结果视图、固定材料 | `query/conditions.py`、`query/fusion.py`、`query/view.py`、`query/excerpts.py`、`query/materials.py` |
| Artifact 的文档格式、共同写入路径、可能过期 | `artifact/document.py`、`artifact/write.py`、`artifact/stale.py`（版本、编辑提示与 `revised` 待实现） |
| 草稿文件的路径、解析与报错行号 | `draft.py` |
| 数据模型、引用写法、名称精确键 | `model/schema.py`、`model/refs.py`、`model/namekey.py` |
| 算子环境、库的版本记录与约束索引、连接、向量 | `store/store.py`、`store/database.py`、`store/graph.py`、`store/embedding.py` |

测试在 `experiments/e09/tests/operators/db/` 与 `tests/operators/agent/`，只在空的测试实例（`GRAPH_VC_TEST_NEO4J_URI`）上运行；写入管线的测试在 `tests/commit/`。

**参考：** [S] Hai Lan et al. *AgenticScholar: Agentic Data Management with Pipeline Orchestration for Scholarly Corpora.* PACMMOD 4(2), Article 131, 2026（本地精读见 `references/papers/2026-AgenticScholar-reread/`）。旧版的 Agent 算子名称沿用自 [S]（Table 2 与 Appendix D）。
