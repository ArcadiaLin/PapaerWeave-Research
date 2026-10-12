# 面向任务的产物算子与共同维护的 Leaderboard

> **状态：** 2026-10-12 讨论稿，汇总当天几轮讨论的结论，已与用户商定；具体格式与校验清单待下一轮。未改代码与设计文档。
> 叙事见 `paper/narrative-draft.md` 的 2026-10-12 修订。前两版（只读的 Leaderboard 视图 + `ExtractResults`、
> 强制的算子声明）见 Git `ed1004e`、`037908b`，已被本稿取代。
>
> **已定：**
> - 产物算子面向任务设计，以 PapersWithCode 与评测任务为目标；Generate 保留，Filter、MatrixConstruct 去掉。
> - 产物是**有版本、可共同编辑的文档**，不再“写入后不可修改”；所有产物都允许他人编辑。
> - 修改他人写的内容须写理由；引入新证据时附上引用，不强制每次都带锚点。
> - fetch 与读取时返回最近的编辑者与他人改动之处，作为提示。
> - 核心算子新增 `FetchArtifact`。
> - schema 由种子示例、工具说明与轻度校验引导，不强制按格式提交。
> - 种子状态中放一组种子 leaderboard；A0 也拿到这些文件，但不给任何“要求统一维护”的提示。
> - 加 `op_version`；Generate 不要求每段带引用。
> - 测试按论文入库顺序，随机分给 3–4 个伪用户，由他们自行维护库。
> - **原则：只在系统要用到的地方要求结构，其余一律自由（2.1）。**
>
> **同日后续推演（一次 pi 会话怎样维护 leaderboard，见 6.1）带出、已商定写入本稿的：**
> - 每类产物有自己的身份键，同一个键只有一份产物（3.7）；
> - Commit 的返回列出这次提交涉及的对象上挂着的共同产物（4.2）；
> - 产物的检入先给出校验结果、不写入，确认后才写（3.3）；
> - `FetchArtifact` 一次可取多份，检入一次可交多份（4.1、3.3）；
> - 键字段按字符串比较，允许说明文字（6）。

## 1. 起因

pilot-2 暴露的问题：A3 的结构化收益很低，结构化的内容没有合成出任何东西。直接原因是 `Extract` 的 schema 由每次调用自带：

- 写者各自决定字段名、粒度与设置的写法；
- 同一篇论文的结果，在不同产物里是互不相同的表；
- 产物之间无法合并，读者只能逐份去读文档。

用户的判断：值得结构化的东西，结构化之后应当能直接合成 PapersWithCode 那样的表格，这才是结构化的收益。进一步的判断：像 leaderboard 这样的表，本来就需要不同来源的 Agent 共同维护同一份产物，而不是各写一份再由系统拼起来。

## 2. 定位

| | 通用核心 | 面向任务的产物层 |
| --- | --- | --- |
| 内容 | Entity / Concept / Content / Artifact；写入机制（统一提交、身份候选、修订、陈旧）；产物的版本与编辑规则 | 一组产物算子，每个算子对应一类产物：它的文档长什么样、做哪些轻度校验 |
| 由谁决定 | 本文的设计 | workload：PapersWithCode 的数据形态与评测任务 |
| 是否随任务变化 | 否 | 是 |

**叙事上的落点：**

- 意图 I1–I6 对系统有两方面的作用：读侧决定检索面，写侧决定有哪些产物算子。“面向任务优化”落在产物层，核心不为任务做特化。
- “操作清单不是贡献”在结构上成立。贡献是两样：
  - 产物的版本与编辑规则；
  - 让不协调的写者共同维护同一份产物的机制。

  具体有哪些算子只是配置。

### 2.1 原则：灵活，但不完全灵活

如果格式完全自由，一个通用的“编辑产物”算子就够了。这个通用算子其实已经存在，就是 `generate`：系统对它的内容几乎不做任何处理，所以它几乎完全自由，只校验引用是否存在。其他类型之所以单独成为算子，是因为系统要对它们的某些部分**做事**，而这些事只有知道结构才做得了。

> **只在系统要用到的地方要求结构，其余一律自由。** 每一个被强制的部分，都必须能说出是哪个机制在消费它；说不出来，就不该强制。

由此得到三条判断标准：

1. **什么时候该加一种产物类型：** 能说出一个机制要消费它的结构；说不出来，就用 `generate`。类型因此不会无限增长，这也回答了“为什么是这几个算子”。
2. **每种类型强制到什么程度：** 恰好是那些机制要用的部分，不多也不少（各类的清单见第 5、6 节）。
3. **对 pi 来说：** 工具说明里明确写出“系统会检查这几项，其余随你”。写者知道哪里不能马虎、哪里可以自由发挥。

系统消费的结构只有三种：

- 让写者收敛到同一份产物的**键**；
- 把产物连进图中的**引用**；
- 让其中的陈述可以核对的**锚点**。

```text
Artifacts are free-form documents, except for the parts the store acts on:
the keys that make writers converge on one artifact, the references that
link it into the graph, and the anchors that let its claims be checked.
```

数据库中的对应：半结构化存储里，只把要建索引、要加约束的字段提出来做列，其余留在文档里。也就是写入时只为少数字段定 schema，其余到读取时再解释。

### 2.2 经典对应

- **dataspaces 的按需整合（pay-as-you-go）：** 不预先定全局 schema，而是用种子示例引导格式，格式随使用逐步收敛；
- **check-out / check-in 与乐观校验：** `FetchArtifact` 取工作副本，检入时核对基础版本。C4 一直“已设计、未实现”，这是它在单个产物上的第一个落点；
- **版本化文档与逐行归属：** 类似 `git blame`，归属由相邻版本比对得出，不写进文档。

## 3. 产物：有版本、可共同编辑的文档

### 3.1 从“写入后不可修改”改为“有版本的文档”

`operators.md` §5.4 的“写入后不修改”来自溯源模型 OPM 对 Artifact 的定义（过程产出的不可变状态），但这走错了：一份 leaderboard 若只能由一个人维护，多写者共同积累就无从谈起。

现在的定义是：**每个版本不可变，产物本身可以演进。** 现有机制几乎不用动：

| 需要的能力 | 怎样实现 |
| --- | --- |
| 版本 | 每个版本的文档登记为一个新的 Material（带内容哈希），旧的保留；产物节点 id 不变，每次检入是一次提交 |
| 引用固定到版本 | 其他产物经 `USED` 引用它时，边上已有的 `material_ref` 天然固定在某个版本 |
| 输入已修订 | `_stale` 扩展一条：所引版本之后已有更新的版本。与论文换版本的 `superseded` 同一逻辑 |
| 谁改了哪里 | 由相邻版本逐行比对得出，不写进文档、不加模型字段 |
| 回到任一历史状态 | 按提交取对应版本的 Material |

Artifact 节点不加字段（`op_version` 除外，见 3.5），版本走提交链。

### 3.2 统一的编辑规则（所有产物）

- 任何人都可以 fetch、编辑、检入；
- 改动他人写的内容，`update_abstract` 中须写理由；用了新证据就附上引用，不强制；
- 改自己写的内容不受限制；
- 每次检入是一个新版本，旧版本全部保留；
- 检入时核对基础版本：中间已有他人更新，就拒绝并提示重新 fetch 后合并；不做自动合并。写者轮流执行，这种情况很少，但机制要有。

“自己写的”与“他人写的”按行判断，由版本比对得出。这需要定义**行的键**，否则分不清“改了一行”与“删了一行、加了一行”。各类产物的行键在格式中规定（第 6 节给出 leaderboard 的）。

### 3.3 统一的写入签名

```text
<op>(artifact_doc | [artifact_doc, ...], update_abstract, confirm?)
```

- `artifact_doc`：工作目录中的文档路径，可以一次交多份。每份各自校验，各成一个版本。头部带 `id` 与 `base` 时是更新，不带时是新建；
- **先校验、后写入：** 不带 `confirm` 时只校验、返回结果与警告，不写入；带 `confirm: true` 再写。与 Commit 的 dry_run → confirm 相同。这样，警告在写入前就给出来，不会为了改一个笔误多出一个版本；
- `update_abstract`：这次改了什么、为什么。它进入提交的 `message`，也作为编辑提示显示给后来者；
- 文档头部的 `title`、`abs` 仍作为检索文本。

### 3.4 轻度校验

只拦会破坏库的东西，其余只警告。按类别分：

| 情况 | 处理 |
| --- | --- |
| 头部的 `id`、`base` 被改，或 `base` 不是最新版本 | 拒绝 |
| 新建的产物，其身份键已有一份产物（3.7） | 拒绝，返回已有那份的 id，让写者去 fetch 它 |
| 文档中出现的对象 id、产物 id 不在库中 | 拒绝 |
| 来源引用格式错误、所指材料不存在或行号越界 | 拒绝 |
| 改动或删除了他人写的行，但 `update_abstract` 没有理由 | 拒绝 |
| 各类产物自己的轻度规则（如 leaderboard 的新行须带出处） | 拒绝，见第 6 节 |
| 数字没有出现在所引的那一行 | 警告 |
| 文档结构与种子示例不同（缺列、多列），或某列的写法与示例不同（例如该写数字的地方写了文字） | 警告，并给出示例的写法 |

“数字是否出现在所引的那一行”是确定性检查，不需要 LLM，能抓住大部分抄错。

### 3.5 `op_version`

记录这类产物当时的工具说明与校验规则的哈希。说明或规则改了，旧版本仍能知道自己是在哪套规则下写入的。它是新字段，用户已同意。

### 3.6 编辑提示：pi 看到什么

fetch 时：

```text
FetchArtifact(artifact: art_0058)
→ wrote ./artifacts/TiDE vs PatchTST comparability.md
  art_0058 · version 4 · last edited by writer-i3 (commit_000071): "Mark TiDE look-back as 720 per Sec. 4.1 [2304.08424v5 l.223]"
  editors: writer-i2 (v1 created, v2) · writer-i1 (v3) · writer-i3 (v4)
  changed by others since your last edit (v2): lines 12–14 (writer-i3), line 20 (writer-i1)
  To change it: edit the file, then call compare_settings(artifact_doc, update_abstract). Do not edit the id and base lines.
```

Search 结果与 ReadEvidence 读产物时，附一行：

```text
art_0058 · v4 · last edited by writer-i3 at commit_000071 · 3 editors
```

“自你上次编辑以来，别人改了哪些行”最有用：同一个伪用户隔几次会话回来，马上知道自己写的东西被谁动过。

### 3.7 产物自己的身份

共同维护的前提，是写者收敛到**同一份**产物上。如果每个写者各建一张“ETTh1 结果表”，C1 的问题就在产物这一层重演。所以每类产物有自己的身份键：

| 产物 | 身份键 |
| --- | --- |
| `leaderboard` | （任务、数据集、设置），如（长期预测、ETTh1、多变量） |
| `compare_settings` | 被比较的两项 |
| `verify` | 被核查的主张 |
| `summarize`、`generate` | 无：每次新建都是一份新的产物 |

新建时如果同键已有产物，就像 Commit 的 dry_run 退回身份候选一样，把已有的那份退回给写者。键由头部的字段算出，按字符串规范化后比较，不做模糊匹配。

## 4. 核心算子的改动

与 Search、Traverse、ReadEvidence 并列。

### 4.1 FetchArtifact

```text
FetchArtifact(artifact | [artifact, ...], at?)
→ 把产物的文档（或 at 指定提交时的版本）写到工作目录的 ./artifacts/<标题>.md，返回版本与编辑提示（3.6）
```

一次可以取多份：一篇论文往往涉及 7–8 张 leaderboard，逐张取的调用开销太大。

文件头部多两行，供检入时核对：

```markdown
---
id: art_0003
base: commit_000057
title: ETTh1 multivariate long-term forecasting
...
```

它顺带解决两个问题：

- **读者读长文档：** 现在读者只能用 ReadEvidence 按行号范围一段段读产物文档。Fetch 把整份文档放进工作目录，读者可以直接 grep。它只取产物文档、不取论文，所以在 `store_only` 读者条件下也可用。
- **看历史版本：** `at` 取当时的版本，对应 G 类版本事件的探针。

### 4.2 Commit 返回相关的共同产物

任务提示里不要求写者维护 leaderboard（第 8 节）。引导来自两处：工具说明，以及库在写入时的返回。Commit 确认后，返回这次提交涉及的对象上挂着哪些共同产物：

```text
committed commit_000057: +1 Paper, +3 Method, +3 Experiment, +4 Claim, +29 relations
  Shared artifacts on objects this commit touches:
    leaderboard art_0003 "ETTh1 multivariate long-term forecasting" — v3, last edited by bob (commit_000041)
    leaderboard art_0004 "ETTh2 multivariate long-term forecasting" — v2, seed
    ... 7 leaderboards in all (datasets used by exp_0031)
    no leaderboard yet for: ILI
```

它不是提示词里的要求，而是库的一个查询结果：沿“实验 → 用到的数据集 → 该数据集上的 leaderboard”查出来。这是 C5（找得到）在写入时的落点。A0 没有这个返回，写者只能自己发现仓库里有哪些表。它直接影响“采用率”这个观测量。

## 5. 算子集合

| 算子 | 产物 | 服务的意图与探针 |
| --- | --- | --- |
| `leaderboard` | 共同维护的结果表：某任务、某数据集、某设置下各方法的数值，按论文与设置分行 | I3；A、B、C、E1、G 类探针；PapersWithCode 的评测表 |
| `compare_settings` | 可比性判断：两组结果在 look-back、数据切分、归一化、训练数据、评测协议等方面是否一致 | I3；C、E2 类探针 |
| `verify` | 一条主张在给定证据下是否成立、在什么范围内成立 | I2、I5；D2、D3 |
| `summarize` | 忠实压缩多份材料或记录，段落须有引用 | I4 |
| `generate` | 最灵活的产物：回答、草稿、点子、方案；不要求每段带引用 | 撰写类任务，用 LLM judge 评 |

按 2.1 的原则，各类产物强制的部分很少，每一项都有机制在用：

| 产物 | 强制的部分 | 用它的机制 |
| --- | --- | --- |
| `leaderboard` | 身份键、行键、id 引用、每个数值的出处 | 见第 6 节 |
| `compare_settings` | 被比较的两项（指向 leaderboard 的行）、维度、结论、依据 | 读取 leaderboard 时把可比性判断挂到对应的格子上 |
| `verify` | 被核查的主张（引用）、结论、依据 | 从 Claim 节点出发能看到对它的核查结论 |
| `summarize` | 每段至少一处引用 | 忠实压缩的检查 |
| `generate` | 只有“引用必须存在” | 无，所以最自由 |

去掉：

- **`Filter`：** 身份确认已由 Commit 的 dry_run 退回候选；
- **`MatrixConstruct`：** 结果矩阵由 leaderboard 取代；
- **自由 schema 的 `Extract`：** 结果直接写进 leaderboard。它正是产物无法合并的原因；
- **`Check`：** 改为 `compare_settings`。维度由种子示例给出（look-back、切分、归一化、训练数据、评测协议，另留其他），不再每次自定，这样不同写者的判断能对到同一处。

**混合标准：**

- 能对照来源核对的部分（结果数值、主张）用自动判分，以原文锚点与 PwC 为准；
- 撰写类产出用 LLM judge 按 rubric 评，rubric 中单列“出处”一项，与“写得好不好”分开评。

## 6. leaderboard 的文档

一份 leaderboard 对应（任务、数据集、设置），例如“ETTh1 多变量长期预测”，跨论文、跨预测长度。格式草案如下（下一轮细化）：

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
| ... |

## Papers covered

| paper | tables | complete | note |
| --- | --- | --- | --- |
| paper_0001 Informer | Table 1 (material_a1::4.2::112:140) | yes | horizons 24, 48, 168, 336, 720 |
```

- **列：**
  - `variant` 记变体或配置名（如 `PatchTST/64`），模型里变体不建节点；
  - `role` 区分论文提出的方法与基线；
  - `origin` 区分论文自己跑的与转录他文的，转录的在 `source` 之外可附说明来历的那一行。
- **强制的部分，以及各自被哪个机制用到：**

  | 强制的部分 | 用它的机制 | 不强制会怎样 |
  | --- | --- | --- |
  | 头部的（任务、数据集、设置） | 产物的身份键（3.7）：一个键只有一张表 | 每个写者各建一张表，共同维护不会发生 |
  | 头部的 id 引用（task、dataset） | 图中的连接：从数据集节点 Traverse 能找到它的 leaderboard；Commit 返回相关产物（4.2） | 只能靠全文搜索碰运气 |
  | 行键：方法、变体、论文、预测长度、look-back | 逐行归属与编辑规则；“同一篇论文的同一格出现两个值”的判断 | 按文本行比对，分不清改了一行还是删一行加一行 |
  | 方法、论文写成 id | 表格碎片化指标；读取时把同一方法的行聚到一起 | 同一方法有几种写法，没人知道 |
  | 每个数值带 `source` | “数字在不在所引那一行”的检查；所引论文换版本时的 `superseded` 附注 | 两者都做不了 |

  多加的列（备注、硬件、运行次数）、表外的段落与说明文字都不强制。
- **键字段按字符串比较，允许说明文字。** 例如 PatchTST 论文中的基线是“在六种 look-back 下重跑、取最好的结果”（`2211.14730v2` 第 569 行），`lookback` 就写不成一个数。这种写法只警告、不拒绝，含义写在“Papers covered”的说明里。种子示例里应放一行这种情况，让写者知道可以这样写。
- **“Papers covered”** 记录每篇论文转录了哪些表、是否转录完整。这样“论文没有报告这一格”与“没人转录这一格”可以区分（探针 A3）。
- **自己的轻度规则：** 新增的行须带 `source`，且 `source` 落在该行 `paper` 的材料中；度量列须为数字。
- **读取时现算的附注**（不写进文档）：

  ```text
  --- computed at read (not part of the document) ---
  rows by contributor: writer-i3 (seed) · writer-i2 (+48, commit_000057) · ...
  superseded sources: 4 rows cite FiLM v3; v4 exists (commit_000090) — rows 61–64
  cells with several values: PatchTST/64 · 96 · MSE: 0.370 (PatchTST paper) / 0.379 (TiDE paper)
  ```

  其中要分开两种情况：
  - 同一篇论文的同一格出现不同值：说明有人抄错了；
  - 不同论文对同一方法报告不同值：正常并存。
- **消融表：** 是同样写进 leaderboard（加一列 `table: main | ablation`），还是每篇论文另建一份结果表，待定。

**身份质量直接决定表格质量。** 同一方法被建成两个节点，表上就裂成两组行。由此得到 E1 的一个直观指标：表格碎片化程度。

### 6.1 一次会话中的维护过程

以伪用户 alice（背景为 I3“做基准对比”）入库 PatchTST 为例。以下 id 与工具返回的文字都是示意，数值取自原文。

**会话开始时的状态：**

- 种子：Informer、SCINet，以及按数据集分的种子 leaderboard（ETTh1、ETTh2、ETTm1、ETTm2、Electricity、Traffic、Weather），每张只有这两篇论文的行；
- bob 之前入库了 Autoformer，并往这些表里加了 Autoformer 自己报告的行；
- alice 的任务提示只有工作背景，加一句“把这篇论文加入你的工作所用的知识库”，**不提 leaderboard**。

| 步骤 | alice 做什么 | 看到什么、要判断什么 |
| --- | --- | --- |
| 1 | 读论文的方法与实验部分 | ReadEvidence 读几段，或在工作目录里 grep 论文文件 |
| 2 | 写入库草稿：Paper、Method PatchTST、主结果的 Experiment（`EVALUATES` 指向 PatchTST 与六个基线）、几条 Claim；调用 Commit | dry_run 退回需要判断的身份：PatchTST、Pyraformer、LogTrans 无匹配，将新建；Weather 精确匹配 `dataset_0005`，复用还是声明不同。确认后写入 |
| 3 | 看 Commit 的返回 | 返回列出这次提交涉及的数据集上挂着的 7 张 leaderboard，以及“ILI 还没有表”（4.2）。这是 alice 发现共同的表的地方 |
| 4 | `FetchArtifact` 取这 7 张表 | 每张写到 `./artifacts/`，返回版本与编辑者，例如 ETTh1 那张：v3，bob 最后编辑，“你之前没有编辑过它” |
| 5 | 用 `cat` 读文件 | 从种子与 bob 的行中看出列和写法（方法写 id 加名字、`source` 写成来源引用），以及已经有谁、转录到什么程度：Autoformer 的表已完整转录，其中没有 96 步 |
| 6 | 读 PatchTST 的 Table 3（第 168–203 行）与说明设置的两处（第 164、569 行） | 需要它判断的都在这里：PatchTST/64 用 $L=512$、PatchTST/42 用 $L=336$，所以变体分开写；FEDformer、Autoformer、Informer 是作者在六种 look-back 下重跑后取最好的，所以 `origin` 是 `run`，`lookback` 写说明文字；DLinear 用默认的 336；Autoformer 在 ETTh1 上的值与 Autoformer 自己的论文不同，这是不同论文的不同结果，照写 |
| 7 | 编辑文件：每张表追加对应数据集 4 个预测长度 × 8 个方法的行，“Papers covered”加一行 | Pyraformer、LogTrans 用第 2 步新建的 id |
| 8 | 一次提交 7 份文档，不带 `confirm` | 返回每份的改动（ETTh1：+32 行，未动他人的行）、校验结果与警告。例如：“第 47 行 FEDformer、336、MSE 0.445：第 190 行没有 0.445（该行是 0.444）”；“`lookback` 列写了文字，种子行是数字：允许，请在 Papers covered 中说明” |
| 9 | 改正笔误，带 `confirm: true` 再交 | 7 张表各成一个新版本。返回读取时现算的附注，例如“Autoformer 在 96–720 步的 4 格现在有两篇论文的值” |
| 10 | 新建 ILI 的表：头部不写 `id`，照已有的表写 | 校验身份键（长期预测、ILI、多变量）：没有已有的表，确认后新建。若别人刚建过，返回那张表的 id，让 alice 去 fetch 它 |

**之后别人看到什么：** 一周后 bob 入库 TiDE，fetch ETTh1 这张表，看到“v4，alice 最后编辑：Add PatchTST/64, PatchTST/42 and six baselines …；自你上次编辑（v3）以来，第 49–80 行由 alice 新增，Papers covered 新增一行”。

**调用开销：** 入库本身约 5–10 次调用。leaderboard 部分，因为可以一次取多份、一次交多份，约 4 次调用加上读文件与编辑，不再随表的数量成倍增加。

## 7. 种子

- 种子状态中放一组种子 leaderboard，只含种子论文（Informer、SCINet）的行，覆盖语料中的主要数据集。探针本来就避开种子论文，所以不与金标准重叠。
- **A0 也拿到这些文件：** 作为仓库里的 Markdown 文件，与其他种子相同。但不给任何“要求统一维护”的提示。A0 的写者怎么用这些文件，由它们自己决定。
- A3 的用法照例写在工具说明里。所以两组的差别是：A3 有工具、版本、编辑提示与校验，A0 只有文件和 git。

## 8. 测试设计：伪用户

- **写入顺序：** 论文按入库顺序进入，每篇随机分给 3–4 个伪用户中的一个，由他们自行维护库。
- **写者数作为 T1 的主因子：** 同一论文序列跑两种条件：
  - $K=1$：一个伪用户维护全部；
  - $K=4$：随机分给 4 个伪用户。

  比较库健康度与下游正确性随时间下降的速度。两种条件下论文、顺序、种子都相同，只有写者数不同。随机分配用固定的种子，跑 2–3 种分配，看结果对分配是否敏感。
- **保留同一篇论文的两种读法：** 大部分论文只分给一个人，留 20%–30% 同时分给两个人。这样跨论文的重叠（大家都在改 ETTh1 那张表）自然发生，同一篇论文的分歧也保留一部分（C 类探针）。
- **伪用户的设定：** 每个伪用户有固定的身份（git 作者、`formed_by`）与一段长期的工作背景，例如：
  - “你在做一个基准对比项目”（I3）；
  - “你在研究这些方法为什么有效”（I2）；
  - “你在核查论文中的主张”（I5）。

  每次会话都是全新的上下文，只有身份与背景跨会话保持。
- **任务提示不提 leaderboard：** 只说“把这篇论文加入你的工作所用的知识库”。写者是否自己去找、去维护共同的表，本身就是一个观测量（采用率）。

## 9. 银标准：PapersWithCode

本地已有 PwC 归档快照（`pwc-archive/evaluation-tables`，`data/raw/t1-pilot-corpus/pwc/`），见 `docs/decisions/2026-10-10-t1-pilot-corpus.md` §3。先导语料的覆盖情况，按论文标题正则粗查（一次性核对，未留脚本）：

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

- **覆盖不均：** 10 篇中 7 篇有可用的条目。探针从 PwC 抽取时按论文分层。
- **PwC 把设置编码在数据集名里：** 如 `ETTh1 (336) Multivariate`。对照时要拆成数据集、预测长度与变量设置。这本身就是 C1 的一个现成例子。
- **leaderboard 的列覆盖了 PwC 一行的内容**（模型、论文、数据集、度量值），另外多出设置的分解与原文出处。银标准只用来对照，分歧回原文锚点裁决。

## 10. 与评测的关系

- **E1 完整性：**
  - **转录忠实度：** leaderboard 的每一行都可以按 `source` 对照原文核查。这也补上了先前的一个缺口：Observation 文本中的数值不在健康度统计里，与 A0 不对称。
  - **表格碎片化程度：** 作为身份质量的下游指标。
  - **“覆盖他人内容”重新定义：** 改动他人内容本身不再算退化，退化的是两种情况：改了却没有理由；读者在不知情的情况下读到了被改过的内容。A0 也能改他人的笔记，git 也有历史，所以要比的是改动在读取时是否可见、理由是否留存。
  - **采用率：** 写者是否发现并维护共同的表。
- **E2 充分性：** I3 的探针可以由 leaderboard 回答。`store_only` 与 `with_papers` 的差距直接反映表的覆盖。
- **E3 对等：** 混合标准，见第 5 节。
- **A0、A2 与 A3 的拆分：**
  - A0 拿到种子文件、没有提示；
  - A2 是同一 schema 的裸 Neo4j + Cypher，它拿到什么（种子 leaderboard、文档怎样存放、有没有版本）待定；
  - 原则是：A2 与 A3 之差只来自机制（校验、版本、编辑提示、过时附注）。

## 11. 按先导探针检查覆盖

| 探针类 | 问的是什么 | 由什么回答 |
| --- | --- | --- |
| A 有据数值（A1–A3） | 某论文某设置下的数值；look-back；“没报告” | leaderboard 的行与 `lookback` 列；“Papers covered” 的 `complete` |
| B 条件与来源（B1–B4） | 基线数值是自己跑的还是转录的；输入长度怎样定 | leaderboard 的 `origin` 与来历说明、`lookback` 列 |
| C 分歧可见（C1–C4） | 同一方法在不同论文中的值是否一致、为什么 | leaderboard 的多值附注；`compare_settings` |
| D 跨意图（D1–D3） | 消融变体的数值；结论是否依赖条件；是否用了额外训练数据 | 消融表（形式待定）；`verify` |
| E 针对产物（E1、E2） | 建一张跨论文的表；先前记录过哪些分歧 | leaderboard 本身；`compare_settings` 与编辑历史 |
| F 对照（F1、F2） | 消融的一格；标准误 | 消融表；标准误列（待加） |
| G 版本事件（G1、G2） | 论文换版本后的数值 | leaderboard 附注中的 `superseded`；`FetchArtifact(at)` |

**“按评测设计”要防的质疑：** 审稿人会问，算子是不是照着探针量身定做的。应对：

- 算子与探针都从意图推出，有共同的来源；`intents_decompose.md` 中每个意图都有公开任务作依据。
- **先冻结算子集合与种子，再写正式探针。** 正式探针一部分从 PwC 抽取（外部、事先存在），一部分按意图新写；写探针的人不改算子。先导探针只用来设计，不进入最终结论。
- 论文中如实写明：产物层是按这个 workload 设计的，换 workload 要换算子与种子。

## 12. 连锁改动（待同步，本稿定了再动）

- **叙事草稿：**
  - Graphiti 对比一段中“他人可以新增关系，但不能改写或删除”，改为“可以改写，但须写理由、保留历史、读取时可见”；
  - 四类对象表中 Artifact 一行，从“不需要一致，带出处并存”改为“可共同编辑；一致靠版本历史与编辑提示”。

  “可问责”的含义从“不让改”变为“改了一定看得见、追得到”。
- **AGENTS.md：** 其中“解释层的并存已经成立：Artifact 每次调用都新建一个”不再成立。
- **`operators.md`：** §4 的算子清单（删去 Filter、MatrixConstruct、自由 schema 的 Extract；Check 改为 `compare_settings`）；§5 的身份与幂等（5.4，改为按身份键）、写入（5.5，改为先校验后确认）、过期（5.6）；新增 `FetchArtifact`；Commit（§3.5）的返回加上相关的共同产物。
- **代码：** `server.yml`、`operators/agent/`、`artifact/`（版本、比对、编辑提示）、测试。
- **pilot-2 与 r2 的数据降为探索性：** A3 的工具与产物语义都变了。

## 13. 待定，各附我的建议

1. **消融表的形式：** 写进 leaderboard 加一列 `table`，还是每篇论文另建一份结果表。建议另建：消融的行是变体而不是方法，混进 leaderboard 会让表难读；格式沿用 leaderboard，只是对应一篇论文。
2. **行键的具体定义：** leaderboard 的已在第 6 节；`compare_settings`、`verify` 的行键随格式一起定。
3. **A2 的配置：** 见第 10 节，待评测设计时定。
4. **标准误：** leaderboard 加一列 `stderr`，可空。建议加（F2）。
5. **Commit 返回相关产物的范围：** 只沿“实验 → 数据集 → leaderboard”一条路径，还是也沿方法、主张（例如返回对某条 Claim 的 `verify`）。建议先只做数据集这一条，看采用率再扩展：返回太多会变成噪声。
