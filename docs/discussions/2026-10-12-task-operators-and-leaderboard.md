# 面向任务的可注入算子与 Leaderboard

> **状态：** 2026-10-12 讨论稿。方向已与用户商定：
> - Agent 算子改为面向任务、可注入；
> - 以 PapersWithCode 与评测任务为目标设计算子；
> - Generate 保留，Filter 与 MatrixConstruct 去掉。
>
> 细节为提议，未改代码与设计文档。叙事见 `paper/narrative-draft.md` 的 2026-10-12 修订。

## 1. 起因

pilot-2 暴露的问题：A3 的结构化收益很低，结构化的内容没有合成出任何东西。直接原因是 `Extract` 的 schema 由每次调用自带：

- 写者各自决定字段名、粒度与设置的写法；
- 同一篇论文的结果，在不同产物里是互不相同的表；
- 产物之间无法 join，读者只能逐份去读文档。

用户的判断：值得结构化的东西，结构化之后应当能直接合成 PapersWithCode 那样的表格，这才是结构化的收益。

## 2. 定位：通用核心与面向任务的算子层

| | 通用核心 | 面向任务的算子层 |
| --- | --- | --- |
| 内容 | Entity / Concept / Content / Artifact；写入机制（统一提交、身份候选、修订、陈旧）；产物契约 | 一组算子声明，每份声明规定一类产物的参数、内容与正文 |
| 由谁决定 | 本文的设计 | workload：PapersWithCode 的数据形态与评测任务 |
| 是否随任务变化 | 否 | 是，按需注入 |

**叙事上的落点：**

- 意图 I1–I6 对系统有两方面的作用：读侧决定检索面，写侧决定要注入哪些算子。“面向任务优化”落在算子层，核心不为任务做特化。
- 草稿中已经写了“操作清单不是贡献”。注入化让这一点在结构上成立：贡献是**任何算子都必须满足的产物契约**，具体有哪些算子只是配置。

**经典对应：**

- dataspaces 的按需整合（pay-as-you-go）：不预先定全局 schema，workload 需要时再给某类产物加 schema；
- 可扩展 DBMS 的用户自定义函数：系统规定契约，语义由注入者负责。

后者与责任边界一致：算子的语义工作由外部 Agent 完成，中间件只按声明做通用校验与持久化。

**收益不在“灵活”，在“schema 被共享”。** schema 从每次调用移到算子声明里，同一算子的所有产物数据块就同构，不同写者的产物才能合在一起用。

## 3. 算子声明

### 3.1 现状离它多远

`operators.md` §4.1 已经是一个通用契约：

```text
<Op>(title?, abs, inputs, params, payload)
```

共同校验已经通用，包括：

- `inputs` 中的引用存在；
- `params` 与 `payload` 中的引用都被 `inputs` 覆盖；
- 判断的取值规则。

§5 的 Artifact 也是通用的：有 `op` 属性、`USED` 边、文档与 `_stale`。

在 `operators/agent/*.py` 中按算子写死的只有三样：

1. `params` / `payload` 的 schema；
2. 少量专用校验（判断覆盖每个单元、Summarize 的段落须有引用）；
3. 正文怎样渲染、有没有数据块。

可注入就是把这三样移进声明，中间件用一个通用的校验与渲染路径处理所有算子。

### 3.2 声明的内容

| 内容 | 作用 |
| --- | --- |
| `name`、给 Agent 看的说明 | 注入后自动出现在 MCP 工具列表中，说明进入工具描述 |
| `params` / `payload` 的 schema | 字段类型沿用 Extract 的 `string`、`number`、`integer`、`boolean`、`enum[...]`、`ref`，`ref` 可以限定类型，如 `ref[Method]` |
| 记录键 | 决定一条记录的字段；记录可以用 `<artifact>#<key>` 引用 |
| 可选的专用规则 | 只从一个固定的小集合中选：判断覆盖（每个单元恰有一条 `T` / `F` / `U`）、段落引用（每段至少一处引用） |
| 正文模板与数据块 | 可读的正文；需要被下游读取的算子在正文末尾附数据块 |
| 版本 | 声明内容的哈希，写进 Artifact |

声明不允许携带代码，专用规则只能从固定集合中选。这样中间件的校验是封闭的、可测试的，注入的只是数据。

**带类型的引用是 join 的前提。** `ref[Method]` 要求引用解析到 Method 节点，否则整次拒绝。两个写者对同一方法写了同一个 id，它们的产物才能对上。

### 3.3 Artifact 上的记录

- 保留 `op` 属性，新增 `op_version`（声明的哈希）。声明改了，旧产物仍能知道自己按哪一版生成。`op_version` 是新字段，突破模型冻结，需要用户同意。
- 不用 `Artifact:<op>` 二级标签。现有的二级标签只用于封闭词表（Entity、Concept 的 kind）；注入的算子名是开放集合，做成标签会让标签无限增长。按 `op` 过滤与按标签查询，能力相同。

### 3.4 谁来注入

由人注入：声明放在实验配置中，服务启动时装配，与 `server.yml` 的做法相同。Agent 不能在运行时注册算子。理由：

- 可复现；
- 各组的评测条件可控；
- 算子不会膨胀。

将来的公共平台可以再开放。

## 4. 算子集合

| 算子 | 处理 | 服务的意图与评测 |
| --- | --- | --- |
| `ExtractResults` | 由 Extract 改造：schema 固定在声明中（第 5 节） | I3；PapersWithCode 的结果行；E1 的转录忠实度 |
| `Leaderboard` | **新增**，内置的只读 db 算子，不是注入的 Agent 算子（第 6 节） | I3；E2 |
| `Check` | 保留，改写为声明 | I3 判断可比性 |
| `Verify` | 保留，改写为声明 | I5 核查主张 |
| `Summarize` | 保留，改写为声明（段落引用规则） | I4 忠实压缩 |
| `Generate` | 保留，改写为声明 | 撰写类任务，用 LLM judge 评 |
| `Filter` | 去掉 | 身份确认已由 Commit 的 dry_run 退回候选 |
| `MatrixConstruct` | 去掉 | 结果矩阵由 Leaderboard 取代，其他矩阵在 workload 中很少用到 |

**通用的 Extract 是否保留：** 我的提议是不保留自由 schema 的 Extract，只保留面向任务的抽取声明，目前只有 `ExtractResults`。workload 需要别的抽取（例如实验设置、资源地址）时，再注入新的声明。自由 schema 的 Extract 正是产物无法 join 的原因。

**Generate 与混合标准：**

- 能对照来源核对的部分（结果数值、主张）用自动判分，以原文锚点与 PwC 为准；
- 撰写类产出用 LLM judge 按 rubric 评。

Generate 现在允许段落不带引用，只在 `stats` 中报告引用比例。若用它的产出评撰写质量，judge 应同时看到引用，以便分开评“写得好不好”与“说的是否有出处”。是否收紧约束，留到改算子时定。

## 5. ExtractResults

**用途：** 把论文结果表中的数值转录成结果行，一行对应 PapersWithCode 评测表中的一个格子，另带设置与原文出处。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `method` | `ref[Method]` 或 `ref[Model]` | 被评测的方法 |
| `dataset` | `ref[Dataset]` | 评测数据 |
| `task` | `ref[Task]`，可选 | 缺省时按 `dataset` 的 `FOR_TASK` 推出 |
| `role` | `enum[target, baseline]` | 该论文提出的方法，还是对比的基线 |
| `origin` | `enum[run, copied, unknown]` | 该论文自己跑的，还是转录自其他论文（如 SCINet 的部分基线数值转录自 Informer） |
| 设置字段 | 由领域实例声明 | LTSF：`pred_len`（`integer`）、`lookback`（`integer`，可选）、`variate`（`enum[multivariate, univariate]`） |
| `metric` | `enum[...]`，由领域实例声明 | LTSF：`MSE`、`MAE` 等 |
| `value` | `number` | 原文数值，不换算 |
| `source` | 来源引用 | 结果表中这一格所在的行 |

- **论文**不作为字段：由 `source` 所指的材料推出，避免写错。
- **记录键：** `method`、`dataset`、设置字段、`metric`。
- **设置字段与度量是领域实例的一部分。** 模型冻结下没有 Metric 类型，归一化放在声明的枚举里。这与“领域词表是参数”的立场一致：换领域时换这份声明，不改模型。
- **粒度：** 一份产物转录一篇论文的一张或几张表，由写者决定；Leaderboard 对所有产物取并集。
- **不做的事：** 不换算单位，不跨设置合并，不补原文没有的值。

## 6. Leaderboard

**定位：** 内置的只读 db 算子，与 Search、Traverse 并列。它不需要 LLM，结果是确定的，在读取时计算。每次读取都现算，所以永远不会陈旧，是“可维护的视图”最简单的形态（虚视图）。

```text
Leaderboard(dataset, metric, task?, setting?, at?)
  -> {rows: [{method, cells: {<setting>: [value_entry, ...]}}], flags, sources}
value_entry = {value, paper, role, origin, artifact, formed_by, source}
```

- **分组：** 按（任务、数据集、度量）成表，行是方法，列是设置。数据来自当前状态（或 `at` 指定的历史状态）下所有 `ExtractResults` 产物的数据块。
- **每一格可能有多个值，各带出处：** 哪篇论文报告、哪份产物转录、谁转录、原文哪一行。
- **两种分歧要分开标出：**
  - **同一篇论文、同一格，转录出不同的值：** 至少一份转录错了。属于“论文所说”的分歧，回原文锚点可以裁决。
  - **不同论文对同一方法报告了不同的值：** 例如自己跑的与转录来的，或不同的重跑。这是正常的并存，不是错误。
- **过时提示：** 所引材料已被新版本取代（`superseded`）、产物的输入已变（`_stale`）时，相应的值带标记。
- **排序：** 按度量的方向排序（MSE 越低越好，方向写在度量的声明里）。这只是排序，不是库对“谁对”的裁决。
- **不存储结果。** 读者需要引用一张表时，引用其中的 `ExtractResults` 记录。

**身份质量直接决定表格质量。** 同一方法被建成两个节点，表上就裂成两行。由此得到 E1 的一个直观指标：表格碎片化程度（同一方法占了几行），把 C1 与下游效果连起来。

## 7. 银标准：PapersWithCode

本地已有 PwC 归档快照（`pwc-archive/evaluation-tables`，`data/raw/t1-pilot-corpus/pwc/`），选语料时已经用过，见 `docs/decisions/2026-10-10-t1-pilot-corpus.md` §3。

先导语料的覆盖情况，按论文标题正则粗查（一次性核对，未留脚本）：

| 论文 | PwC 榜单数（数据集 × 设置） |
| --- | --- |
| Informer | 20 |
| SCINet | 20 |
| Query Selector | 22 |
| FiLM | 16 |
| PatchTST | 24 |
| TiDE | 8 |
| UniTime | 1 |
| TimeMachine | 1 |
| CATS | 0 |
| Autoformer | 未定：标题正则混入了视觉领域的 AutoFormer，需要精确匹配 |

由此得到几点：

- **覆盖不均：** 10 篇中 7 篇有可用的条目，UniTime、TimeMachine 只有一格，CATS 没有。探针从 PwC 抽取时要按论文分层（选语料时已定）。
- **PwC 把设置编码在数据集名里：** 如 `ETTh1 (336) Multivariate`。对照时要把它拆成 `dataset`、`pred_len`、`variate`。这个拆分本身就是 C1 的一个现成例子：人工维护的平台把设置和身份混在一起。
- **`ExtractResults` 的字段覆盖了 PwC 一行的内容**（模型、论文、数据集、度量值），另外多出两样：设置的分解，以及原文锚点。银标准只用来对照，分歧回原文锚点裁决（三方核对，见语料决策）。

## 8. 与评测的关系

- **E1 完整性：**
  - `ExtractResults` 的每一行都可以按 `source` 对照原文核查，转录忠实度直接可测。这也补上了先前的一个缺口：Observation 文本中的数值不在健康度统计里，与 A0 不对称。
  - 表格碎片化程度作为身份质量的下游指标。
- **E2 充分性：** I3 的探针可以经 Leaderboard 回答。`store_only` 与 `with_papers` 的差距直接反映结果行的覆盖。
- **E3 对等：** 混合标准，数值与主张自动判分，Generate 的撰写产出由 LLM judge 评。
- **A0 的对等性：** 按“强基线、同等条件”的原则，A0 的写者也应拿到同一份结果行 schema，作为笔记约定（例如一个 YAML 模板）。这样两组的差别只在：引用是否被强制解析到唯一身份、有没有 Leaderboard。我建议这样做；否则 A3 的优势里混进了“A3 有 schema、A0 没有”。

## 9. 影响

- **pilot-2 与 r2 的数据降为探索性：** A3 的 MCP 工具列表变了。
- **模型冻结：** `op_version` 是新字段；`ExtractResults` 不改模型；Leaderboard 是新的读算子，不改模型。
- **之后需要同步的文档与代码（等本稿定了再动）：**
  - `operators.md` §4（含删去 §4.7 Filter、§4.8 MatrixConstruct，以及 Generate 一节中对 MatrixConstruct 的引用）与 §5；
  - `server.yml`；
  - `operators/agent/` 的实现与测试；
  - 叙事草稿相关工作一节中提到 MatrixConstruct 的一句。
- **代码量：** 五个算子文件合并为一个通用的校验与渲染路径，加上声明文件；Leaderboard 是一个新的 db 算子。

## 10. 待定，各附我的建议

1. **结果行是产物，还是“论文所说”的 Content？**
   - 本稿按产物处理：只追加，不同写者的转录并存，Leaderboard 标出同一格的分歧，读者可以用一次 ReadEvidence 回原文核对。
   - 另一种做法是把结果行升格为“论文所说”的 Content：单值，带锚点修订。这需要新增 Content 类型，突破冻结。
   - **建议：** 先按产物做，看先导中同一格的转录分歧有多频繁，再决定。
2. **A0 是否拿到同一份 schema。** 建议给，理由见第 8 节。
3. **`op_version` 是否加。** 建议加。没有它，声明一旦修改，产物的来源就说不清。
4. **Generate 是否要求每段带引用。** 建议先不收紧，在 LLM judge 的 rubric 里单列“出处”一项。
