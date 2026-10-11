# Commit 契约：论文增量的入库

> **状态：** 本文是 paper-form-v4 与 supplement-form-v1 的现行入库契约：论文表单写入实验（按研究问题分组，只存描述、锚点和方法、数据、Benchmark、任务关联）、主张与自述贡献；增补表单写入 Observation、Agent 认为的贡献与正反关系。Agent 算子写 Artifact 时共用本文的提交机制（第 7 节）。E09 的 compile、dry_run 与 apply 已对齐本文，尚待重新入库验证。抽取范围见 [抽取原则](./extraction_principles.md)，对象映射见 [Graph Model V2](./graph_model_v2.md)，算子见 [算子契约](./operators.md)，intent 与数据流见 [Workload 拆解](./intents_decompose.md) §5。

## 1. 流程与职责

```text
表单 ──compile──▶ delta ──dry_run──▶ plan ──apply──▶ 写入（单事务）──▶ 复核 ──▶ 补算向量
         │                │                 │
   不查库：只读        只读查库：         plan 有错误、冲突或
   表单与材料          库内与批内         待确认项时拒绝整批
```

| 阶段 | 输入 | 职责 | 查库 |
| --- | --- | --- | --- |
| compile | 表单、材料文件、领域配置 | 结构、语法、锚点等只看表单与材料就能判定的检查；将实验分组与参与关系编译为增量 | 否 |
| dry_run | delta | 解析引用、查重、冲突与幂等判定，返回 plan | 只读 |
| apply | 无阻塞项的 plan | 单事务写入；写完重跑 plan，必须为空 | 写 |
| 补算向量 | 本批新建或补全的对象 | 由 apply 触发；否则下一批的语义查重看不到这些对象 | 写 |

- **批**：一份表单为一批，整批原子。论文表单一篇论文一批；增补表单可以只填部分段落，按同一流程 compile、dry_run、apply。
- **循环**：Agent 按 plan 修改表单，再次 dry_run，直到没有阻塞项。来回轮数记入批次记录，是主张 A 的构建成本。
- **跨批依赖**：靠提交顺序保证。引用的对象所在的批次尚未提交时，dry_run 报"引用无法解析"。
- **边界**：中间件只做确定性检查与执行；同一性、称呼指向、冲突怎么处理由 Agent 判断（[研究顶层设计](./research_design_v2.md)）。

## 2. 表单

### 2.1 论文表单（paper-form-v4）

| 字段 | 内容 |
| --- | --- |
| `form` | 表单版本 `paper-form-v4` |
| `material` | 材料路径与内容哈希 |
| `paper` | 论文本身：`labels`、`properties`（name、identifiers、description）；dry_run 列出相似的已有 Paper 节点（含桩节点）后，经确认可写 `fill: {id}` 补全该节点 |
| `refs` | 已有对象（方法、数据集、Benchmark、任务、Issue、Proposition 等）：`{mention, kind}`；或经确认的 `{id, printed?, register?}`，`register: true` 表示把 `printed` 注册为该对象的新 alias（笔误不注册） |
| `objects` | 新对象：核心方法与桩节点（`stub: true`），带 `rejected`；被引论文只能是桩节点；补全桩节点用 `fill: {id 或 mention}` |
| `relationships` | 论文表单只允许本文 → 被引论文的 `CITES`：`{from: paper, type: CITES, to: <Paper ref>, basis: [<定位>…], description?}`，选择性写入（[抽取原则](./extraction_principles.md) §8） |
| `experiments` | 每个研究问题一项：`anchors`（表、图的锚点列表，第一个为主锚点）、`locators`（全部行范围 `<章节>::<start>:<end>`，含表、图与陈述设计和结论的正文）、`task`、`text`（实验描述）、`participants`（`subject`、`role`）、`data`、`benchmark`（可选，论文声明采用的 Benchmark，编译为 `EVALUATED_ON`） |
| `claims` | 每条主张一项：`key`（本文内唯一的短键）、`text`、`locators`、`about`（对象引用）、`supported_by`（本表单实验的主锚点列表，编译为 `SUPPORTED_BY`） |
| `contributions` | 每条自述贡献一项：`key`、`text`、`locators`、`about`（它提出或改进的对象）；编译为 `stated_by: paper` |
| `x-ingest` | `{committed_by, rounds}`：提交者与 dry_run 来回轮数，由入库入口读出写进批次记录（第 6 节） |

实验、主张与贡献的写法见 [抽取原则](./extraction_principles.md) §4、§9；变体、条件、疑点与逐项来源性质都不进表单（§2、§5、§6），结果引自哪篇论文写在 `CITES` 的 `description` 中。数值留在原文。其余 `x-` 开头的键只作 YAML 复用；compile 忽略全部 `x-` 键。

### 2.2 增补表单（supplement-form-v1）

| 字段 | 内容 |
| --- | --- |
| `form` | `supplement-form-v1` |
| `formed_by` | 形成者，整份表单共用，由提交的 Agent 填写；`formed_at` 由 apply 自动写入 |
| `refs` | 引用的已有对象：Entity、Concept 用 `{mention, kind}` 或 `{id}`；Content 与 Artifact 没有称呼，只能用 `{id}`；不写 `printed`、`register` |
| `observations` | 每条：`text`、`about`（`refs` 中的引用，至少一个）、`basis`（可选，`{material: <材料路径>, locators}`，编译为 `FROM`） |
| `contributions` | Agent 认为的贡献：`paper`（`refs` 中的 Paper 引用）、`text`、`about`、`basis`（可选）；编译为 `stated_by: agent`，经 `FROM` 连到该论文 |
| `relationships` | 只允许 `SUPPORTS` / `OPPOSES`：`{from, type, to, description}`，端点为 `refs` 中同为 Claim 或同为 Proposition 的引用；编译为 `stated_by: agent` |
| `x-ingest` | 同论文表单 |

三段都可省略，只要有一段非空就能编译。增补表单不新建 Entity、Concept 对象，也不注册 alias；引用的对象必须已在库中。

`basis` 的材料必须已入库：论文原文或 Artifact 文档。`FROM` 的终点是该材料所属的节点（论文或 Artifact），边上带 `material_ref` 与 `locators`。Agent 贡献的 `basis` 必须属于它所属的论文；没有 `basis` 时，贡献的 `FROM` 仍连到所属论文，边上不带定位。Observation 可经 `about` 关联 Artifact、以 Artifact 文档为 `basis`，这是把工作产物提升为长期记录的途径（[算子契约](./operators.md) §5.7）。

## 3. 操作集

| 操作 | 写入 |
| --- | --- |
| `create_object` | Entity / Concept 节点；桩节点带 `stub: true` |
| `register_name` | `NameKey` 与 `NAMES` |
| `fill_stub` | 补全桩节点（含论文表单的 `paper`）：**只填空字段**，去掉 `stub` |
| `add_material` | `Material`（路径、内容哈希）与 `MATERIAL_OF` |
| `add_experiment` | `Content:Experiment`，与 `FROM {material_ref, locators}`、`ON_TASK`、`EVALUATES {role}`、`USES {role: evaluation_data}`、`EVALUATED_ON` |
| `add_content` | `Content:Claim`、`Content:Contribution`、`Content:Observation`，与 `FROM`、`ABOUT`、`SUPPORTED_BY`；Agent 形成的记录带 `formed_by`、`formed_at` |
| `link` | 论文表单的 `CITES`，边上存 `source_refs`（`<material_id>::<定位>`）与 `description`；增补表单的 `SUPPORTS` / `OPPOSES`，边上存 `description`、`stated_by`、`formed_by`、`formed_at` |
| `record_batch` | `IngestBatch` 系统记录（第 6 节） |

Experiment 上的属性：`exp_key`、`anchors`、`text`；Claim、Contribution 上的属性：`content_key`（Agent 贡献不设）、`text`、`stated_by`（Contribution）。行范围只存在 `FROM.locators` 上。

## 4. 检查与返回

| 阶段 | 检查 | 返回类别 |
| --- | --- | --- |
| compile | 表单结构与未知字段；每个锚点都在材料中，且落在该实验某个 locator 的行范围内；locators 不越界；`text` 非空；同一实验中被测对象不重复、至少一个 target；各实验的主锚点不重复；桩节点不写定义、非桩必须写；Paper 对象只能是桩节点 | **错误** |
| compile | 关系只能是 `CITES`，起点是本文、终点是 Paper；`basis` 非空，且不能全部落在参考文献节内 | **错误** |
| compile | 表单里的方法名与数据集的称呼不在该实验任一 locator 的行范围内（新对象的 name 或任一 alias 出现即可） | **待确认** |
| compile | 实验描述中出现带小数的数值（抽取原则 §4：不转录数值） | **待确认** |
| compile | 主张与贡献：`key` 本文内唯一，`text` 非空，locators 不越界，`supported_by` 指向本表单实验的主锚点 | **错误** |
| compile | 增补表单：`formed_by` 非空，至少一段非空；Content 与 Artifact 只能用 `{id}` 引用；Observation 的 `about` 非空；`basis` 的材料存在、locators 不越界；关系类型只能是 `SUPPORTS` / `OPPOSES`，`description` 非空，两端同为 Claim 或同为 Proposition、不是同一个引用；同一表单内不重复写同一条记录或关系 | **错误** |
| dry_run | 引用在 id / alias 级唯一命中 | 否则**待确认**（附候选） |
| dry_run | `paper` 未按标识命中且未写 `fill` 时，按名称词面与语义通道列出相似的已有 Paper 节点（含桩节点）；确认为同一论文时改用 `fill` | 有相似节点时**待确认** |
| dry_run | 增补表单 `basis` 的材料已入库且属于唯一一个节点；Agent 贡献的 `basis` 属于它所属的论文 | 否则**冲突**（`material-missing`、`basis-paper`） |
| dry_run | 新对象的语义近邻全部列入 `rejected`；桩节点只走 id、alias 与名称词面通道 | 否则**待确认** |
| dry_run | 新对象的精确键或唯一标识（如 arXiv 号）已被占用；新对象撞上已有桩节点（提示改用 `fill`） | **冲突** |
| dry_run | 实验的自然键已存在：`anchors`、`text`、`FROM.locators`、`ON_TASK`、`EVALUATES` 与 `USES` 绑定都相同为不变，否则为冲突 | **不变** / **冲突** |
| dry_run | `CITES` 的两端已在库中且边已存在：`source_refs` 与 `description` 都相同为不变，否则为冲突（`rel-changed`） | **不变** / **冲突** |
| dry_run | Claim、Contribution 的自然键已存在：`text`、`FROM.locators` 与 `ABOUT`、`SUPPORTED_BY` 绑定都相同为不变，否则为冲突；Observation 与 Agent 贡献的 `formed_by`、`text` 与对象集合（贡献另加所属论文）都相同时，`FROM` 也相同为不变，否则为冲突；正反关系按起点、终点、类型与 `formed_by` 已存在时，`description` 相同为不变，否则为冲突 | **不变** / **冲突** |

三类阻塞项的处理方不同：**错误**由 Agent 改表单；**待确认**由 Agent 做语义判断；**冲突**是与库内状态矛盾，由外部决定（改为引用、`fill`、改名或交人工）。有任何一类时 apply 拒绝整批。

## 5. 自然键与幂等

| 对象 | 自然键（存为属性，带唯一约束） |
| --- | --- |
| Experiment | `exp_key = <论文 id>::<主锚点>` |
| `CITES` | 起点与终点的 id（不另存键，也不加约束） |
| Claim、Contribution（`stated_by: paper`） | `content_key = <论文 id>::<kind>::<key>` |
| Observation、Contribution（`stated_by: agent`） | 不设自然键；按 `formed_by`、`text` 与对象集合（贡献另加所属论文）判重 |
| `SUPPORTS` / `OPPOSES` | 起点、终点、类型与 `formed_by` |

- 同一表单重跑：全部为不变，不写入。写入中途失败时事务回滚，可直接重试。
- 实验、主张或贡献内容有变化：按层处理（2026-10-11 放宽，实现见 graph-doc 写入路径 [`commit.md`](../../experiments/e09/operators/commit.md) §5）。
  - **有据层**（Experiment，`stated_by: paper` 的 Claim、Contribution 与正反关系）：附理由与锚点（该记录所属论文中支持新内容的行范围）时允许修订，二者记入 graph-vc 提交的 `meta.revisions`，旧值留在版本历史中；删除即撤回，只需理由。未附的仍然拒绝。
  - **解释层**（Observation，`stated_by: agent` 的 Contribution 与正反关系）：只有形成者本人可以改动或删除；其他写入者另写自己的记录，两者并存，不裁决。
- 同一论文补录另一个研究问题：论文按标识命中，新增一个 Experiment；已有实验组补充锚点属于内容修订，按上一条处理。表单中没有的实验不删除（可能来自其他批次）。
- 写后复核不为空：说明 `Commit` 自身有缺陷，报错。

## 6. 批次记录

每批一个 `IngestBatch` 系统记录。论文表单的批次连到 Paper；增补表单的批次只记出处、提交者、时间与写入统计：

- `coverage`：本批各实验的全部锚点（表、图）。同一论文多批的 coverage 取并集。查询时据此区分"原文没报告"与"没有录入"；抽取原则 §11 的锚点覆盖检查也以它为准。
- 解析统计：引用在各级的命中数、展示的语义候选数与否定数、dry_run 来回轮数——主张 A 的构建成本。
- 写入统计：新建对象、实验与关系（`new_rels`）的数量。
- 来回轮数与提交者取自表单的 `x-ingest`，由提交者如实填写；中间件的偶发故障（如语义查重通道失败后重跑）不计入轮数，在表单注释中说明。
- 出处：表单的内容哈希（`form_hash`，两种表单都记）、论文表单的材料哈希、提交者、时间；增补表单另记 `formed_by`。

## 7. Agent 算子的写入

Agent 算子（[算子契约](./operators.md) §4）每次调用写一个 Artifact。它们不是 `Commit`，不经表单与 dry_run 循环，但使用本文的同一提交机制：

| 环节 | 规定 |
| --- | --- |
| 校验 | 引用都在库中；正文中的引用属于声明的输入；参数与内容符合该算子的 schema；判断类每个单元恰有一条判断。任一不过则整次拒绝，返回与本文阻塞项同形的错误 `{rule, where, msg}` |
| 写入 | 先写文档文件，再在单事务中写 Artifact 节点、`USED` 边、`Material` 与 `MATERIAL_OF` |
| 复核 | 写后在同一事务内确认节点与边都在、文档哈希一致；不一致则回滚，文件作废 |
| 幂等 | 相同 `artifact_key`（`op`、输入、参数、内容与形成者的哈希）视为重试，返回已有 Artifact，不重复写入 |
| 向量 | 写入后补算 `title` 与 `abs` 的向量 |
| 批次 | 不写 `IngestBatch`；形成者、时间与会话记在 Artifact 上 |

## 8. 尚未覆盖

- 对象合并与拆分：不实现；重复与误合并只测量，作为局限报告。修订与撤回见 §5。
- 实验条件与数据切分：模型不表达切分与资源版本，条件按锚点读原文。
- Paper 以外的关系写入（方法间关系、`IMPLEMENTS`、`ADDRESSES` 等）：单篇抽取不写（[抽取原则](./extraction_principles.md) §1）。
- Issue、Proposition 的建立与整理：留给后续的 Concept 精炼与整理工具或算子；当前只能经 `refs` 引用已有对象。
