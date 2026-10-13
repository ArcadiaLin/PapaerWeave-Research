# 手动进展汇总

## 2026/09/27 之前

已有进度：构建 bert、graphrag、rag 三篇作为example 进入 graph 中，结论是当前的数据模型的确能够满足网络构建的需求。

但是问题是 Agent 凭借记忆构建的示例数据无法满足这些情况：

1、示例数据拼接模型预训练的记忆生成，因此无法检验论文理解图谱是否能够帮助 Agent 更好地获取有依据地论文理解和以前的经验
2、无法体现真实数据的复杂性，例如实体消歧
3、直接生成了最终可入库的文件，但是真实工作流中，抽取数据到入库，还有很多复杂的步骤准备

## 2026/09/27

准备了6篇真实的论文，data/raw/e08-paper-knowledge，来进行模拟真实数据抽取、入库

但是这个抽取工作目前不进入我们论文的叙事，因此我们可以比较“方便”而不体系地推进，例如先准备好数据，然后做抽取套件，之后方案固定了，在真实地规范好一个 agent 使用我们设计方案时如何更新图谱

更新了 data model 为 Paper、Method、MethodConcept、Resource、Metric 加上了 aliases property，帮助新数据入库时，agent 进行检索兜底，获取到相似的 node，然后将数据补充或更新到图谱中已有的 node 中，防止新造实体，充当实体消歧，检索兜底的作用。alias 字段进行验证后能够有效的进行检索和兜底保障

### 数据抽取准备

- Resource 改用次级 Label（Dataset、Benchmark、Model、CodeRepo、Tool），不再为不同种类设专属属性。id 改为不带语义、由工具分配。样例数据按此重新入库。
- 新建 pi-configs/paper-extract/：禁用全部内置工具，不加载 AGENTS.md 和 skills；配套 system prompt 草稿与抽取指南 GUIDE_ZH.md。
- 种子概念入图 data/raw/e08-paper-knowledge/seeds/：共 79 个节点，内容用英文；aliases 只收同义称呼，description 不写经验判断，事实按原始出处核对并记录 sources/verified。修正了两处：MultiHop-RAG 的时间范围，以及 Electricity 通用版本的来源。

### 数据模型演进

- 新增：
  - Task，以及 ADDRESSES、ON_TASK、FOR_TASK；
  - Issue，以及 RAISES、RESPONDS_TO {stance}，用来承载论文之间有争议的问题；
  - Observation，以及 OBSERVES、CHECKS {verdict}，把第一手检查与论文声明分开；
  - 可选的 note，只放使用提醒；
  - Claim ABOUT 的终点扩展到 MethodConcept、Task、Metric。
- 删除：Condition 和 ContentUnit。实验设置并入 Experiment 的 description，表和图直接用块级 anchor 定位。
- 现在共 13 类节点，模型暂时冻结；新需求等 DLinear、PatchTST 抽取后再定。
- Resource:Model 包含 API 模型；检索索引加入 Task、Issue 和 note。

### 基础设施

- 新增 infra/neo4j-e08/（端口 7688/7475），与样例库隔离。

## 2026/09/28

### 种子概念重新入图

- id 由全局分配器按“前缀 + 序号”分配（如 task_0001）；按“主 Label + name”判断节点是否已存在，已存在就跳过。
- 重跑时全部跳过，id 保持不变。
- 语义检索支持：用 Qwen3-Embedding-8B（vLLM，部署在 192.168.163.112:8002，4096 维）给节点算向量，并建了 entity_vectors 和 statement_vectors 两个向量索引。
  - sync_embeddings() 按“模型名 + 文本”的哈希只补算缺失或过期的向量，写入图谱后调用一次即可。

### 查询算子

- `find_entities(mention, description, entity_type)`：
  - Stage 1 标识解析：原样匹配和去标点后匹配，命中的固定置顶，不参与排序；
  - Stage 2 三路召回：名称 BM25（带前缀和模糊匹配）、定义 BM25、语义向量，按 RRF（k = 10）融合；
  - 返回前 5 个候选，附各通道的证据、定义、note 和一跳邻接关系，不给置信度。
- `find_statements(text, description, kind)`：在 ClaimConcept、Issue、Claim 上做两路召回并融合。Claim 只查不复用，结果附所属论文。用临时节点做冒烟测试通过。
- 索引调整：
  - 定义和陈述两个全文索引改用 english 分词，名称索引保留默认分词；
  - note 不进索引也不进向量，只随候选返回；
  - Issue 的向量改为用 text + description 计算；
  - ensure_schema() 发现索引的 Label、字段或分词方式与声明不一致时，自动重建。
- 示例效果：
  - ETTh1 能带出 ETT；
  - RevIN 加一句 description 后能命中 Instance normalization；
  - 图里没有的 PatchTST，前 5 名都是它可能要连边的相关概念。

### 基础设施

- 部署 Qwen3-Embedding-8B
- neo4j 索引完善

### 论文草稿

- codex 撰写了一版论文全文雏形已提交；核心机制与评测方案待细化，下一步审阅第 2、4 节
  - 本次因 find_entities 与命题检索的区分，重新审视了数据模型的设计依据及其在研究中的地位。讨论明确：当前模型是面向 Agent 长期研究活动的 semantic data model，其设计由 **研究 intent 中的知识复用需求** ，以及 **科学知识表示的既有研究** 共同支撑，可以构成研究贡献的一部分。
  - 为固定这些理解、锚定研究主线，提前将 paper/introduction.zh.md 扩展为全文草稿，串联“研究活动 → 复用挑战 → 模型设计 → 操作机制 → 效果评价”。已保留原有引言并提交 29914b0。这版草稿用于检查研究叙事是否连贯；核心算法、命题归并与知识维护机制、评测协议仍待细化。下一步优先审阅第 2、4 节，明确哪些设计承担核心贡献、需要什么证据支持

## 2026/09/29

### 设计文档更新

- graph_model.md: 删除 graph_model.md 的 Query 一节，查询部分统一以 docs/designs/operator.md 为准
- open_questions: 
  - 更新检索设计文档 2026-09-28-entity-lookup-and-identity.md，算子是否算贡献、要不要靠 aliases 绕过两个问题已回答，查找效果的测量、aliases 积累、身份的可追溯与修正仍开放。
  - 算子设计

## 2026/09/30

### 核心设计思想演化

- **明确模型、算子与任务表达共同演化**
  - 相对稳定的则是 intent 及完成任务所需的信息；信息如何拆成节点、属性、关系仍然可调整。顺势提出整体设计的 v2，v1 作为经验和实现材料参考，不再限定 v2 分类和接口
- **创建 v2 文档集合，与 v1 区别**
  - `docs/designs/v1/*` & `docs/designs/v2/*`

## 2026/10/01

### v2 文档修改

主要在 `docs/designs/v2/intents_decompose.md` 和 `docs/designs/v2/research_design_v2.md` 两个上面

- **澄清描述面与检索面的包含关系，帮助intent拆解**
  - 描述面是字段全集，检索面则是其中由中间件直接消费的子集。三类下，类内共享检索字段、索引及关系处理七月，其余描述字段允许异构，Agent可以消费完整的描述面
- 在前者的基础上**重新论证了 Entity / Concept / Content**
  - Entity 侧重资源指标、版本实现与对应；Concept侧重定义、范围和概念关系；Content侧重来源化表达及上下文。Entity、Concept可以使用名称和别名匹配，Content 不默认使用 alias，**Concept 虽然可以具有严谨标识符，但体系不一我不想用**（需要论证，虽然我觉得也符合直觉，一些概念，比如 RAG，刚出来的时候那些标识体系就纳入了吗？）
- **将语义对象提升到了节点与关系的组合**，一个语义对象，可以映射为单节点或者有限子图；对象间的关联也可以由边或带中间节点的子图表示。物理节点（属性图上的 Node）不必一一对应语义对象，关系进入检索七月，分别承担硬约束、扩展候选/排序线索和结果装配，不能全部混为文本相似度
- **研究中心现在篇面向 Agent 的语义访问层**：通过可组合的任务级访问算子，组织结构化查询、语义检索、关系遍历和材料读取。算子表达可复用信息取得任务
- **保持外部 Agent 与中间件的边界**：Agent在端到端表达式中承担解释、谓词判断和策略选择；中间件不调度Agent，系统执行已声明的约束并返回候选、绑定、匹配路径和来源

## 2026/10/02

- E09 环境与种子入库。 搭好了独立的 neo4j-e09 与数据目录，种子改写为 v2 格式后写入图中（make seed）。身份按 NameKey 精确键与命名空间标识判断；冲突和重复整批拒绝，可以重复执行。
- 第一批算子落地。 src/e09/ 分为 operators/ 与 utils/，实现了 Commit（目前只支持种子）、Resolve、Get，并在 notebook 01、02 中用真实种子检验了正常与失败的各种情况。
- 对实际复杂度的认识。 语义检索不设阈值，"库里没有"很少直接返回空，而要由外部 Agent 逐个否定候选；写入必须整批解析，逐条查重发现不了同批之间的冲突。确认和查重的成本因此比预想的高，要计入主张 A。
- 设计文档同步。 按实践修订了 Resolve 契约和结果路由、I3/I6 伪代码与写入路径；graph_model_v2 §7 新增 Commit 契约等待定项。下一步：确定入库表单与 Commit 契约，然后让 DLinear 和 PatchTST 入库。

### 未决问题与下一步

- 伪代码的论证、拆解等未能充分完成：算子粒度是否合适、三分类是否必要、图映射保留信息。尤其需要与直接的 cypher、充分说明查询模板及可比检索组合进行受控比较，别忘了现在还没有更新入库的算子设计，语义化的查询好搞，语义化的入库就很难搞了
- 从资源定位、概念范围查询、实验上下文各取典型真实案例，固定输入、材料、数据状态和独立参考输出，检验分类与访问契约，再确定最小实现和benchmark范围

## 2026/10/03-10/07

### 算子工程落实（E09）

- 数据入库与模型冻结：DLinear 和 PatchTST 正式入库，报告级，含 22 张结果表和引用关系。v2 模型冻结，对象与关系不再增加，另加增补表单和自由文本向量。
- 写入路径重建：
  - 底层分两层：graph-vc 记录变更集和版本，graph-doc 是读写同形的 YAML 子图，读出的视图原样交回就是 noop。
  - Commit 在这两层之上，支持查重与 confirm、删除影响提示、先预演后提交（graph-plan → graph-result）。
  - neo4j-e09 按新的写入路径重建。
- 算子补全：
  - 中间件算子：Search、Resolve、Traverse、ReadEvidence、Commit。
  - Agent 算子：Extract、Summarize、Generate、Check、Verify、Filter、MatrixConstruct。每次调用的结果存为 Artifact，包括文档、USED 边和一次提交。
- 作为 MCP 服务交给通用 Agent：
  - 算子以 PaperWeave MCP 服务的形式提供给默认配置的 pi，实验只控制仓库外的工作目录。
  - 用法全部写进各工具的说明，因为 pi 的 direct 方式不会把服务的 instructions 交给模型。
- 试跑驱动的修正
  - 主要修正在限制工具返回长度，不超过 pi 的上限
  - 修正工具参数、说明，引导 Agent 更加稳定、正确地使用工具

### 论文草稿（paper/narrative-draft.md）

- 10/05：草稿改名为"叙事推进草稿"，精简并收束引言与章节大纲；加入知识产物和版本化项目管理的设计。
- 10/06：
  - Why 改为纵横两维框架，研究问题句定稿，与"通用 Agent 经 MCP 使用中间件"的设定对齐。
  - 贡献改为 agent-composed 契约的定位。
  - Figure 1 改为三带结构，标出 C1–C4 的落点，并与算子挂钩。
  - related work 前移为 §2，大纲按 AgenticScholar 的方式重排。
- 同期 AGENTS.md 的研究方向更新：
  - 项目视图、提交记录和版本历史定为必需范围（10/05）；
  - 实验中的 Agent 定为经 MCP 使用中间件的通用 Agent（10/06）。

## 正在进行的工作

### 实验

- 2026-10-11：T1 沙箱完成。
  - t1.bridge 用 unix socket 转发大模型和 MCP 服务；t1.sandbox 用 bwrap 隔离运行默认配置的 pi：断网、只读论文、清空环境变量，MCP 服务在沙箱外按登录身份启动。
  - 隔离探测通过。A3 冒烟会话通过：33 秒，调用 Resolve 和 Traverse，身份记录正确。6 个测试通过。
  - 下一步：T1 运行框架（调度、检查点、每次运行重建存储）。

- 2026-10-11：T1 冒烟测试 smoke-3 通过，两组各跑一个会话：A3 用时 632 秒，A0 用时 446 秒。
  - A3：补全了 Autoformer 方法桩，写入 3 个实验和 3 份 Extract 结果表（MSE/MAE 全量）。
  - A0：写了 623 行的论文笔记，并在 Informer 笔记里记下与 Autoformer 的分歧，但引用了 SCINet 不存在的章节 A1.T4。
- 改动：
  - 上下文窗口改为 262144（之前在 12.8 万左右触发自动压缩）；
  - Commit 的 source 可省略；
  - 两组并行运行。
- 已启动完整先导 ~/t1-runs/pilot-1，两组各 16 个会话。
- 下一步：运行结束后检查各检查点，并开始写探针。

- 2026-10-11：实现了草稿文件接口（docs/designs/v2/draft_files.md）。Extract 和 MatrixConstruct 用 payload_file（CSV，带模板，报错带行号），Commit 用 doc_file，且一次调用即提交。另外修了 T1 框架：pi 空闲超时、工作目录映射、请求出错计数、A0 残留改动处理。
- A3 冒烟（~/t1-runs/smoke-4、smoke-5，同 pilot-1 槽位 1）：会话时长从 1321 s 降到 351 s / 556 s；输出 token 从 112k 降到 28k / 54k；这三个算子被拒调用的 token 占比从 52% 降到 18% / 21%（经文件提交的部分只有 14.5% / 1.0%）；模型请求没有出错。写者会用脚本从论文生成 CSV。
- 冒烟后追加了三处修复：声明的问题先报告；回执最多回显 40 行；错误最多列 30 条。
- 未解决：MatrixConstruct 的文件路径没有在实际运行中用到；Summarize 和 Generate 仍常因参数位置错误被 pi 拒绝（smoke-5 中占 17.5%），可以作为下一轮改动对象；设计文档还没写入上面三处追加修复。
- 下一步：提交改动；考虑把 Generate 也改为通过文件提交；然后启动新的先导运行（A0 + A3）。

- 2026-10-11：提交了草稿文件的实现（a8ec86f）和 commit.md 中调用参数一段（478cbff）。
- 核对了冒烟产物的准确度：smoke-4 的 584 个数值全部与所引的论文行一致；smoke-5 有 192 个 std 值取自 Table 10，却标为 Table 1 的出处。值是对的，出处不完整，现有契约发现不了。
- smoke-4 写出了有用的跨论文 Observation：可比条件、与 SCINet 记录的分歧、与 Informer 数值一致。
- 未解决：
  - commit.md 还没写 doc_file 和 MCP 中 apply 默认提交；
  - 两次运行的写法差别大，正式实验需要多次重复；
  - 要不要加"数值是否出现在所引的行"的警告；
  - Generate 要不要改为通过文件提交。
- 下一步：在同一槽位跑 A0 冒烟，然后跑 pilot-2（A0 + A3）。

2026-10-12：叙事调整与算子层设计（提交 ed1004e）：
 - paper/narrative-draft.md 改为领域优先：标题点出 research knowledge；加入 agent memory 的谱系；写出四类对象在写入机制下的一致方式（主张收回到机制，不归于模型）；评测归为 E1 完整性 / E2 充分性 / E3 对等。
 - docs/discussions/2026-10-12-task-operators-and-leaderboard.md：面向任务的可注入算子（声明格式、op_version）、ExtractResults 的 schema、内置的 Leaderboard 读算子；去掉 Filter、MatrixConstruct，保留 Generate 用于 LLM judge 评撰写任务。
 - PwC 快照覆盖先导语料 10 篇中的 7 篇（CATS 无，UniTime、TimeMachine 各 1 格）。
 - 待定：结果行作为产物还是论文陈述的记录；A0 是否给同一份 schema；op_version；Generate 的引用约束。
 - 下一步：定下以上 4 点，再改 operators.md 与代码。

2026-10-12（续）：算子层决定：A0 不给 schema（统一格式是被评对象，schema 与机制的作用由 A2 分开）、加 op_version、Generate 不要求每段带引用。按 T1 先导探针（A–G）倒推出算子集合：ExtractResults（补变体、表类型、数值来历、训练数据、标准误、转录范围）、CompareSettings（由 Check 改造，维度固定）、Verify、Summarize、Generate，以及内置的 Leaderboard。约束：先冻结算子集合，再写正式探针。见 docs/discussions/2026-10-12-task-operators-and-leaderboard.md §11。待定：结果行作为产物还是论文陈述的记录。

### 论文

- 与 Graphiti 的区别
  - 补充研究操作契约与 Artifact 回流机制的定位；下一步检查候选段落是否准确表达这条积累链，并以跨 agent 的后续使用验证其价值。

问：
接着回到评测草案。上一轮要你定的四件事还在：
1. 主指标是不是用下游探针正确率；
2. 是否采用"不变式 × 合并"骨架，Fork/Merge 要不要提前；
3. A4 选 Mem0、Graphiti 中的一个还是两个都上；
4. 论文截稿日期是哪天。

要防一个质疑： 审稿人会问，算子是不是照着探针量身定做的。我在稿子里写了应对：

- 算子和探针都从意图推出，有共同的来源，不是互相迁就；
- 先冻结算子集合，再写正式探针。 正式探针一部分从 PwC 抽取，一部分按意图新写；先导探针只用来设计，不进入最终结论；
- 论文中坦白写明：算子集合是按这个 workload 设计的，换 workload 就换声明。