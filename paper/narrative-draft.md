# Collaboration without Coordination: Managing Scientific Knowledge for Agentic Research

（标题暂定。）本文是学术知识积累的领域系统论文：要解决的就是这个领域的问题，而不是拿它当通用问题的一个实例。标题因此点出领域（Agentic Research），系统名保留 PaperWeave。

- 前半句用名词，陈述原则；后半句只留 Managing 一个动作，说明我们做什么。"Coordination" 作名词是数据库界的用法（coordination avoidance、coordination-free）。
- "Scientific Knowledge" 点明管理对象：论文派生的知识与产物。2026-10-14 由 "Scientific Memory" 改回：memory 一词会倒逼系统纳入 skill 提炼、整合、遗忘等工作负载并不要求的功能（[头脑风暴](../docs/discussions/2026-10-14-design-brainstorm.md) §1）。agent memory 的谱系（GEM、Collaborative Memory、ShareMem）改在摘要与相关工作中交代，仍对应主投方向 AI & knowledge bases；摘要必须说清：这些知识只能靠来源锚定，不能靠整合者改写。
- 标题只写 Knowledge，审稿人可能拿它和 ORKG、PwC 一类科学知识库比；正文要说明差别在写者：许多互不协调的 agent 持续写入，而不是人工整理。
- 不写 "Shared Memory"，以免让人联想到共享内存架构。
- 查重（2026-10-13，网页搜索 + OpenAlex 标题短语检索）：没有以 "Collaboration without Coordination" 或 "Collaborating without Coordinating" 为题的论文。最接近的是 Stone et al. 的 *Ad Hoc Autonomous Agent Teams: Collaboration without Pre-Coordination*（AAAI 2010，ad hoc teamwork），领域和措辞都不同。

"Collaboration without Coordination"会让审稿人期待协调规避（I-confluence、CALM）式的不变式分析。正文用四类对象各自的一致方式接住：写者不协调时，每一类对象怎样达成一致，见“四类对象”一节。

# 论文草稿

中文记叙事意图；英文代码块留候选短句和用语。两者都用于推进草稿，随设计继续调整。系统设计见 V3 的[数据模型](../docs/designs/v3/data_model.md)与[工具](../docs/designs/v3/tools.md)（V2 的 [`docs/designs/v2/`](../docs/designs/v2/) 作背景，冲突处以 V3 为准）；工作负载见[意图 V3](../docs/designs/v3/intents.md)；评测设计见 [`evaluation_draft.md`](../docs/designs/v2/evaluation_draft.md) 与[评测 V3](../docs/designs/v3/evaluation.md)。

# Abstract

（暂定。）先不写评测数字，结果用定性表述；终稿有了实验结果再决定是否补数字。

宏观主线是“agent memory 的谱系 → 研究知识没有可信的整合者 → 外部锚点代替协调”：

- **Agent 从知识的消费者变成生产者。** 它们读、比较、核查时留下的记录，别的 Agent 可以接着用。
- **从 agent memory 的谱系切入，指出它共同的假设。** memory 从把交互历史提炼成教训、技能、工作流开始，发展到把记忆当作数据管理问题（如 GEM 的 *Is Agent Memory a Database?*），再到跨用户共享（Collaborative Memory、ShareMem）。这些系统都假设有一个可信的整合者：拥有记忆的 Agent，或改写共享池的内部 LLM。于是最新整合出的条目可以代表真值。
  - 这对过程性经验成立：经验好不好，看下一个任务成不成功。
  - 对研究知识不成立：研究知识对不对，要对照它的来源。

  摘要只陈述这一点，不点名反驳。
- **答案是外部锚点代替协调。** 研究知识的权威不在任何写者，而在论文原文及其版本、官方代码与外部标识。数据模型沿用 Entity / Concept / Content / Artifact 四类，分成两层：前三类是证据节点，属于有据层，对来源负责；写者自己的判断不写成证据节点，写进产物（Artifact），属于解释层。写入机制（不是模型本身）让每一类在不协调下达成一致：
  - Entity 与 Concept 的身份收敛到外部标识与名称；可能重复的候选退回写者，由写者判定；
  - 论文所说的 Content 单值，绑定论文的材料版本，修订须带锚点和理由，历史全部保留；
  - 写者的判断不需要一致，写进产物，带形成者与所用输入并存；
  - 共同产物按身份键唯一、共同编辑，每次改动都有版本、可追溯到人；输入变了，读到产物的人会看到过期标记，改了输入的写者在提交时就被告知。
- **不卷 memory 的性能。** 评测三点，摘要定性表述：
  - 写者增多时库不退化，也不把维护的代价转嫁给读者和写者（主结果；“代价”一半是 2026-10-19 的提议，见引言“可证伪的现象”）；
  - 库中内容足以支撑研究意图，不必回读论文；
  - 答题效果不逊于 agent memory 系统（非劣效）。
- 机制压缩成一句“经典机制的改造”。四类对象与经典机制的对应留给引言与设计章节，摘要不展开。
- **照顾主题领域：**
  - 数据模型一句（四类对象及其一致方式）对应 *Data models and semantics*；
  - 实体解析直接写 entity resolution，对应 *Data integration*。实际机制是存储层给出候选（id、alias、语义近邻），由写入者在写入时判定；不做匹配算法，也没有 merge/split。摘要不展开，正文讲清。
  - Agent 产物只标记过时、不重算，所以写 view invalidation：读取时附带过时提示，改动输入的提交同时告诉写者哪些产物受影响。
- **领域立场：** 摘要第一句就落在研究论文上，不先提通用问题再收回。泛化只在 Discussion 留一段，不进摘要。

```text
LLM agents now read, compare, and verify research papers, and what they record
can serve the agents that come after them. Agent memory systems distill
experience into lessons and workflows, and increasingly share it across users,
but they assume a trusted consolidator: the owning agent, or an internal model
that rewrites the shared pool, so that the latest consolidated entry can stand
for the truth. This suits procedural experience, which is judged by whether the
next task succeeds, but not research knowledge, which is judged against its
sources. When many agents that do not coordinate accumulate knowledge about
papers in one store, no writer's word is authoritative; the papers, their
versions, their code, and their external identifiers are. We present
PaperWeave, a data management system in which these external anchors
substitute for coordination. It separates evidence records, which answer to
their sources, from artifacts, which carry writers' judgments, and its write
mechanisms give each kind of record its own way to agree: entities and
concepts converge on external identifiers and names, with candidate
duplicates returned to the writer; what a paper states holds one value, pinned
to a version of the paper and revisable only with an anchor and a reason;
writers' judgments coexist in artifacts with their writers and inputs; shared
artifacts are keyed and co-edited, every edit is versioned and attributable,
and a change to an artifact's inputs is flagged to its readers and reported to
the writer who made it. PaperWeave adapts entity resolution, view
invalidation, and data versioning to agent writers. On a workload derived from
six research intents, we evaluate whether the store stays sound as writers
accumulate, and at what cost to writers and readers; whether its contents
suffice for these intents without rereading the papers; and whether its
answers match those of agent memory systems.
```

# Introduction

## Why：

先讲四点背景：

1. **通用 Agent 参与研究：** 读论文、抽取方法与实验、比较、形成判断与报告。这些产物持续积累，后续工作值得在它们之上继续。
2. **agent memory 的谱系与它的共同假设：**
   - memory 起于经验复用：把交互历史提炼成教训、技能或工作流，供后续任务使用；
   - 随后被当作数据管理问题；
   - 现在开始跨用户、跨 Agent 共享。

   这些系统都有一个可信的整合者，最新整合的条目代表真值。我们不在这条线上比高低：经验类 memory 已经发展出 skill、偏好与经验分离等高层设计，我们存的不是经验，是**知识与产物**。要切的一刀是：
   - **过程性经验以使用效果评判；**
   - **声明性的研究知识以来源评判。**

   ShareMem 的共享池由内部 LLM 覆盖改写，不记出处、不留历史。对经验来说这没问题，合并后的教训往往更好；对论文知识来说，这正是退化：值被悄悄改掉，分歧被悄悄抹平。
3. **积累是共享的，写入者互不协调：** 同一个人或研究组在几个月里开出大量 session，彼此上下文不通；不同项目、不同成员的 Agent 各自读到同一批论文。愿景是一个公共平台（paper4agents）。共享库是写入者之间唯一的通道，读者往往是当初不在场的陌生人。
4. **单写者不需要数据库：** 一个 Agent 在一个项目里复用自己的产物，文件加 Git 作为基线，可能是最强的（尤其是在大厂都在卷这种场景下的模型能力的背景下，与这个模式做竞争没有必要），可能已经够用。数据库的理由来自许多写入者长期写同一个库，这也是 DBMS 的经典理由：共享数据、完整性、多用户。

背景第 2 点的候选段落。引文来自 ShareMem 的背景写法：前三条是 Reflexion、ExpeL、AWM。这三条与 GEM、ShareMem 尚未进 `references/refs.bib`；`2024-MemorySharing`、`2025-CollaborativeMemory`、`2025-Zep` 已在。

```text
LLM agents increasingly retain memory beyond a single context. Early work
distills interaction histories into lessons, skills, or workflows for later
tasks (Shinn et al., 2023; Zhao et al., 2024; Wang et al., 2024b). Recent work
treats agent memory as a data management problem, and begins to share memory
across users and agents. These systems share one assumption: the memory has a
consolidator it trusts, either the owning agent or an internal model that
rewrites the shared pool, so the latest consolidated entry can stand for the
truth. This holds for procedural experience, whose worth is judged by whether
the next task succeeds. It fails for knowledge about the world, such as what a
paper reports, whose worth is judged against its source.
```

```text
Background: General-purpose agents read, extract, compare, and judge papers,
and their outputs accumulate.
Setting: The accumulation is shared. Many agents and sessions that never
coordinate write to one long-lived store, and later readers were not there
when it was written.
Not the setting: One agent reusing its own work within one project, where
files and Git are a strong baseline and may suffice.
```

**研究知识的性质决定了设计。** 要回答的不是“为什么选论文领域”，而是“为什么通用的 agent memory 不够用”。审稿人对领域系统论文的问题是：为什么通用系统做不了？ORCHESTRA 面向生物信息学的协作数据共享就是这种写法。回答是：研究知识有以下性质，通用 memory 没有建模它们，而每一条都对存储提出要求，并落在模型的某一处：

| 研究知识的性质 | 对存储的要求 | 落在模型的哪里 |
| --- | --- | --- |
| **写入高度重叠：** 引用呈长尾分布，少数热门方法、数据集和 benchmark（如 PatchTST、ETTh1）几乎被每个项目、每个 Agent 反复读到 | 同一对象被许多写者各写一遍，身份必须收敛 | Entity、Concept 的身份；也是 E1 中退化压力的来源 |
| **身份难判，但有外部锚点：** 别名、变体、子集（ETT 与 ETTh1）让判断不平凡；同名不同物也常见：Informer 的 Weather 是 NOAA 的美国站点数据，后来论文的 Weather 是 BGC-Jena 的 21 个气象指标；arXiv ID、DOI、代码仓库与数据集主页提供外部标识 | 收敛借助外部标识，而不是写者之间互相协调；名称相同不等于同一对象，所以名称只产生候选，由写者判定 | Entity 的 `identities`；名称与别名的精确查找；写入时的查重候选 |
| **权威来源固定且有版本：** 论文原文是作者陈述的唯一依据；arXiv 版本、勘误、撤稿会改变它 | 对“论文说了什么”的分歧可以回原文裁决；引用要固定到版本，来源变化要能被发现 | Content（全部带锚点）；Paper 的 `material` 按内容登记版本，Content 记下写入时的材料，锚点落在旧版本上时读取给出提示 |
| **代码也是来源：** 结果的口径常由代码决定、论文正文不写：PatchTST 官方代码的测试 DataLoader 设 `drop_last=True`，TiDE 修正后重新评测，两篇论文同一格的差别由此而来 | 官方代码库按 commit 固定，作为与论文并列的材料；读代码、记配置在库内，运行与复现在库外 | Code 的材料与代码锚点（2026-10-18 商定方向，模型改动待设计评审） |
| **合理的分歧：** 结果依赖条件，比较与综合因目的而异，读者也可能误读 | 判断不需要一致，需要带着出处并存 | 产物：Verify 保留前人的判断、另起一节；CompareSettings、Summarize 各带形成者与所用输入 |
| **派生内容依赖其他记录：** 比较表、综述、核查结论建立在别人写下的记录上；有的输入是隐含的，排行榜应当收进表头数据集上的全部实验 | 派生内容声明输入，输入变了要能被发现；隐含的输入多出来，也要能被发现 | Artifact 的 `USED`；读取时的 `_stale`（含隐含输入的 `uncovered`）；提交时的 `affected_artifacts` |
| **知识寿命长、重读成本高：** 每个研究 Agent 从头重读同一批论文，冗余很大 | 值得在写入时多投入，由后来的读者摊销 | E3 的成本账 |

另有两条性质让问题可以评测，但不决定设计：

- **有客观的未来可对照：** 按时间切分，用 $t_0$ 之前的论文建库，以之后论文实际选用的 baseline、数据集与指标为金标准（本文暂不做，留作后续评测）；
- **数据公开、金标准现成：** TDMS、AxCell、SciREX、LEGOBench、OpenAlex 等，满足可复现要求。

与其他场景的差别，说明通用设计为什么在那里够用：

- 代码库知识本身就是真值，且已由 Git 管理；
- 个人助理记忆只有一个主人，偏好与经验以使用效果评判（ShareMem 的场景）；
- 通用百科的写者是人，已有 Wikidata。

**主张范围：** 写成领域系统论文，标题点出领域，主张与实验结果只针对研究知识。Discussion 留一段：法律、临床指南等同样有外部权威来源的领域，可以借鉴按对象类别规定一致方式的做法。这一段是讨论，不是主张。

“写入高度重叠”是身份收敛压力的前提，需在选定语料上核实（例如热门方法与数据集被多少篇论文用到）；若重叠不足，E1 测不出退化。开发语料上已初步核实（`tmps/pilot/p0-overlap.md`）：7 篇论文两两之间平均共享 4 个被评测的方法、6.5 个数据集，ETTh1、Weather 等被 7 篇全部用到。正式语料另抽，要重测。

参照 AgenticScholar 的数据管理问题引入：
**学术知识系统管理文档与人工整理的知识，Agent Memory 管理单个 Agent 的交互历史；由许多互不协调的 Agent 持续写入的共享派生知识，尚无人管理。**

再引出可证伪的现象（对应评测 E1）：没有身份、契约、来源与版本约束时，共享积累的完整性随写入者数和写入量增长，只有两种去向。

1. **丢失：**
   - 同一对象被建成多个节点（重复），或不同对象被并成一个（误合并，如两个 Weather）；
   - 产物引用的记录不存在或已改变（悬空引用）；
   - 两个写入者对同一结果给出不同读法，后写的静默覆盖前写的（冲突未被发现）；
   - 来源被修订、撤回或出了新版本后，依赖它的比较与报告没人知道已经过时。
2. **由写者与读者自己补回：** 写者写之前自己查重、写完自己校验引用；读者为确认一个答案是否完整、是否过时，自己把相关记录对一遍。库小的时候补得回来，答案不一定错；但补回的代价每次写、每次读都要付一遍，并且随库增长。补不全的地方，答案就错。

与此同时，内容按各个写入者自己的目的、措辞和粒度存放，换一个目的的读者未必找得到。

错的答案往往看不出错。例子：只读论文正文，TiDE 表中的 PatchTST 列像是转载自 PatchTST 论文；实际上 TiDE 修正了 PatchTST 官方代码中测试集丢样本的问题（`drop_last=True`）后重新评测，只在脚注中一笔带过。写下“转载”的记录有锚点、读起来通顺，却是错的；我们自己按论文正文写的探针标准答案，起初也这样写错（先导决策日志 D17）。这个例子同时说明为什么代码要作为来源。

（2026-10-19 提议，待确认：在“错而不显”之外加上“代价转嫁”这一半。依据是先导的方向：5–9 篇论文的规模下，各组的读者正确率接近，失分多来自某位写者的一次判断；拉开的是读者与写者的代价、Graphiti 的身份重复与版本变化。先导不进结论，只用来调整要检验的命题。若同意，E1 把代价与库健康度、正确率并列为主指标，以库的规模为自变量，AGENTS.md 中 E1 一句随之修改。）

```text
Without identity, contracts, provenance, and versions, shared accumulation
degrades as writers and writes grow: duplicate and wrongly merged entities,
dangling references, unnoticed conflicts, and stale artifacts. Diligent
writers and readers can repair some of this themselves, by searching before
they write and by cross-checking what they read, but the repair is paid on
every write and every read, and it grows with the store. What is not repaired
yields answers that are wrong without looking wrong. Content stored on each
writer's own terms is, moreover, hard to find for readers with other purposes.
```

## Figure 1：多写者共享积累及其退化

放在 intro 的场景图，让读者看到：（a）几个互不知情的写入者在时间线上交错，读到重叠的论文；（b）同一段写入历史落进两种库，一种无约束，一种有约束；（c）几个写入者先后编辑同一份共同产物。五个 challenge 都要能指到图上的具体元素。这个场景同时是评测 E1 的设定，评测中完整重演。

```text
                                         time ──────────────────────────────────────────────────────▶

┌─ Writers ── uncoordinated, each unaware of the others ─────────────────────────────────────────────┐
│                                                                                                    │
│   W1 · proj X     reads A, B ──▶ extract ──▶ comparison table ───────────────┐                     │
│   W2 · proj Y              reads B, C ──▶ reads B's result differently ──────┤   B: read twice,    │
│   W3                                  reads D (contradicts B's claim) ───────┤   independently     │
│   R  · later reader (not present at writes)          "which method is best on ETTh1@720?"     (C5) │
└────────────────────────────────────────────────────────────────────────────────────────────────────┘

                                                   │ same write history
                    ┌──────────────────────────────┴─────────────────────┐
                    ▼                                                    ▼
┌─ (a) Unconstrained store ────────────┐    ┌─ (b) Identity · Contracts · Provenance · Versions ─────┐
│                                      │    │                                                        │
│   [PatchTST] [PatchTST′]             │    │   [PatchTST] ◀── W2 shown W1's node, reuses it    (C1) │
│   duplicate nodes               (C1) │    │   B: W2 revises with anchor + reason;                  │
│   B: W2's value silently             │    │      W1's value stays in history                  (C3) │
│      overwrites W1's            (C3) │    │   cmp table flagged stale; W2 told at commit      (C3) │
│   cmp table → old B, no flag    (C3) │    │   D's evidence added beside B's, not over it      (C3) │
│   B's claim overwritten by D    (C3) │    │   references pinned to paper versions             (C2) │
│   report ──▶ [record gone]           │    │   R: answer + revision + staleness notice              │
│   dangling reference            (C2) │    │                                                        │
│   R: wrong answer,                   │    │                                                        │
│      and it looks right              │    │                                                        │
└──────────────────────────────────────┘    └────────────────────────────────────────────────────────┘

┌─ Shared artifact: Leaderboard (ETTh1, multivariate) ── one per key, versioned ─────────────────────┐
│                                                                                                    │
│   W1   creates v1 (rows from A, B)                                                                 │
│   W2       checks out v1 ──▶ adds rows from C ──▶ commits v2        editors: W1, W2                │
│   W3            edits from v1 ──▶ commit rejected: base v1 is not the latest                       │
│                      ──▶ checks out v2, keeps others' rows, adds rows from D                  (C4) │
└────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

初版（10-13，按旧的字符图画的，需按上面的字符图重画；脚本在 `tmps/draws/`）：
[Figure1](./figures/introduction/Figure1.svg)

```text
Caption:
    Figure 1: Uncoordinated writers accumulating paper-derived knowledge.
    Writers with separate projects read overlapping papers at different times
    (top). The same write history lands in an unconstrained store, which
    degrades, and in a store that enforces identity, contracts, provenance, and
    versions (middle): there, a revision keeps its anchor, reason, and the old
    value; contrary evidence is added beside earlier evidence; and an artifact
    whose input changed is flagged to its readers and reported to the writer
    who changed it. Writers extend one shared artifact in turn; an edit from
    an outdated version is rejected and redone on the latest one (bottom).
```

Band 1（写入者）：三个写入者各自做自己的事，互不知道对方存在，而且各带不同的研究意图（intent）。W1 为项目 X 比较实验结果（I3），读 A、B，抽取并做比较表；W2 为项目 Y 核查一条主张（I5），读 B、C，对 B 的同一个结果读出了不同的值；W3 后来读到 D，D 的实验与 B 的主张相反。最后一个陌生读者 R 带着另一个意图来用这个库：它要找到的内容是别人为别的目的写下的。写侧行为包括读、抽取、比较、判断、修订、删除，以及检出、编辑、提交共同产物；读侧强调读者不在写入现场，也不知道内容当初是怎样组织的。

Band 2（共享库）：同一段写入历史分别落进两种库。左栏无约束：重复节点、静默覆盖、未标记的过时、悬空引用，R 得到错误答案且看不出来。右栏有约束：

- **身份：** W2 新建 PatchTST 时，提交退回 W1 已建的同名节点作为候选，W2 改用它（C1）。系统只给候选，不替写者合并；写者判错时（如把两个 Weather 当成一个）照样会误合并。
- **有据层的修订：** B 的结果是论文所说的内容，只有一个值。W2 读出不同的值时，不是并存两种读法，而是带原文锚点与理由修订；W1 的旧值留在历史中，读者看到最近一次修订的理由（C3）。系统不检测两种读法的冲突，冲突由后来的写者回原文判断。
- **过期：** 比较表用到了 B 的记录。W2 的修订让它在读取时带上过期标记，W2 提交时也被告知这张表可能过期；是否更新由写者决定（C3）。
- **证据并存：** D 与 B 的主张相反。W3 加一条从 D 的实验指向 B 的主张的 `OPPOSES`，B 自己的支持依据仍在；W3 对“B 的主张是否仍成立”的判断写进 Verify，与前人的判断分节并存（C3）。
- **版本：** 引用固定到论文的材料版本（C2）。

图中数值只作示意。

Band 3（共同产物）：一个身份键（任务、数据集、设置）只有一份 Leaderboard。W1 建立 v1；W2 检出 v1、补上 C 的行，提交 v2，编辑者记为 W1、W2；W3 基于 v1 的编辑在提交时因不是最新版本被拒，检出 v2 后保留他人的行、补上 D 的行，得到 v3。每个版本都保留，谁改了什么、为什么改都看得到；改他人的行须写理由。

五个 challenge 在图中的落点：C1 对应 PatchTST 的重复与收敛；C2 对应比较表与报告所带的输入、条件和引用；C3 对应 B 的修订、比较表的过期标记与提交时的告知、D 与 B 的证据并存；C4 对应 Band 3 的检出、提交与过旧版本被拒；C5 对应 R 的问题：答案分散在 W1 的比较表、W2 的修订与 W3 的 Verify 中，R 要在不知道它们如何组织的情况下找到它们。

## 从场景到问题与 Challenges

```text
How can a long-lived store accumulate paper-derived knowledge and artifacts
written by many agents that do not coordinate, so that later readers can
still find, trust, and build on it?
```

问题的几条边界，在 Problem 节显式写出：

- **不协调指语义上互不知情，不是并发事务。** 写入者不知道别人写过什么、怎么理解的；写操作本身可以轮流执行，原子性与隔离交给后端事务，不是本文的问题。
- **领域类型词表是给定的。** 我们假定写入者共享一套领域类型（Paper、Method、Dataset、Experiment 等）；词表的设计与演化属于 ontology engineering 与 schema induction，与本文正交。我们研究的是共享积累的完整性语义，领域词表是它的一个参数；本文为 CS 论文给出一个实例。
- **库不判断谁对：可问责，而非权威。** 写入者之间有分歧时，语义判断由 Agent 做；中间件只让分歧可见、可追溯、可被后来者处理，不按使用或引证次数排名。权威不在库里，而在库所指向的外部参照中：固定版本的论文原文与外部标识（arXiv ID、DOI、OpenAlex、Wikidata 等）。按写者不协调时怎样达成一致，每一类对象有自己的一致方式，见下一节。
- **库从论文原文开始。** 不预设权威快照：外部参照随时可取，有据层与解释层由写入者读论文后构建。冷启动可以从公开注册表引导身份锚点，但论文内容层面没有现成来源，正是 Agent 的工作。
- **主张限于研究知识。** 评测与结论只覆盖本领域；推广留给 Discussion。

## 四类对象：不协调时怎样达成一致

这一节回应标题。模型的主结构不变：Entity、Concept、Content、Artifact 四类，加上名称键、材料、提交记录等系统记录。前三类是证据节点，按身份怎样确定来划分（[数据模型 V3](../docs/designs/v3/data_model.md)）：Entity 有外部标识，Concept 只有名称与描述，Content 是某篇论文在某处说的话、附锚点；Artifact 是写者交上来的、有类型、有版本的文档。写者之间不协调，库里的记录仍要在某种意义上“一致”。

**主张要保守：** 一致与问责靠的是机制，不是数据模型本身。数据模型只说明记录是什么、出自哪篇论文的哪几行，不在模型上区分读写者，也不保证写者责任分明。让写者能在不协调下协作的是写入机制：

- **统一提交：** 每次写入都记录作者（来自服务端登录，不由写者自报）、时间、说明与前后值，对所有类别一视同仁，所以任何记录都能查到是谁写的；
- **写入时的查重：** 新建 Entity、Concept 时，名称、别名与外部标识的精确命中，以及语义上的近邻，作为候选退回，这一批先不写；写者改用已有对象，或声明不同（`distinct_from`），判断记入提交；
- **有据层的修订：** 改字段、改或删出边须带锚点与理由；Content 记下写入时论文的材料版本；
- **共同产物：** 按身份键唯一；提交须基于最新版本；改他人的行须写理由；声明输入（`USED`）；
- **过期：** 读取时计算（`_stale`），提交时也告诉造成它的写者（`affected_artifacts`）。

两层的划分（V3 起）：

- **有据层是证据节点：** Entity 与 Concept 的身份，以及 Content（Experiment、Claim、Contribution）。Content 都来自论文、都带锚点，对来源负责。论证关系 `SUPPORTS` / `OPPOSES` 也是带锚点的边：它记下“这条证据与这条主张相关”，后来的写者可以跨论文添加，但同类边按端点唯一，新加的边不替代、不删除已有的边。
- **解释层是产物：** 写者自己的判断（这条主张是否仍成立、两行能否比较、一条路线怎样综述）不写成证据节点，写进 Verify、CompareSettings、Summarize 等产物，带形成者与所用输入。

V2 用 `stated_by: paper / agent` 把 Content 分成两半，解释层里有 Observation；V3 去掉了这一分法，解释层整体落在产物上。

| 类 | 是什么 | 靠什么机制达成一致 | 写规则 | 读者看到什么 | 没有机制时的退化 | 经典对应 |
| --- | --- | --- | --- | --- | --- | --- |
| **Entity** | 有外部标识的资源：Paper、Dataset（含评测套件）、Code、Model、Tool | 外部标识（arXiv ID、DOI、Semantic Scholar ID）撞上即同一对象；名称、别名与语义近邻只作为候选，交写者判定 | 新建，或指向已有对象；被引用而未入库的可以先建桩，后来者补全 | 解析后的唯一对象；写者的查重判断记在提交上 | 重复、误合并、悬空引用 | 实体解析、自然键 |
| **Concept** | 许多论文共同指向、没有外部标识的概念：Method、Task、Issue | 只有名称、别名与描述；候选交写者判定，系统不按描述相似自动合并；变体与配置不建节点 | 同 Entity | 同 Entity | 重复与误合并最集中的地方（见下） | 实体解析、受控词表 |
| **Content** | 论文在某处说的话：Experiment、Claim、Contribution；带锚点的论证边 | 写者之间不必协调，分歧回到原文锚点 | 单值；修订须带锚点和理由；绑定材料版本；论文出新版本时换材料，旧锚点留在旧版本上 | 当前值；最近一次修订的理由与锚点（`_revised`）；哪些锚点还落在旧版本上（`_anchor_version`） | 值不忠实；引用了旧版本而不自知；被静默覆盖 | 有修订日志的权威数据、truth maintenance |
| **Artifact**，有身份键 | Leaderboard（任务、数据集、设置）、CompareSettings（所比较的对象）、Verify（一条主张） | 一个键一份，共同编辑；分歧写进同一份产物，Verify 保留前人的判断、另起一节 | 检出、编辑、提交；须基于最新版本，每个版本不可变；改他人的行须写理由；声明输入 | 当前版本、各编辑者与改动说明、过期标记（`_stale`） | 同一张表各写一份；他人的行或判断被静默改掉；输入已变而无人知道 | check-out/check-in、乐观校验、CRDT 多值寄存器、Wikidata ranks、视图失效 |
| **Artifact**，无身份键 | Summarize、Generate | 不需要一致，各自并存，带形成者 | 同上，只是不撞键 | 多份并存，各带出处与过期标记 | 找不到，或分不清；输入已变而无人知道 | provenance、视图失效 |

Skill 也是有身份键的产物类型（按名称），但它是写者“怎么写”的知识，不是论文派生的知识，不进 E1，表中不列。

这张表把模型、机制和评测串成一条线：

- 机制在每一类上的效果，同时决定了写规则、读者看到什么、没有机制时怎样退化；
- “退化”一列与现有的库健康度指标基本一一对应（重复实体、悬空引用、有据层忠实度、覆盖他人内容），所以 E1 的指标不是随手列的，而是每一类对象特有的退化方式。

```text
Uncoordinated writers can still agree, but not all in the same way. Entities
and concepts converge on external identifiers and names; candidate duplicates
go back to the writer, who decides. What a paper states is settled against the
paper itself: such content holds one value, pinned to a version of the paper,
and a revision must cite the source and give a reason. What a writer judges
needs no agreement; it is written into artifacts, where it coexists with its
writer and inputs. Shared artifacts are keyed and co-edited, so every edit
stays versioned and attributable. External anchors thus substitute for
coordination wherever facts are checkable, and attributed coexistence
replaces adjudication wherever they are not.
```

两点细化，都只是测量与解释，不改冻结的模型：

1. **Entity 与 Concept 的身份难度不同，这是 C1 最难的地方。**
   - Paper 有外部标识（arXiv ID、DOI），收敛是确定性的。
   - Method、Task 没有外部注册表，只能靠规范化名称，“锚点”实际上是提出它的论文。

   由此得到一个可以检验的预测：外部锚点越弱，越依赖写者判断，退化越多。E1 按对象类型拆开报告重复率，预期 Paper 的重复率接近 0、Method 最高。若数据支持，它本身就是对这种划分的支持；若不支持，如实报告。

   名称也不是可靠的锚点：两个 Weather 同名不同物，按名称自动合并必然合错，所以查重只列候选，不自动合并。候选交给写者以后，写者仍可能判错；写者一开始就复用已有的同名节点时，查重根本不起作用（查重只对新建起作用）。误合并率按对象类型报告，这一点作为局限如实写出。
2. **派生内容分两种，对应数据库中两种处理视图的方式。**
   - **确定性的派生：** 例如从论文所说的结果行 join 出 Leaderboard。它可以像物化视图一样精确重算，来源被修订后跟着变（view maintenance）。
   - **Agent 生成的派生：** Artifact，包括 Leaderboard。重算代价高且结果不确定，只标记过期（view invalidation），是否更新由写者决定。

   两者的分界线是“这个派生是否出自 Agent 的判断”，正好落在“Agent 写者改变了什么”上。系统只做后一种：Leaderboard 由写者从论文读出并共同维护，不由系统 join 生成，所以摘要只写 view invalidation。

   过期按输入的来路分三种，都是读取时计算、提交时告知：
   - **声明的输入：** 产物经 `USED` 指向它用到的节点与其他产物。节点被修订（`revised`）、论文出了新版本（`superseded`）、材料文件被改动（`material`）、所引的产物出了新版本（`superseded`），都使产物过期；过期沿产物之间的 `USED` 传递（`stale input`），例如 CompareSettings 引用了排行榜的行，排行榜更新后它也过期。
   - **隐含的输入：** 排行榜的输入不只是表中已有的行，还有“表头数据集上的全部实验”。库里出现了使用该数据集、但论文不在表中的实验时，排行榜报 `uncovered`；写者有意不收的论文写进 “Papers covered” 并给出理由，提示即消失。这相当于按视图的定义谓词判断失效，而不只按已记录的输入。不收也是留下记录的决定：理由写错了，机制不会再提醒。
   - **写入一侧的补全：** `_stale` 只在读取时算，改了证据的写者看不到它让哪些产物过期，要等下一个读到产物的人。所以提交前后各算一次，把新出现的过期原因随提交结果告诉这位写者（`affected_artifacts`），只是信息，不阻塞。

   已知的粗糙处，在 Lessons 或局限中写明：产物出了新版本，下游一律报 `superseded`，即使所引的行没有变；给实验加一条 `OPPOSES` 边也算“实验被修订”，对排行榜是误报。两处都按记录或版本判断，不做行级、字段级的比较。


五个困难，各自接回图中的元素。C1–C4 在写侧，回答 trust 与 build on；C5 在读侧，回答 find：

1. **独立写入下的身份：** 不同写入者在不同时间写同一个方法、数据集或结果，要收敛到同一身份，同时不能把不同对象误并。身份规则必须显式、可检查、对所有写入者一致；粒度定在哪里（例如方法变体是否单独建节点）属于领域实例化。
2. **自描述的贡献：** 写入者之间没有共享上下文，库是唯一的通道。产物必须自带条件、证据和输入依赖，不在场的读者才能使用或复查。
3. **分歧与变化：** 写入者之间有分歧，会误读后修订，会撤回；源材料也会变。库要暴露冲突与过时，既不静默覆盖，也不整批拒绝：有据层的分歧回到原文修订并保留历史，解释层的判断带着来源并存。
4. **在共同成果上继续构建：** 后来的写入者要能在别人的产物上补充和修正，而不是另起一份；改动不能悄悄破坏别人写下的内容，并且能回到任一历史版本。
5. **跨写入者的可发现性：** 一个写入者为某个目的写下的内容，要能被另一个目的的读者找到。读者不知道写入者当时的措辞、粒度和组织方式，又受上下文所限，需要把结构导航与语义检索组合起来，取得有界的视图。

```text
C1. Converge identities across independent writers without wrong merges.
C2. Make contributions self-describing for readers who were not there.
C3. Keep disagreement and change visible, neither overwritten nor rejected.
C4. Let writers extend shared results without silently breaking others' work.
C5. Let readers with one purpose find what writers with another stored.
```

挑战编号暂按提出顺序；正文是否按 find → trust → build on 重排，待定。

## Claim + Contributions：总体方法

一个面向外部通用 Agent 的共享知识积累中间件：Agent 经 MCP 读写。写侧，中间件对身份、契约、来源与版本施加约束，使互不协调的写入在长期积累中不退化；读侧，它提供从研究意图推出的检索面与知识访问工具，使别人写下的内容能被找到。

```text
We propose a middleware for shared accumulation of paper-derived knowledge
by uncoordinated agents. On the write side, it enforces identity, contracts,
provenance, and versions, so that the store keeps disagreement and change
visible instead of degrading as writers and writes grow. On the read side,
it offers an intent-derived retrieval surface and access tools, so that
readers can find what others stored for other purposes.
```

工作负载的根：**六类研究意图 I1–I6**（发现工作与方法、理解机制与条件、组织结果并判断可比性、综合路线与发现、核查主张、取得实现资源），各有公开任务作为依据（PaperFindingBench、QASPER、TDMS-IE、ScholarQA-CS、ArxivDIGESTables、SciFact、CORE-Bench 等），分解见 `docs/designs/v2/intents_decompose.md`。它们在本文中有三种用途：

- 生成写入者的任务：不同意图的写入者以不同粒度和关注点写到同一批对象上，这正是 C1、C3 压力的来源；写入者数 $K$ 由此操作化为任务意图的多样性。
- 生成陌生读者的探针：探针有任务依据，不是为本系统量身定制的。
- 决定检索面：对象的哪些字段与关系必须可检索，由读需求推出。

意图在这里提供了工作负载。"我们的工具支持这六类意图"本身不构成贡献，因为通用图库配上合适的查询同样可以支持。

定位：**经典机制的选择与改造。** 每项机制都有经典前身：实体解析与自然键（C1）；provenance、W3C PROV 与 nanopublication（C2）；物化视图失效、真值维护，以及 Trio、CRDT 多值寄存器、Wikidata rank 式的值并存（C3）；check-out/check-in、乐观校验与数据版本管理（C4）；dataspaces 的按需整合、数据库上的关键词搜索与混合检索（C5）。我们主动引证这些前身，不用主张新的并发、provenance 或版本理论。贡献在于说明 Agent 写入者要求的改变，并用实验证明哪些机制仍然必要。需要改变的有五点：

- 裁决在写入时交还写入者；
- 错误是语义性的且读起来通顺，所以保留来源与分歧比保证正确更重要；
- 派生内容重算昂贵且不确定，所以只标记过时，不做自动维护；改动输入的写者在提交时就被告知哪些产物受影响，是否更新由写者决定；
- 读者不会主动查 provenance，所以分歧与过时随查询结果一起返回；
- MCP 接口就是契约，Agent 会不会用、会不会绕开都可以测量。

对照与文献见 `docs/discussions/2026-10-10-challenges-and-classical-mechanisms.md`。

设计立场：**薄图、厚文档。** 图里只放身份锚点和引用关系；丰富内容放在 Artifact 文档中，文档结构由 Agent 按契约声明。领域 schema 因此只需回答"这是什么对象"，不必回答"怎样描述它"；装不进图的内容仍可进文档，代价是失去结构化检索。

三项贡献：

```text
1. Problem and Workload
   A formulation of shared accumulation by uncoordinated agent writers in
   research, and an intent-grounded workload: writer tasks and reader probes
   derived from six research intents with public task sources, plus the
   events of revision, deletion, new paper versions, and divergence.

2. PaperWeave Design (C1–C5), adapting classical mechanisms to agent writers
   Write mechanisms that give each kind of record (entities, concepts,
   contents, artifacts) a way for uncoordinated writers to agree: identities
   converging on external identifiers and names, with candidate duplicates
   decided by the writer; paper-stated content pinned to paper versions and
   revised against its anchors with full history; writer judgments
   coexisting in artifacts with their writers and inputs; and keyed artifacts
   co-edited with every edit versioned and attributable.
   Read side: a retrieval surface and access tools derived from the
   intents; a thin graph of identity anchors and references, with rich
   content in artifact documents.
   Write side: tool contracts that make contributions self-describing;
   staleness over declared and implicit inputs, flagged on read and reported
   at commit to the writer whose change caused it; keyed, versioned artifacts
   that writers check out, edit, and commit.

3. Evaluation
   Integrity: a falsifiable degradation claim under growing writers and
   writes against strong baselines, measured in store health, answer
   correctness, and the cost writers and readers pay to keep them, with
   per-mechanism ablations.
   Sufficiency: whether the store alone supports each research intent,
   relative to readers who may reread the papers.
   Parity: answer quality non-inferior to agent memory systems, with
   construction and use cost.
```

评测的三点：不去卷 memory 的性能，三点分开验证，最后归纳。

- **E1 完整性（主结果）：** 写者增多时库不退化，也不把维护的代价转嫁给读者和写者（后一半待确认，见“可证伪的现象”）。
- **E2 充分性：** 整理出的内容足以支撑研究意图，不必回读论文。
- **E3 对等：** 作为一种 memory，答题效果不逊于 agent memory 系统。

E1 与 E2 必须一起报告：一个什么都不存的库永远不会退化，“不退化”本身可以被钻空子，充分性是退化实验有意义的前提。

系统沿用现有原型。撤回在有据层是删除（附理由，历史保留），或由后来的证据加一条 `OPPOSES`；产物中的判断由后来者另起一节，不改写前人的；任何历史状态都可以重建（`as_of`）。对象的合并与拆分不实现，重复与误合并只测量，作为局限报告。

责任边界是立论核心，在新命题下更自然：组合的规划在 Agent 侧，Agent 把意图翻译成工具调用，翻译是否忠实单独评估；中间件校验提交的结构与引用、执行写入、持久化产物并记录谱系与状态变化。写入者之间有分歧时，库无权判断谁对，只负责让分歧可见、可追溯。我们管理 Agent 的写入，而不是替 Agent 判断。

随后以 Figure 2 介绍整体架构：多个 Agent 经 MCP 调用工具；读者经知识访问工具在检索面上定位、遍历与读取证据；每次写入经统一提交进入共享库；共同产物经检出、编辑、提交形成版本链。回看 Figure 1 的写入历史如何沿这条链路落地。评测结果出来后，在 intro 末尾补主要发现。

# Related Work and Positioning

本节围绕**独立 Agent 持续积累论文衍生知识与研究产物**这一领域工作负载定位 PaperWeave。一般背景是 Agent 从知识消费者成为生产者；本文具体研究的是学术知识积累中的身份、来源、研究操作及产物生命周期。重点说明相邻系统已有机制与这些任务要求之间的关系，不以功能名称的有无判定优劣。机制适配是否改善后续使用、收益是否抵偿成本，由评测回答。

## 动态 Agent Memory：Zep / Graphiti

**已有工作。** Zep（`2025-Zep`）通过 Graphiti 将持续到来的对话与其他输入组织为时态知识图，结合原始 episode、实体与事实、来源连接、时间有效区间及混合检索，为 Agent 提供上下文。当前公开 Graphiti 实现还支持自定义实体与关系类型、属性和端点约束、直接三元组写入，以及来源导航；Zep 的公开集成示例包含共享业务图和领域 ontology。因此，不能把这一路线概括为只保存个人交互、缺少身份或来源，也不能仅以“PaperWeave 有学术 schema”作为区别。

**区别在管理语义，不在功能有无。** 身份解析、来源、时态更新、自定义类型、混合检索与 MCP 接入，两者多有重叠，以下不按功能有无比较。不协调的多写者积累要回答的是：语义判断由谁做出，判断之后保留什么，后来的读者能看到什么。PaperWeave 与 Graphiti 的区别落在三处，每一处对应 E1 中一种可观测的失败模式，由同一工作负载上的实验检验。

**一、裁决位置。** Graphiti 在摄入时由系统内部完成语义裁决：实体身份先走精确名称、模糊匹配等确定性路径，未决部分交给内部 LLM；关系的去重与矛盾也由内部 LLM 判断，被判矛盾的旧关系按有效时间失效。直接写三元组的 `add_triplet` 跳过的是抽取，不是这些解析。当前的矛盾判断指令要求保留数值、日期与限定条件的差异，只在两条事实不能同时为真时判为矛盾，这是实际的防误判设计，应当承认；但判断仍在系统内部做出，提交内容的写者既看不到也无法确认。PaperWeave 的系统内部不做语义判断：可能重复的候选随提交结果退回写者，由写者复用已有对象或声明不同（`distinct_from`），判断记入提交，由形成者负责。不协调写入下，内部裁决一旦出错，例如合并了同名的不同数据集，或让一个合理的不同解释失效，错误不经任何人确认就进入共享状态；交回写者则把成本转为写入时的交互，并可能增加重复。两种做法的误合并率、重复率与交互成本都要测量，我们不主张交回写者天然更准确。

**二、有据层与解释层。** Graphiti 的来源是 episode 级的：一条事实可追溯到摄入它的那次输入。PaperWeave 进一步区分两类记录。有据层（实体身份与论文自身的陈述）对来源负责，引用绑定材料的内容版本与章节、行号锚点；分歧视为暂时的错误，修订须附原文锚点和理由，历史全部保留。解释层（Observation、写者对主张之间支持或反对的判断、派生产物）让不同形成者的判断并存：他人可以新增关系，但不能改写或删除。Graphiti 可以用声明节点、属性与外部规则表示类似的区分；差别在于 PaperWeave 把它作为写入契约执行。分歧在读取时是否足够可见，由评测检验。

**三、派生依赖与版本状态。** 研究工作会产出跨论文比较、可比性核查与综合报告等派生产物。PaperWeave 要求每份产物声明所用输入，形成可追溯的谱系；输入被修订、删除或材料变化后，读取该产物时会附带可能过时的提示；造成这一变化的写者在提交时也会收到受影响产物的清单。重算派生内容代价高且结果不确定，因此只提示、不自动维护，这是对视图失效这一经典做法的改编。每次写入都是带前后值的提交，任意历史状态都可以重建。据本次核查，Graphiti 的一等机制围绕关系的有效时间与系统时间，未见与声明输入、过时提示及提交祖先对应的机制。一条事实何时不再成立，与一份比较所依据的输入是否发生变化，是两种不同的维护要求。

**产物类型的位置。** Leaderboard、CompareSettings、Verify、Summarize、Generate 等产物类型是上述契约的载体：外部通用 Agent 完成语义工作，经 checkout、commit 提交带引用的文档；系统按类型契约校验结构与引用后，把它登记为产物的新版本，供后来者检索、引用和继续使用。类型清单本身不是贡献，同样的文档可以在通用框架的应用层组合出来；贡献在于这些类型执行的声明、修订与依赖规则。

**实验检验与主张边界。** 区别由实验检验，而不由特性表证明。评测中 Graphiti 作为基线，使用与 PaperWeave 相同的领域类型，承接相同的写者任务，测量误合并、分歧被失效、过时未被发现，以及下游答案的正确率。先导语料已包含对应情形：Informer 使用的 NOAA Weather 与后续论文常用的 Jena Weather 同名而不同；SCINet 的部分基线数值转录自 Informer；不同论文在不同条件下报告相互冲突的结果。若 Graphiti 在这些情形上不弱于 PaperWeave，我们相应缩小主张。Agent 承担语义执行，系统承担契约校验与产物管理；这不意味着系统接管完整科研过程、捕获全部隐性输入或验证科学结论。约束只作用于经系统入口提交的内容，通用 Agent 仍保留文件和 shell 工具，绕过行为另行审计。本文是学术知识积累的领域系统研究，采用并适配已有机制，跨领域有效性留作讨论。

英文候选段落：

```text
Zep and its open-source framework Graphiti organize evolving inputs into
temporal knowledge graphs, with entity resolution, episode-level provenance,
custom entity and edge types, hybrid retrieval, and an MCP interface; much of
this overlaps with PaperWeave. The difference lies in how each manages
uncoordinated writes. First, Graphiti adjudicates inside the system: an
internal LLM resolves the identities that deterministic rules leave open and
judges duplicate and contradicting facts, invalidating older ones by valid
time. PaperWeave makes no semantic judgment internally; it returns candidate
duplicates to the writer, who reuses them or declares the objects distinct,
and records that decision in the commit. Second, PaperWeave separates
source-grounded records, anchored to spans of a fixed paper version and
revised only with an anchor and a reason, from interpretations that coexist
with their writers. Third, derived artifacts declare their inputs; reads flag
artifacts whose inputs have since been revised, the commit that revised them
reports the affected artifacts to its writer, and every write is a versioned
commit from which any past state can be rebuilt. Graphiti tracks
when a fact stops holding; PaperWeave also tracks whether the basis of a
derived comparison has changed. Graphiti could emulate these behaviors with
custom types and application logic, so we compare the two empirically, on
the same workload and schema, by wrong merges, lost disagreements, undetected
staleness, and downstream correctness.
```

引用与核查依据：

- 论文使用 [`2025-Zep`](../references/refs.bib)，对应 [arXiv:2501.13956v1](https://arxiv.org/abs/2501.13956v1)；2025 年论文的实验与当前实现能力分开引证。
- 当前实现依据固定版本：[Graphiti 摄入与类型接口](https://github.com/getzep/graphiti/blob/964bb11d1e7020e3cc67fab244268b0736b6c219/graphiti_core/graphiti.py)、[矛盾判断指令](https://github.com/getzep/graphiti/blob/964bb11d1e7020e3cc67fab244268b0736b6c219/graphiti_core/prompts/dedupe_edges.py)、[关系时间处理](https://github.com/getzep/graphiti/blob/964bb11d1e7020e3cc67fab244268b0736b6c219/graphiti_core/utils/maintenance/edge_operations.py)，以及 [Zep 共享图与 ontology 用法](https://github.com/getzep/zep/blob/cfa2ab2bbc3c7085d636479b719bcf64608162cc/ingestion/README.md)。Zep 仓库是示例与集成，不包含当前云服务内部实现，未公开能力不作否定判断。
- 详细代码证据、工程状态和措辞边界见本地暂存的[实现比较笔记](../references/papers/narrative-adjust/shared-agent-memory/2025-Graphiti/implementation-comparison-paperweave.md)。该目录不入 Git；这里保留公开固定版本链接，使核心比较不依赖本地副本。

# 后续章节大纲

组织方式借鉴 AgenticScholar：一套工作负载规约作为全文中枢，复用三处：related work 能力矩阵的行、机制设计的需求来源、评测小节的组织轴。中枢以六类研究意图 I1–I6 为根，由四部分组成，与评测草案对齐：**意图**（写入者任务与读者探针的共同来源）、**写入者模型**（伪用户：每个写入者带身份与背景、一个意图任务，轮流写）、**事件类型**（误读后修订、撤回、论文新版本、写入者分歧、共同产物的并发编辑、回看历史状态）、**读者探针**（按 I1–I6，落在多写者交汇处）。挑战编号、机制编号、评测小节一一对应；Figure 1 的场景在评测中完整重演。Related work 前置到 intro 之后，直接叙述我们与各路线的区别。

2. **Related Work and Positioning.** 先用一段简述中枢规约，作为能力矩阵的行。主体按机制组织：每个挑战一段，依次写经典前身、Agent 场景下的改变、我们的设计。底稿见讨论记录 §2–§3。反面参照是 truth discovery 与按引用排名：两者都由系统裁决，我们不这样做。随后按路线补充与相邻系统的区别：
   - 学术知识图谱与文献系统：以文档为中心；ORKG 虽是众包多写者，但写入者是人、靠模板整理，不管理 Agent 的使用产物。
   - 多写者共享知识库：Wikidata 固定数据模型（item、statement、qualifier、reference、rank），领域属性由社区逐步提议；相互冲突的值可以带来源并存。这是我们"元模型与领域词表分层""分歧并存"的最近先例，要正面说明差别：写入者是 Agent、产物是声明输入的派生文档、过时随依赖标出。
   - Agent Memory，含多 Agent 共享记忆：Zep/Graphiti 的比较已在上文展开，承认其身份解析、来源、时态更新与领域扩展能力；差异落在裁决位置（系统内部 LLM 裁决，或交回写者）、有据层与解释层的划分、派生依赖与版本状态，产物类型只是这些契约的载体。Graphiti 作为实验基线，在同一工作负载与同一套类型上比较。其他系统逐项核实，不概括为均缺少身份、来源或版本。
     - ShareMem（跨用户经验共享，精读笔记在 `references/papers/narrative-adjust/shared-agent-memory/2026-ShareMem/`）是与本文设定最近的 memory 工作，可从三方面引用：
       - 它按**归属**把偏好与经验分开，我们按**权威**把有据层与解释层分开，两者是平行的洞见；
       - 它的失败审计说明，来源标签和明确指令挡不住 Agent 误用他人的值，可作为“冲突与过时要有结构约束、不能只靠提示”的外部证据；
       - 它的共享池由内部 LLM 覆盖改写，不记出处、不留历史，正是过程性经验与研究知识要求不同的例子。
   - 语义算子系统（AgenticScholar、LOTUS 等）：LLM 内化于算子；我们把语义工作外置、契约内化。
   - provenance 与版本化数据管理（`2026-Git4Data`、`2013-GraphSnapshot` 等）：管数据版本；我们管多写者积累的知识状态。
   - ontology engineering 与 schema induction：与本文正交，说明领域词表问题有人在做、不是我们的贡献。

   能力矩阵区分原生支持、组合支持、需外部推理。上述多写者知识库与多 Agent 记忆的文献是否已在 `references/` 中，待核实。
3. **Problem and Workloads.** 把中枢规约展开为可评测的形式：六类意图及其任务来源与必要信息（取自 intents 分解），写入者模型、事件类型、读者探针，各自给出具体输入、所需输出、数据状态与操作序列。显式写出几条假设：不协调是语义上的而非并发事务；领域词表给定；库不判断谁对（可问责而非权威，按对象类别与 `stated_by` 规定一致方式）；起点只有论文原文与外部标识。明确责任边界。
4. **System Overview.** Figure 2：共享库、产物版本与提交历史的整体关系；用 Figure 1 中一段写入历史端到端走查各部件。
5. **Accumulation Meta-Model.** Entity / Concept / Content / Artifact 主类与系统记录；写入机制在每一类上的效果放在第 7 节；身份规则（精确键、标识、重复与歧义的处理）、材料引用、来源与派生谱系；薄图、厚文档的分工；从意图推出的检索面（描述面与检索子集、关系为何进入检索面）。CS 论文的领域词表作为实例单列（回应 C1、C2、C5）。
6. **Tool Contracts and Artifact Persistence.** 知识访问工具（search、get、traverse、read_evidence）的契约：混合检索中关系的作用、有界视图与分页、分歧与过时随结果返回（回应 C5）。产物类型的契约：产物是按类型检查的版本化文档，写者经 checkout / commit 检出与检入，中间件校验文档结构与引用、保存各版本、记录所用的节点，使贡献自描述、可复查、可继续组合（回应 C2）。以意图的数据流说明两类契约如何组合。
7. **Versions, Revision, and Shared Artifacts.** 统一提交与完整变更记录；有据层的修订（附锚点与理由）与解释层的并存；撤回；核对写成 Verify 产物；共同产物的检出、检入与版本；基于依赖的过时提示（读取时标记，提交时告诉造成变化的写者）；历史访问（任何历史状态都可以重建）。区分产物输入谱系与提交祖先（回应 C3、C4）。
8. **Implementation.** 现有原型：属性图与材料存储、graph-doc 与 Commit、graph-vc 统一写入与版本、工具契约到 Cypher 与后端的映射、MCP 接入。
9. **Evaluation.** 三个命题，细节见评测草案与评测 V3：

   | 实验 | 回答什么 | 怎样测 |
   | --- | --- | --- |
   | E1 完整性（主结果） | 写者增多时库不退化 | 多写者代价 $\Delta_{\text{arm}} = Y(4) - Y(1)$：同一批论文由 1 个与 4 个伪用户写入，比较库健康度与探针正确率；按对象类别分别报告，知识流失率与探针正确率同为主指标 |
   | E2 充分性 | 库中内容足以支撑意图 | 按 I1–I6 分别报告 $\rho_I = \mathrm{Acc}_{\text{store\_only}}/\mathrm{Acc}_{\text{with\_papers}}$；同时检验“由意图推导读取面”这一设计方法 |
   | E3 对等 | 作为 memory 不吃亏 | 对 Graphiti 做非劣效检验，阈值 $\delta$ 事先声明；附构建与使用的成本账 |

   - **E1：** 重复率按对象类型拆开，检验“外部锚点越弱、退化越多”；探针落在多写者交汇处；注入事件即 Figure 1 的重演。审计 DAG 只用系统写入时不检查的项作为 A3 胜过对照组的证据。
   - **消融：** 去掉查重（身份候选）、写入时提示（`affected_artifacts` 与 `related_artifacts`）、读取时的过时标记（`_stale`）、共同编辑，各一项，放在 E1 中。
   - **E2：** 充分性要按意图拆开：哪些意图库能独立支撑，哪些仍需回读论文。一个什么都不存的库永远不会退化，所以 E2 与 E1 一起报告。
   - **E3：** 不跑 LongMemEval、DMR 等对话记忆基准，它们不是本文的工作负载。主张写成带阈值的非劣效，而不是“接近”。成本账：构建成本前移、按使用者摊销，盈亏点 $N^* = C_{\text{build}}/(c_{\text{base}}-c_{\text{ours}})$；baseline 给相同预计算预算。
   - **对照组：** A0 文件 + Git（最强配置）、A2 同一 schema 的裸 Neo4j + Cypher、A3 完整系统、A4 Graphiti；A1 RAG 只用于 E2。A0 拿到与 A3 工具说明对等的约定文档与模板（文字对等，机制不同）：schema 的文字相同，但没有任何执行。A2 与 A3 共用 schema 与存储，二者之差只来自机制；A0 与 A3 之差是机制加上图层；与 A4 的比较混有 schema 的作用，需如实标出。
   - **起点与金标准：** 起点只有论文原文与外部标识，种子在各组之间相同，且不与金标准重合。有据层以原文锚点为金标准；解释层不测真值，只测分歧是否保留、读者是否看得到。
   - **schema 覆盖不足作为观测量：** 记录写入内容装不进类型的次数与去向（Artifact 文档、描述字段或丢弃），不作为要解决的问题。
   - 结果可能为负，例如 A0 始终不输；那时报告文件加 Git 足够的区间，收窄主张。
10. **Lessons Learned.** 责任边界的划分、身份规则粒度的取舍、分歧并存的代价、版本记录的开销等实务经验。
11. **Conclusion.** 实验完成后收束主要发现、适用范围与局限。

# 备忘

通用接口暴露方式

General-purpose Agent → Agent-facing Access Interface → PaperWeave DBMS

```text
Agent-facing Interface
├── MCP
│   ├── tools
│   ├── resources
│   └── structured results
│
└── Skills
    ├── capability descriptions
    ├── usage semantics
    └── workflow instructions
```
