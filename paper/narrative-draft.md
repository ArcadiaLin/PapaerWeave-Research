# Collaborating without Coordinating: Data Management for Knowledge Accumulated by LLM Agents

（标题暂定，2026-10-10。）标题按通用的问题来提，摘要再把主张收回到实证范围（科学文献）；系统名保留 PaperWeave，名字本身也标明了实证领域。

落选的候选：

- *PaperWeave: Shared Accumulation of Paper-Derived Knowledge by Uncoordinated Agents*：旧标题，只讲场景，没有主张。
- *PaperWeave: Collaborating without Coordinating — Data Management for Scientific Knowledge Accumulation by LLM Agents*：领域限定写进标题，偏长。
- 改系统名（Cairn、SourceWeave 等）：比喻类名字撞名严重，直白类名字不如 PaperWeave 可信，作罢。

"Collaborating without Coordinating"会让审稿人期待协调规避（I-confluence、CALM）式的不变式分析，正文需要接住。

# 论文草稿

中文记叙事意图；英文代码块留候选短句和用语。两者都用于推进草稿，随设计继续调整。

> **2026-10-10 修订：** 按 2026-10-09 商定的核心命题（互不协调的写入者共同积累，shared accumulation by uncoordinated writers）重写 Introduction 与大纲。旧版以单个研究者的纵向/横向复用为动机，见 Git `df7fb2a`。评测设计见 [`docs/designs/v2/evaluation_draft.md`](../docs/designs/v2/evaluation_draft.md)。

# Abstract

（暂定，2026-10-10。）先不写评测数字，结果用定性表述；终稿有了实验结果再决定是否补数字。

宏观主线是"私有记忆 → 没有主人的共享知识 → 可问责"：

- **Agent 从知识的消费者变成生产者。** 它们读、比较、核查时留下的记录，别的 Agent 可以接着用。
- **暗中回应 agent memory 的数据管理研究**（如 GEM 的 *Is Agent Memory a Database?*、*Are We Ready For An Agent-Native Memory System?*）：它们的记忆属于一个 Agent、服务一个主体，最新的写入可以代表真值，过时就是旧值被新值取代。共享知识没有主人，这个前提不再成立：新写入不一定更对，分歧可能合理，依据会在脚下变化。摘要只陈述这一点，不点名反驳。
- **答案是可问责而不是权威：** 规则能判定的地方收敛，合理分歧连同依据一起保留，可能过时的地方暴露出来。
- 机制压缩成一句"经典机制的改造"；"不变式 × 合并"的分类留给引言与设计章节，摘要不展开。
- **照顾主题领域：** 数据模型一句（有据层与解释层）对应 *Data models and semantics*；实体解析直接写 entity resolution，对应 *Data integration*。实际机制是存储层给出候选（id、alias、语义近邻）、由写入者在写入时判定，不做匹配算法，也没有 merge/split；摘要不展开，正文讲清。过时机制只标记不重算，所以用 view invalidation 而非 view maintenance。
- **收回通用性：** 标题是通用的，摘要在提出原则之后用一句话把研究限定到科学文献，并给出理由（问题在这里尖锐且可核查），实验结论也只对这个领域陈述。机制按领域无关设计，泛化留到讨论部分，不进摘要。

```text
LLM agents now both use and produce knowledge: as they read, compare, and verify, they can build on what earlier agents recorded and leave records for later ones. Agent memory systems largely manage state that belongs to one agent, so its latest write can stand for the truth. When many agents share one long-lived store, no single agent’s word is authoritative: agents may work without coordinating or legitimately disagree, and the sources they draw on change. We argue that such a store cannot decide who is right, but must keep every write accountable: converging what rules can decide, preserving disagreement with its grounds, and exposing what may be stale. We study this problem in scientific literature, where it is acute and checkable, and present PaperWeave, a data management system whose data model separates source-grounded records, revised with full history, from interpretations that coexist with their provenance. It adapts classical entity resolution, view invalidation, and data versioning to agent writers, preserving the store's integrity as uncoordinated writes accumulate. Experiments on an intent-grounded workload show that PaperWeave degrades markedly more slowly than file-based, graph, and agent-memory baselines as agents and updates accumulate.
```

备选方案，这个方案前部分比较贴近 scientific 和

```text
LLM agents increasingly perform literature-based research tasks. Accumulating
their outputs in a long-lived shared store would let later agents build on
prior work. Existing agent memory systems, however, are largely designed for a
single owner and resolve conflicting writes by recency or internal judgment.
When writers do not coordinate, this assumption fails: absent appropriate
mechanisms, new content often remains unlinked to existing content, and store
quality degrades as writes accumulate. We argue that a shared store should not
adjudicate correctness but should keep every write accountable: attributable to
its writer and traceable to its evidence and prior content. We present
PaperWeave, a data management system for paper-derived knowledge. It separates
what a paper states from what a writer judges: source-grounded records hold one
value, revisable by any writer with a source anchor and a reason, while
interpretations are attributed to their writers and coexist without
adjudication. PaperWeave adapts entity resolution, view invalidation, and data
versioning to agent writers to maintain accountability as uncoordinated writes
accumulate. We design an evaluation on an intent-grounded workload to measure
store integrity and downstream answer accuracy as the number of writers grows.
```

摘要中出现的 agent-memory 对照组（A4）尚未写入评测草案。

# Introduction

## Why：

先讲三点背景：

1. **通用 Agent 参与研究：** 读论文、抽取方法与实验、比较、形成判断与报告。这些产物持续积累，后续工作值得在它们之上继续。
2. **积累是共享的，写入者互不协调：** 同一个人或研究组在几个月里开出大量 session，彼此上下文不通；不同项目、不同成员的 Agent 各自读到同一批论文。愿景是一个公共平台（paper4agents）。共享库是写入者之间唯一的通道，读者往往是当初不在场的陌生人。
3. **单写者不需要数据库：** 一个 Agent 在一个项目里复用自己的产物，文件加 Git 作为基线，可能是最强的（尤其是在大厂都在卷这种场景下的模型能力的背景下，与这个模式做竞争没有必要），可能已经够用。数据库的理由来自许多写入者长期写同一个库，这也是 DBMS 的经典理由：共享数据、完整性、多用户。

```text
Background: General-purpose agents read, extract, compare, and judge papers,
and their outputs accumulate.
Setting: The accumulation is shared. Many agents and sessions that never
coordinate write to one long-lived store, and later readers were not there
when it was written.
Not the setting: One agent reusing its own work within one project, where
files and Git are a strong baseline and may suffice.
```

**为什么是论文知识（暂定）：** 论文领域最初是项目起点的预设，多写者命题是后来才确立的；但选它的理由可以落在数据本身的性质上，而这些性质正好让问题既尖锐又可评测：

- **写入高度重叠：** 引用呈长尾分布，少数热门方法、数据集和 benchmark（如 PatchTST、ETTh1）几乎被每个项目、每个 Agent 反复读到，同一对象被许多写入者各写一遍，是重复与冲突的高发区（C1、T1）。
- **身份难判，但有外部锚点：** 别名、变体、子集（ETT 与 ETTh1、同一方法的不同配置）让身份判断不平凡；arXiv ID、DOI、代码仓库与数据集主页等外部标识又能给去重与误合并提供部分真值。
- **分歧与变化自然发生：** 结果依赖条件，读者可能误读；arXiv 版本更新会改数值，还有勘误、撤稿与复现不一致。C3 的事件不必全靠人工注入。
- **有客观的未来可对照：** 按时间切分，用 $t_0$ 之前的论文建库，以之后论文实际选用的 baseline、数据集与指标为金标准（L4）。
- **数据公开、金标准现成：** TDMS、AxCell、SciREX、LEGOBench、OpenAlex 等，满足可复现要求。
- **知识寿命长、重读成本高：** 每个研究 Agent 从头重读同一批论文，冗余大，是摊销的前提（T2）。

对照其他候选：代码库知识本身就是真值且已由 Git 管理，文件加 Git 基线大概率胜出；企业文档有多写者性质但数据私有、无公开金标准；个人助理记忆本质上是单写者；通用百科已有 Wikidata；医学文献性质相近，但金标准构建需要专业知识，可作推广讨论。

**主张范围（暂定）：** 写成领域系统论文。主张与实验结果只针对论文派生知识；元模型与领域词表分层，因此在 Discussion 中说明机制在设计上与领域无关，推广作为讨论而非主张。"写入高度重叠"是这一选择最关键的支撑，需在选定语料上核实（例如热门方法与数据集被多少篇论文参与）；若重叠不足，T1 测不出退化。

参照 AgenticScholar 的数据管理问题引入：
**学术知识系统管理文档与人工整理的知识，Agent Memory 管理单个 Agent 的交互历史；由许多互不协调的 Agent 持续写入的共享派生知识，尚无人管理。**

再引出可证伪的现象（对应评测 T1）：没有身份、契约、来源与版本约束时，共享积累会随写入者数和写入量增长而**退化**：

- 同一对象被建成多个节点（重复），或不同对象被并成一个（误合并）；
- 产物引用的记录不存在或已改变（悬空引用）；
- 两个写入者对同一结果给出不同读法，后写的静默覆盖前写的（冲突未被发现）；
- 来源被修订或撤回后，依赖它的比较与报告没人知道已经过时。

与此同时，内容按各个写入者自己的目的、措辞和粒度存放，换一个目的的读者未必找得到。下游读者拿到的答案随之出错，而且错得不显眼。

```text
Without identity, contracts, provenance, and versions, shared accumulation
degrades as writers and writes grow: duplicate and wrongly merged entities,
dangling references, unnoticed conflicts, and stale artifacts. Content stored
on each writer's own terms is hard to find for readers with other purposes.
Downstream answers become wrong without looking wrong.
```

## Figure 1：多写者共享积累及其退化

放在 intro 的场景图，让读者看到：（a）几个互不知情的写入者在时间线上交错，读到重叠的论文；（b）同一段写入历史落进两种库，一种无约束，一种有约束；（c）项目工作从共享库 fork、推回。五个 challenge 都要能指到图上的具体元素。这个场景同时是评测 T1 的设定，评测中完整重演。

```text
                                         time ──────────────────────────────────────────────────────▶

┌─ Writers ── uncoordinated, each unaware of the others ─────────────────────────────────────────────┐
│                                                                                                    │
│   W1 · proj X     reads A, B ──▶ extract ──▶ comparison table ───────────────┐                     │
│   W2 · proj Y              reads B, C ──▶ 2nd reading of B's result ─────────┤   B: read twice,    │
│   W3                                  reads D (revises B) ──▶ revision ──────┤   independently     │
│   R  · later reader (not present at writes)          "which method is best on ETTh1@720?"     (C5) │
└────────────────────────────────────────────────────────────────────────────────────────────────────┘

                                                   │ same write history
                    ┌──────────────────────────────┴─────────────────────┐
                    ▼                                                    ▼
┌─ (a) Unconstrained store ────────────┐    ┌─ (b) Identity · Contracts · Provenance · Versions ─────┐
│                                      │    │                                                        │
│   [PatchTST] [PatchTST′]             │    │   [PatchTST] ◀── W1, W2 converge on one identity  (C1) │
│   duplicate nodes               (C1) │    │   B: x vs y flagged → re-read anchor, revise      (C3) │
│   B: y silently overwrites x    (C3) │    │   cmp table flagged stale: input B revised by D   (C3) │
│   cmp table → old B, no flag    (C3) │    │   references resolve to pinned versions           (C2) │
│   report ──▶ [record gone]           │    │   R: answer + disagreement + staleness notice          │
│   dangling reference            (C2) │    │                                                        │
│   R: wrong answer,                   │    │                                                        │
│      and it looks right              │    │                                                        │
└──────────────────────────────────────┘    └────────────────────────────────────────────────────────┘

┌─ Project work ─────────────────────────────────────────────────────────────────────────────────────┐
│                                                                                                    │
│   proj X   ──fork @v3──▶ x1 ──▶ x2 ──▶ push ──┐                                                    │
│                                               ▼                                                    │
│                           shared store    v3 ──▶ v4 ──▶ v5                                         │
│                                               ▲                                                    │
│   proj Y        ──fork @v4──▶ y1 ──▶ push ────┘   conflict with x2: reconcile, not overwrite  (C4) │
└────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

```text
Caption:
    Figure 1: Uncoordinated writers accumulating paper-derived knowledge.
    Writers with separate projects read overlapping papers at different times
    (top). The same write history lands in an unconstrained store, which
    degrades, and in a store that enforces identity, contracts, provenance, and
    versions, which keeps disagreement and change visible (middle). Project
    work forks from the shared store and pushes results back (bottom).
```

Band 1（写入者）：三个写入者各自做自己的事，互不知道对方存在，而且各带不同的研究意图（intent）。W1 为项目 X 比较实验结果（I3），读 A、B，抽取并做比较表；W2 为项目 Y 核查一条主张（I5），读 B、C，对 B 的同一个结果给出不同读法；W3 后来读到 D，D 修订了 B 的结论，W3 提交了这次修订。最后一个陌生读者 R 带着另一个意图来用这个库：它要找到的内容是别人为别的目的写下的。写侧行为包括读、抽取、比较、判断、修订、撤回、fork、推回；读侧强调读者不在写入现场，也不知道内容当初是怎样组织的。

Band 2（共享库）：同一段写入历史分别落进两种库。左栏无约束：重复节点、静默覆盖、未标记的过时、悬空引用，R 得到错误答案且看不出来。右栏有约束：身份收敛；B 的结果属于有据层，两种读法被标为冲突，回到原文锚点重读后记为一次修订，旧值留在历史中；依赖已修订输入的产物被标为可能过时；引用指向固定版本。解释层的判断（例如 W1、W2 各自对"哪个方法更好"的结论）则带着来源并存，不被裁决。图中数值只作示意。

Band 3（项目工作）：项目 X、Y 分别从共享库的某个状态 fork，在隔离的基线上工作，再把成果推回；Y 推回时与 X 已推回的内容冲突，需要处理而不是覆盖。

五个 challenge 在图中的落点：C1 对应 PatchTST 的重复与收敛；C2 对应比较表与报告所带的输入、条件和引用；C3 对应 B 的两种读法、W3 的修订与比较表的过时提示；C4 对应 Band 3 的 fork、推回与冲突；C5 对应 R 的问题：答案分散在 W1 的比较表与 W2、W3 写下的记录中，R 要在不知道它们如何组织的情况下找到它们。

## 从场景到问题与 Challenges

```text
How can a long-lived store accumulate paper-derived knowledge and artifacts
written by many agents that do not coordinate, so that later readers can
still find, trust, and build on it?
```

问题的几条边界，在 Problem 节显式写出：

- **不协调指语义上互不知情，不是并发事务。** 写入者不知道别人写过什么、怎么理解的；写操作本身可以轮流执行，原子性与隔离交给后端事务，不是本文的问题。
- **领域类型词表是给定的。** 我们假定写入者共享一套领域类型（Paper、Method、Dataset、Experiment 等）；词表的设计与演化属于 ontology engineering 与 schema induction，与本文正交。我们研究的是共享积累的完整性语义，领域词表是它的一个参数；本文为 CS 论文给出一个实例。
- **库不判断谁对：可问责，而非权威。** 写入者之间有分歧时，语义判断由 Agent 做；中间件只让分歧可见、可追溯、可被后来者处理，不按使用或引证次数排名。权威不在库里，而在库所指向的外部参照中：固定版本的论文原文与外部标识（arXiv ID、DOI、OpenAlex、Wikidata 等）。按有无外部参照分两层：
  - **有据层**：实体身份与 `stated_by: paper` 的记录（Experiment、Claim、Contribution）。对错指是否忠实于原文，可对照锚点检验；分歧是暂时的错误，以附锚点与理由的修订解决，旧值留在历史中。
  - **解释层**：Observation、Agent 认为的贡献与正反关系、全部 Artifact。没有单一真值，判断带着来源并存。
- **库从论文原文开始。** 不预设权威快照：外部参照随时可取，有据层与解释层由写入者读论文后构建。冷启动可以从公开注册表引导身份锚点，但论文内容层面没有现成来源，正是 Agent 的工作。
- **主张限于论文派生知识。** 机制设计与领域无关，但评测与结论只覆盖本领域；推广留给 Discussion。

五个困难，各自接回图中的元素。C1–C4 在写侧，回答 trust 与 build on；C5 在读侧，回答 find：

1. **独立写入下的身份：** 不同写入者在不同时间写同一个方法、数据集或结果，要收敛到同一身份，同时不能把不同对象误并。身份规则必须显式、可检查、对所有写入者一致；粒度定在哪里（例如方法变体是否单独建节点）属于领域实例化。
2. **自描述的贡献：** 写入者之间没有共享上下文，库是唯一的通道。产物必须自带条件、证据和输入依赖，不在场的读者才能使用或复查。
3. **分歧与变化：** 写入者之间有分歧，会误读后修订，会撤回；源材料也会变。库要暴露冲突与过时，既不静默覆盖，也不整批拒绝：有据层的分歧回到原文修订并保留历史，解释层的判断带着来源并存。
4. **隔离地工作，共享地交付：** 项目工作需要一个不受他人写入干扰的稳定基线，成果要能推回共享库而不破坏它，并且能回到任一历史状态。
5. **跨写入者的可发现性：** 一个写入者为某个目的写下的内容，要能被另一个目的的读者找到。读者不知道写入者当时的措辞、粒度和组织方式，又受上下文所限，需要把结构导航与语义检索组合起来，取得有界的视图。

```text
C1. Converge identities across independent writers without wrong merges.
C2. Make contributions self-describing for readers who were not there.
C3. Keep disagreement and change visible, neither overwritten nor rejected.
C4. Isolate project work while delivering results back to the shared store.
C5. Let readers with one purpose find what writers with another stored.
```

挑战编号暂按提出顺序；正文是否按 find → trust → build on 重排，待定。

## Claim + Contributions：总体方法

一个面向外部通用 Agent 的共享知识积累中间件：Agent 经 MCP 读写。写侧，中间件对身份、契约、来源与版本施加约束，使互不协调的写入在长期积累中不退化；读侧，它提供从研究意图推出的检索面与访问算子，使别人写下的内容能被找到。

```text
We propose a middleware for shared accumulation of paper-derived knowledge
by uncoordinated agents. On the write side, it enforces identity, contracts,
provenance, and versions, so that the store keeps disagreement and change
visible instead of degrading as writers and writes grow. On the read side,
it offers an intent-derived retrieval surface and access operators, so that
readers can find what others stored for other purposes.
```

工作负载的根：**六类研究意图 I1–I6**（发现工作与方法、理解机制与条件、组织结果并判断可比性、综合路线与发现、核查主张、取得实现资源），各有公开任务作为依据（PaperFindingBench、QASPER、TDMS-IE、ScholarQA-CS、ArxivDIGESTables、SciFact、CORE-Bench 等），分解见 `docs/designs/v2/intents_decompose.md`。它们在本文中有三种用途：

- 生成写入者的任务：不同意图的写入者以不同粒度和关注点写到同一批对象上，这正是 C1、C3 压力的来源；写入者数 $K$ 由此操作化为任务意图的多样性。
- 生成陌生读者的探针：探针有任务依据，不是为本系统量身定制的。
- 决定检索面：对象的哪些字段与关系必须可检索，由读需求推出。

意图在这里提供了工作负载。"我们的算子支持这六类意图"本身不构成贡献，因为通用图库配上合适的查询同样可以支持。

定位：**经典机制的选择与改造。** 每项机制都有经典前身：实体解析与自然键（C1）；provenance、W3C PROV 与 nanopublication（C2）；物化视图失效、真值维护，以及 Trio、CRDT 多值寄存器、Wikidata rank 式的值并存（C3）；check-out/check-in、乐观校验与数据版本管理（C4）；dataspaces 的按需整合、数据库上的关键词搜索与混合检索（C5）。我们主动引证这些前身，不用主张新的并发、provenance 或版本理论。贡献在于说明 Agent 写入者要求的改变，并用实验证明哪些机制仍然必要。需要改变的有五点：

- 裁决在写入时交还写入者；
- 错误是语义性的且读起来通顺，所以保留来源与分歧比保证正确更重要；
- 派生内容重算昂贵且不确定，所以只标记过时，不做自动维护；
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
   events of revision, retraction, divergence, and branching.

2. PaperWeave Design (C1–C5), adapting classical mechanisms to agent writers
   Read side: an accumulation meta-model (identity, provenance, artifact
   semantics independent of the domain vocabulary) with a retrieval surface
   and access operators derived from the intents; a thin graph of identity
   anchors and references, with rich content in artifact documents.
   Write side: operator contracts that make contributions self-describing;
   source-grounded records revised against their anchors with full history,
   interpretive judgments coexisting with their sources; dependency-based
   staleness; versioned shared and project states with fork and push.

3. Evaluation
   A falsifiable degradation claim under growing writers and writes against
   strong baselines (files + Git, RAG, the same schema without constraints),
   per-mechanism ablations, and amortized construction/use cost.
```

写侧版本与修订机制的工程落点很小，系统沿用现有原型：

- 解释层的并存已经成立：Observation 没有自然键，Artifact 每次调用都新建一个。
- 有据层的修订需放宽 `docs/designs/v2/commit_contract.md` §5，该节目前把内容变化一律视为冲突并整批拒绝。放宽后，附锚点与理由的修订被接受，锚点与理由存入 graph-vc 提交的 `message` / `meta`。
- `_stale` 增加"输入已修订"这一原因。
- 撤回沿用删除变更集或 `revert`，解释层的撤回写一条 `OPPOSES`。
- 对象的合并与拆分不实现，作为局限报告。

责任边界是立论核心，在新命题下更自然：组合的规划在 Agent 侧，Agent 把意图翻译成算子计划，翻译是否忠实单独评估；中间件校验计划结构与引用、执行操作、持久化产物并记录谱系与状态变化。写入者之间有分歧时，库无权判断谁对，只负责让分歧可见、可追溯。我们管理 Agent 的写入，而不是替 Agent 判断。

随后以 Figure 2 介绍整体架构：多个 Agent 经 MCP 调用算子契约；读者经访问算子在检索面上定位、遍历与读取证据；每次写入经统一提交进入共享库；项目从共享库的固定状态 fork，在隔离的状态上工作并推回。回看 Figure 1 的写入历史如何沿这条链路落地。评测结果出来后，在 intro 末尾补主要发现。

# Related Work and Positioning

本节围绕**独立 Agent 持续积累论文衍生知识与研究产物**这一领域工作负载定位 PaperWeave。一般背景是 Agent 从知识消费者成为生产者；本文具体研究的是学术知识积累中的身份、来源、研究操作及产物生命周期。重点说明相邻系统已有机制与这些任务要求之间的关系，不以功能名称的有无判定优劣。机制适配是否改善后续使用、收益是否抵偿成本，由评测回答。

## 动态 Agent Memory：Zep / Graphiti

**已有工作。** Zep（`2025-Zep`）通过 Graphiti 将持续到来的对话与其他输入组织为时态知识图，结合原始 episode、实体与事实、来源连接、时间有效区间及混合检索，为 Agent 提供上下文。当前公开 Graphiti 实现还支持自定义实体与关系类型、属性和端点约束、直接三元组写入，以及来源导航；Zep 的公开集成示例包含共享业务图和领域 ontology。因此，不能把这一路线概括为只保存个人交互、缺少身份或来源，也不能仅以“PaperWeave 有学术 schema”作为区别。

**区别在管理语义，不在功能有无。** 身份解析、来源、时态更新、自定义类型、混合检索与 MCP 接入，两者多有重叠，以下不按功能有无比较。不协调的多写者积累要回答的是：语义判断由谁做出，判断之后保留什么，后来的读者能看到什么。PaperWeave 与 Graphiti 的区别落在三处，每一处对应 T1 中一种可观测的失败模式，由同一工作负载上的实验检验。

**一、裁决位置。** Graphiti 在摄入时由系统内部完成语义裁决：实体身份先走精确名称、模糊匹配等确定性路径，未决部分交给内部 LLM；关系的去重与矛盾也由内部 LLM 判断，被判矛盾的旧关系按有效时间失效。直接写三元组的 `add_triplet` 跳过的是抽取，不是这些解析。当前的矛盾判断指令要求保留数值、日期与限定条件的差异，只在两条事实不能同时为真时判为矛盾，这是实际的防误判设计，应当承认；但判断仍在系统内部做出，提交内容的写者既看不到也无法确认。PaperWeave 的系统内部不做语义判断：可能重复的候选随提交结果退回写者，由写者复用已有对象或声明不同（`distinct_from`），判断记入提交，由形成者负责。不协调写入下，内部裁决一旦出错，例如合并了同名的不同数据集，或让一个合理的不同解释失效，错误不经任何人确认就进入共享状态；交回写者则把成本转为写入时的交互，并可能增加重复。两种做法的误合并率、重复率与交互成本都要测量，我们不主张交回写者天然更准确。

**二、有据层与解释层。** Graphiti 的来源是 episode 级的：一条事实可追溯到摄入它的那次输入。PaperWeave 进一步区分两类记录。有据层（实体身份与论文自身的陈述）对来源负责，引用绑定材料的内容版本与章节、行号锚点；分歧视为暂时的错误，修订须附原文锚点和理由，历史全部保留。解释层（Observation、写者对主张之间支持或反对的判断、派生产物）让不同形成者的判断并存：他人可以新增关系，但不能改写或删除。Graphiti 可以用声明节点、属性与外部规则表示类似的区分；差别在于 PaperWeave 把它作为写入契约执行。分歧在读取时是否足够可见，由评测检验。

**三、派生依赖与版本状态。** 研究工作会产出跨论文比较、可比性核查与综合报告等派生产物。PaperWeave 要求每份产物声明所用输入，形成可追溯的谱系；输入被修订、删除或材料变化后，读取该产物时会附带可能过时的提示。重算派生内容代价高且结果不确定，因此只提示、不自动维护，这是对视图失效这一经典做法的改编。每次写入都是带前后值的提交，任意历史状态可以重建，提交可以撤销；项目从固定状态分出并推回的机制已设计，尚未实现。据本次核查，Graphiti 的一等机制围绕关系的有效时间与系统时间，未见与声明输入、过时提示及提交祖先对应的机制。一条事实何时不再成立，与一份比较所依据的输入是否发生变化，是两种不同的维护要求。

**研究操作的位置。** Extract、Check、MatrixConstruct、Generate 等 MCP 操作是上述契约的载体：外部通用 Agent 完成语义工作，提交声明的输入、参数与结果；系统校验结构与引用后，把结果登记为产物，供后来者检索、引用和继续使用。操作清单本身不是贡献，同样的操作可以在通用框架的应用层组合出来；贡献在于这些操作执行的声明、修订与依赖规则。

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
artifacts whose inputs have since been revised, and every write is a
versioned commit from which any past state can be rebuilt. Graphiti tracks
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

组织方式借鉴 AgenticScholar：一套工作负载规约作为全文中枢，复用三处：related work 能力矩阵的行、机制设计的需求来源、评测小节的组织轴。中枢以六类研究意图 I1–I6 为根，由四部分组成，与评测草案对齐：**意图**（写入者任务与读者探针的共同来源）、**写入者模型**（每个写入者带一个意图任务，轮流写，两条写路径：直写共享库，或 fork → 项目工作 → 推回）、**事件类型**（误读后修订、撤回、材料变化、写入者分歧、分支与推回、回看历史状态）、**读侧阶梯 L0–L4**（存储语义、关联检索、组合、有状态工作、端到端）。挑战编号、机制编号、评测小节一一对应；Figure 1 的场景在评测中完整重演。Related work 前置到 intro 之后，直接叙述我们与各路线的区别。

2. **Related Work and Positioning.** 先用一段简述中枢规约，作为能力矩阵的行。主体按机制组织：每个挑战一段，依次写经典前身、Agent 场景下的改变、我们的设计。底稿见讨论记录 §2–§3。反面参照是 truth discovery 与按引用排名：两者都由系统裁决，我们不这样做。随后按路线补充与相邻系统的区别：
   - 学术知识图谱与文献系统：以文档为中心；ORKG 虽是众包多写者，但写入者是人、靠模板整理，不管理 Agent 的使用产物与项目分支。
   - 多写者共享知识库：Wikidata 固定数据模型（item、statement、qualifier、reference、rank），领域属性由社区逐步提议；相互冲突的值可以带来源并存。这是我们"元模型与领域词表分层""分歧并存"的最近先例，要正面说明差别：写入者是 Agent、产物是派生文档、有项目 fork 与推回。
   - Agent Memory，含多 Agent 共享记忆：Zep/Graphiti 的比较已在上文展开，承认其身份解析、来源、时态更新与领域扩展能力；差异落在裁决位置（系统内部 LLM 裁决，或交回写者）、有据层与解释层的划分、派生依赖与版本状态，研究操作只是这些契约的载体。Graphiti 作为实验基线，在同一工作负载与同一套类型上比较。其他系统逐项核实，不概括为均缺少身份、来源或版本。
   - 语义算子系统（AgenticScholar、LOTUS 等）：LLM 内化于算子；我们把语义工作外置、契约内化。
   - provenance 与版本化数据管理（`2026-Git4Data`、`2013-GraphSnapshot` 等）：管数据版本；我们管多写者积累的知识状态。
   - ontology engineering 与 schema induction：与本文正交，说明领域词表问题有人在做、不是我们的贡献。

   能力矩阵区分原生支持、组合支持、需外部推理。上述多写者知识库与多 Agent 记忆的文献是否已在 `references/` 中，待核实。
3. **Problem and Workloads.** 把中枢规约展开为可评测的形式：六类意图及其任务来源与必要信息（取自 intents 分解），写入者模型、事件类型、读侧阶梯，各自给出具体输入、所需输出、数据状态与操作序列。显式写出几条假设：不协调是语义上的而非并发事务；领域词表给定；库不判断谁对（可问责而非权威，按有据层与解释层区分）；起点只有论文原文与外部标识。明确责任边界。
4. **System Overview.** Figure 2：共享库、产物、提交历史与项目状态的整体关系；用 Figure 1 中一段写入历史端到端走查各部件。
5. **Accumulation Meta-Model.** Entity / Concept / Content / Artifact 主类与系统记录；身份规则（精确键、标识、重复与歧义的处理）、材料引用、来源与派生谱系；薄图、厚文档的分工；从意图推出的检索面（描述面与检索子集、关系为何进入检索面）。CS 论文的领域词表作为实例单列（回应 C1、C2、C5）。
6. **Operator Contracts and Artifact Persistence.** 访问算子（Search、Resolve、Traverse、ReadEvidence）的契约：混合检索中关系的作用、有界视图、分歧与过时随结果返回（回应 C5）。Agent 算子的输入输出契约：中间件校验计划、保存产物与声明依赖，使贡献自描述、可复查、可继续组合（回应 C2）。以意图的数据流说明两类算子如何组合。
7. **Versions, Revision, and Project States.** 统一提交与完整变更记录；有据层的修订（附锚点与理由）与解释层的并存；撤回；核对写成 Verify / Check 产物；基于依赖的过时提示；fork、推回与冲突处理；历史访问。区分产物输入谱系与提交祖先（回应 C3、C4）。
8. **Implementation.** 现有原型：属性图与材料存储、graph-doc 与 Commit、graph-vc 统一写入与版本、算子契约到 Cypher 与后端的映射、MCP 接入。
9. **Evaluation.**
   - **T1 主实验：** 写入者数 $K$（意图任务的多样性）与写入量增长下的库健康度（重复率、误合并率、悬空引用率、冲突检出率、过时识别及误报），由独立读者以固定探针查询测下游正确性；探针按 I1–I6 设计，落在多写者交汇处；注入事件即 Figure 1 的重演。
   - **消融：** 逐项去掉身份、契约、来源、版本。
   - **T2 成本账：** 构建成本前移、按使用者摊销，盈亏点 $N^* = C_{\text{build}}/(c_{\text{base}}-c_{\text{ours}})$；baseline 给相同预计算预算。
   - **读侧阶梯：** L0–L4，L4 为按时间切分的实验设计任务。
   - **T3（可选）：** 结构化访问是否缩小弱模型与强模型的差距。
   - **Baseline：** A0 文件 + Git（最强配置）、A1 RAG、A2 同一 schema 的裸 Neo4j + Cypher、A3 完整系统。A2 与 A3 共用 schema，二者之差只来自机制；与 A0、A1 的比较混有 schema 的作用，需如实标出。
   - **起点与金标准：** 起点只有论文原文与外部标识；可选的身份锚点引导在各组之间相同，且不与金标准重合。有据层以原文锚点为金标准；解释层不测真值，只测分歧是否保留、读者是否看得到。
   - **使用次数与正确性：** 作为观测量，检验多写者积累中是否出现错误级联。
   - **schema 覆盖不足作为观测量：** 记录写入内容装不进类型的次数与去向（Artifact 文档、描述字段或丢弃），不作为要解决的问题。
   - 任务、语料与协议见评测草案，仍待商定；结果可能为负，例如 A0 始终不输。
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
