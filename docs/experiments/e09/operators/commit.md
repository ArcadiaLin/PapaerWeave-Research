# Commit 工具设计：graph-doc

> **状态：** 草案（2026-10-05），部分已实现。本文记录 Commit 新入口的设计：读写同形的 YAML 文档 graph-doc。现行契约 [commit_contract.md](../../../designs/v2/commit_contract.md) 与 [operators.md](../../../designs/v2/operators.md) 尚未同步。第 8 节是建立在同一写入机制上的版本管理规划，第 9 节记录实现中已定的问题与仍待决定的问题，第 10 节记录 TerminusDB 调研的工程见解与改进建议，第 11 节记录面向项目知识继承的理论建议与论文参照。
>
> **实现情况（2026-10-05）：**
>
> - 第 2–7 节的格式、写入语义、检查与 dry_run / apply 已实现：解析与求差在 `packages/graph-doc`，按冻结模型的翻译、查重与写后复核在 `experiments/e09/src/e09/commit/`。
> - 命令行入口是 `python -m e09`（直接给 graph-doc 即为 Commit，算子定义在 `operators/db/commit.py`，写入管线在 `commit/`），它会拒绝没有版本记录的旧库，提交后补算向量。
> - 第 8.2–8.3 节的 Commit 记录与 `Revert` 由 `packages/graph-vc` 实现。
> - 尚未实现：
>   - 读视图渲染（§6 R）；
>   - `Log`、`Show`、`Diff`、`AsOf`、`Blame`；
>   - Artifact 写入；
>   - 分支。
>
> E09 旧的写入路径（论文表单、增补表单、种子入库）已删除，最后的版本留在 tag `e09-legacy-write`。现有的种子与两份论文表单将一次性转成 graph-doc，经新路径重建。

## 1. 为什么重新设计

现行 Commit 只会新建：`create_object`、`register_name`、`add_*`、`link`，以及只填空字段的 `fill_stub`。由此带来两个缺口：

- **不能修改。** 修订、撤回、合并都只能清库重建（commit_contract §5、§8）。
- **有些对象没有写入路径。** Issue、Proposition 只能引用已有节点；Paper 之外的关系（`IMPLEMENTS`、`ADDRESSES`、方法之间的关系等）也写不进去。

模型中暂时没有写入路径的元素不删除；Commit 最终应能完成对模型的任何修改。

新设计借鉴 OpenAI Agents SDK 的 `apply_patch`（`references/repos/openai-agents-python/examples/tools/apply_patch.py`），取的是它的思路，不是它的操作：

- **读写同形。** Agent 用 Traverse 读出的视图是一份 YAML 文档（Search 只给摘录，不是可交回的视图），写入时交的也是同一种 YAML 文档。
- **交状态，不交指令。** 交上来的文档表示“这些节点应当是这个样子”，由中间件计算它与库中现状的差异，再执行。
- **不模拟文件系统。** 没有真实目录，也不按对象切分文件；一次查询的视图合成一份文档，修改时整份交回。
- **只有一种格式。** 新入库、在视图上修改、追加理解、删除、合并都写成 graph-doc，不再区分论文表单与增补表单。

## 2. graph-doc 格式

一份 graph-doc 就是图中的一个子图。

### 2.1 顶层

| 键 | 读 | 写 | 含义 |
| --- | --- | --- | --- |
| `graph-doc` | ✓ | ✓ | 格式版本 |
| `meta` | ✓ | 忽略 | 生成这份视图的查询、覆盖情况（返回数、是否截断、快照）、路径绑定与诊断信息 |
| `by` | — | 必填 | 写入者。Agent 形成的记录的 `formed_by` 取自这里。经 MCP 写入时由连接配置给出登录身份（`E09_USER`）：`by` 可以省略，写了就必须相同，否则报 `identity`；所用的 Agent 与模型（`E09_AGENT`）记入提交的 `meta.agent` |
| `confirm` | — | 可选 | 写入时的确认，不入图：判定新节点与查重候选不是同一对象（`distinct_from`）；修订有据层记录的理由与锚点（`revise`），见 §5 |
| `nodes` | ✓ | ✓ | 节点，按引用作键；同一节点在一份文档中只出现一次 |

### 2.2 引用

| 写法 | 用于 | 说明 |
| --- | --- | --- |
| 已有 id，如 `method_0016` | 已有节点 | 写入时引用已有节点只能用 id。称呼要先经 Resolve 解析，Commit 不负责解析称呼 |
| `$` 开头，如 `$patchtst` | 新建节点 | 临时引用，文档内任何位置都可以引用它；apply 后返回 `$ → id` 的映射 |

id 由中间件生成。Agent 读得到 id，但不会编造 id：新节点一律写 `$` 引用，写入成功后从返回结果中拿到 id。

### 2.3 字段：三种拼写

字段的类别看拼写，不看位置：

| 拼写 | 类别 | 可写 | 例 |
| --- | --- | --- | --- |
| 小写 | 属性 | ✓，任何时候都可写可改 | `name`、`aliases`、`identifiers`、`definition`、`text`、`description`、`note`、`kind`、`stated_by`、`stub`、`material` |
| 全大写 | 出边，键就是关系类型，写在起点上（方向约定见 graph_model §6） | ✓ | `ABOUT`、`FROM`、`EVALUATES`、`SUPPORTS`、`CITES` |
| `_` 开头 | 自动生成、需要给读者看的信息 | 只读 | `_formed_by`、`_formed_at`、`_stale`、`_material`、Artifact 的全部字段 |

出边的值是列表，元素可以是引用，也可以是 `{to: 引用, <边属性>…}`。

纯机制用的自动生成字段不进入 graph-doc，读写时都看不到：版本哈希、`exp_key` / `content_key`、`artifact_key`、材料的内容哈希、向量。

`kind`、`stated_by` 等不限于新建时写入，之后也可以修改。

### 2.4 材料与来源引用

- **登记材料。** Paper 上写 `material: <路径>`，中间件登记 Material 并计算哈希。读到的视图中另有只读的 `_material: <material id>`。
- **写 `FROM` 边。** 写成 `{to: <paper 或 art 引用>, locators: [...]}`，由中间件补上 `material_ref`，读时显示为边上的 `_material`。
- **来源引用。** 格式为 `<material id>::<locator>`，locator 是 `<section>::<start>:<end>`。写入时也可以用 `<paper 或 art 的 id 或 $ 引用>::<locator>`，由中间件换成该节点当前的材料；这是因为新论文在入库前还没有材料 id。把读到的值原样抄回去也可以。
- **更换材料。** Paper 登记材料后，暂不支持更换或清空 `material`。改材料会牵动已有 locator 与来源引用的校验，留待以后设计。

### 2.5 中间件补上的内容

下面这些由中间件在写入时生成，Agent 不写。

**系统节点**

| 内容 | 规则 |
| --- | --- |
| Material | `id` 为 `material_<内容 SHA-256 前 12 位>`，属性 `path`、`format: markdown`、`content_hash`，以 `MATERIAL_OF` 连到 Paper。材料文件的路径与哈希同时记入变更集的 `files`，提交前核对 |
| NameKey | `name` 与每个 `aliases` 元素各对应一个 NameKey，以 `NAMES` 连到所命名的节点。`id` 就是它的 `key`，即 `<规范化名称>\|<kind>\|global`。`registered_by` 取自 `by`，`registered_from` 取自调用方给出的来源标签。名称在同一文档中从一个节点移到另一个节点时（合并，W6），改指原有的 NameKey，不删了再建 |

**补在节点与边上的字段**

| 内容 | 规则 |
| --- | --- |
| `FROM` 边的 `material_ref` | 取终点当前的材料 |
| 来源引用 | 开头的 `$` 引用、节点 id 或材料 id 统一换成材料 id；locator 按材料行数检查是否越界 |
| 形成信息 | 新建的 Observation、`stated_by: agent` 的 Contribution，以及 `stated_by: agent` 的 `SUPPORTS` / `OPPOSES` 边，补上 `formed_by`（取自 `by`）与 `formed_at` |
| `exp_key` | 为 `<来源论文 id>::<anchors 的第一项>`，主锚点或来源论文改变时随之重算 |
| `content_key` | 论文陈述的 Claim、Contribution 新建时生成，为 `<来源论文 id>::<kind>::<$ 引用名>`，之后不变 |

两种自然键用来发现同一条记录被重复提交（`key-taken`）。dry_run 时新论文还没有 id，自然键中的论文用临时引用，此时同一篇论文的重复提交由标识、名称和材料的冲突发现。

## 3. 写入语义：交上来的就是想要的状态

| 对象 | 出现 | `null` | 不写 |
| --- | --- | --- | --- |
| 属性 | 设为该值 | 清空 | 不动 |
| 某一关系键 | 该类型出边的完整集合：多出的边新建，缺少的边删除；已有的边上，写出的边属性按值更新，写 `null` 清空，不写的边属性不动 | — | 不动 |
| 节点 | 按上两行处理；`$` 引用则新建 | 删除该节点及其全部入边与出边 | 不动（不写 ≠ 删除） |

- **集合与顺序。** `aliases`、`identifiers` 和出边列表都与顺序无关。增删 `aliases` 就是注册或撤销 NameKey。
- **读视图的完整性。** 读到的视图中，节点只要出现了某个关系键，就给出该类型的全部出边，所以原样交回不会丢边。
- **只读字段。** `_` 字段原样带回时忽略，改动则报错。
- **Artifact。** 只能由 Agent 算子写入；graph-doc 中出现的 Artifact 只供引用，修改它会报错。
- **入边。** 入边在起点上修改。Agent 先检索出子图，从而知道哪些节点指向目标节点，再修改这些节点的关系键。
- **合并。** 没有专门的操作：先把边改指到保留的节点，移过别名，再删除被并入的节点（例 W6）。
- **只交差异也可以。** 只交被修改的节点，甚至只交被修改的那一个关系键，结果与交回整份视图相同。“交一份完整的 YAML 文档”的意思是交一份 YAML 格式的子图；没改的部分带不带都可以。
- **并发。** 乐观检测。求差在事务之外读取现状，变更集记下改前值；提交时 graph-vc 在事务中核对改前值与库中当前值，不一致就抛出 `ConflictError`，整批不写，由 Agent 重新读取后再交。这只能发现 dry_run 读取之后库被改动；Agent 读视图时所在的提交可以作为 `base` 记入 Commit，但还没有用它判断视图是否过期（§9.2）。

## 4. 调用与返回

```text
graph-doc ──dry_run──▶ graph-plan ──(无阻塞项)──▶ apply ──▶ graph-result
    ▲                      │
    └─── Agent 按 errors 改文档后重交 ───┘
```

| 调用 | 输入 | 职责 | 返回 |
| --- | --- | --- | --- |
| dry_run | graph-doc | 解析文档；按模型翻译成目标状态并检查格式、只读字段与引用；查重；计算与库中现状的差异；在内存中执行差异，复核写后状态（端点规则、必需字段与必需的边） | graph-plan |
| apply | 同一份 graph-doc | 先做一次 dry_run；没有阻塞项时分配 id，用真实 id 再做一次，然后在单事务中写入并记 Commit | graph-result |

调用参数除 graph-doc（`doc`）外，有 `source`、`message`、`base`、`apply`、`dedup`，它们都不是文档的键。`source` 是来源标签，记入提交的 `source` 与新 NameKey 的 `registered_from`（§2.5）。它可以省略：省略时记为调用所在的会话（`session:<会话 id>`），没有会话的调用（如命令行）仍须给出。

写后复核看的是改动节点及其邻居的完整状态，所以删除节点后，邻居缺了必需的边也会被发现。提交后补算向量；补算失败不回滚提交，只在 graph-result 的 `warnings` 中提示。提交时若发现库在 dry_run 之后被改动，返回 `status: conflict` 与不一致项（§3）。

**graph-plan**

| 键 | 内容 |
| --- | --- |
| `status` | `ready`、`blocked` 或 `noop` |
| `changes` | `create` 与 `delete` 列出模型节点；`update` 按节点列出改动的字段与关系键，改了 kind 记为 `kind`，增删了名称或别名记为 `names`；`edges` 是边的新建、修改、删除数；另有 `names`（NameKey 的增删数）与 `materials`（新登记的材料路径） |
| `errors` | 阻塞项，每项为 `{rule, at, msg}`，查重等需要判断的另带 `candidates`（每个候选给出 `ref`、`kind`、`name` 或 `text`，桩节点标 `stub`，查重命中的通道列在 `channels`），常见规则另带改法提示 `fix`。有任何一项时 apply 拒绝整批 |
| `warnings` | 不阻塞的提示：查重通道执行失败、删除的影响面、开放类型上的模型外属性 |

**graph-result**

| 键 | 内容 |
| --- | --- |
| `status` | `committed`；提交时发现冲突则为 `conflict`，`errors` 列出不一致项（`rule: conflict`，带改法 `fix`） |
| `commit` | 本次写入产生的 Commit id（§8） |
| `ids` | `$` 引用到新 id 的映射 |
| `counts` | 节点与边各自的新建、修改、删除数，含 NameKey 与 Material |
| `warnings` | 同 graph-plan，有提示时才出现 |

## 5. 检查

表中第二列是 graph-plan 中的 `rule`。

| 类别 | `rule` | 规则 | 处理方 |
| --- | --- | --- | --- |
| 格式 | `format`、`field`、`value` | 顶层键、`$` 引用与 id 的写法、未知字段、`by` 必填、新节点必须写 `kind`、属性值的类型与取值 | Agent 改文档 |
| 只读 | `readonly` | 改了 `_` 字段；修改 Artifact | Agent 改文档 |
| 引用 | `reference` | 引用既不在库中，也不是本文档的 `$` 引用 | Agent 改文档 |
| 端点 | `endpoint`、`relationship` | 关系类型与起点、终点的 kind 不符（graph_model 的端点规则）；改 kind 后原有的边按新的 kind 复核；边的必填属性与 `role` 取值 | Agent 改文档 |
| 必需字段与边 | `required-field`、`required-edge` | 例如 Observation 必须有 `ABOUT`，Claim 必须有 `FROM`，Experiment 必须有 `EVALUATES` | Agent 改文档 |
| 材料 | `material`、`locator`、`source-ref` | 材料路径不存在或已属于别的 Paper；更换已登记的材料；locator 越界；来源引用指向的节点没有材料 | Agent 改文档 |
| 唯一性 | `identifier-taken`、`name-taken`、`key-taken` | 唯一命名空间的标识、名称（NameKey）或自然键已属于另一个节点 | Agent 判断：同一对象就改用已有 id 修改它，否则更正 |
| 查重 | `dedup` | 新建的 Entity / Concept 有未判定的候选 | Agent 判断：换成已有 id，或写 `confirm.<引用>.distinct_from` |
| 修订 | `revision` | 改动或删除有据层记录（Experiment，`stated_by: paper` 的 Claim、Contribution 与正反关系）而没有写 `confirm.<id>.revise`；改动缺锚点；锚点格式错或超出该记录所属论文的行范围（报为 `locator`）。改 `note` 不算 | Agent 回原文核对：确实读错就写 `revise: {reason, anchor}`，删除只需 `reason`；否则不改 |
| 并存 | `coexist` | 改动别人形成的解释层记录（Observation，`stated_by: agent` 的 Contribution 与正反关系）的内容、删改它的出边或删除它；给它新增出边不受限 | Agent 不改别人的记录，另写自己的记录 |
| 删除 | `delete-impact` | 删除节点时一并删除的、来自其他模型节点的入边 | 只提示，不阻塞 |
| 并发 | — | 提交时改前值与库中当前值不一致（`ConflictError`，§3） | Agent 重新读取后再交 |

**查重的细节**

- **对象。** 只查新建的 Entity 与 Concept；Content 不查重，它的重复由自然键发现。
- **通道。** 查重经 Resolve 的写入模式执行。通道有标识、名称的精确命中，以及名称词面、文本词面、向量语义三路近邻，候选的 `channels` 记为 `identifier`、`name`、`lexical_name`、`lexical_text`、`semantic`。桩节点只有名称，只开名称词面通道。
- **为什么要逐个判断。** 语义通道没有阈值，库中只要有同类对象就会给出近邻，所以每个新对象都要经过一次明确的判断。通道执行失败（如向量服务不可用）只给提示，候选可能不全。
- **文档内部。** 同一文档中的新节点之间不互相查重。
- **不查重的写入。** 调用方可以关闭查重，用于种子这类经人工整理、可信的批量入库。是否查重记入 Commit 的 `meta.dedup`。

**修订与并存（2026-10-11）。** 修改是正常的写入，但按改前状态分层把关（[Commit 契约](../../../designs/v2/commit_contract.md) §5）：

- **有据层**记录说的是论文写了什么，分歧是暂时的错误。改动它是一次修订，必须写 `confirm.<id>.revise: {reason, anchor}`，`anchor` 是该记录所属论文中支持新内容的行范围；删除（撤回）只需 `reason`。锚点与理由记入提交的 `meta.revisions`，旧值留在版本历史中。出边的增删改算作起点的改动；删除另一端节点时连带删除的边不算。
- **解释层**记录是写入者的判断，没有单一真值。其他写入者可以读，也可以给它新增出边（如补一条 `ABOUT`）；改内容、删改出边或删除它只能由形成者本人做。有不同意见就另写一条，两者带着各自的来源并存。新增 agent 的正反关系不算修订它的起点 Claim。
- 实体与概念不在两层之内，照常修改。

自然键冲突只在新建或改键时检查。实现在 `e09/commit/revision.py`。

## 6. 场景示例

以下各段是一组连贯的例子：R 是读到的视图，W1–W7 是各种写入，P、P′、A 是中间件的返回。

### R　Agent 读到的视图

`Traverse(claim_0004, [SUPPORTED_BY out, USES out])` 的结果，另加几个相邻节点。写入时可以从这里改起，只读字段原样带回即可。

```yaml
graph-doc: v0.1
meta:
  query: {op: Traverse, start: [claim_0004], path: [{rel: SUPPORTED_BY, dir: out}, {rel: USES, dir: out}]}
  coverage: {returned: 8, truncated: false, snapshot: commit_0007}
  bindings:
    - [claim_0004, SUPPORTED_BY, exp_0001, USES, dataset_0002]

nodes:
  paper_0001:
    kind: Paper
    name: Are Transformers Effective for Time Series Forecasting?
    aliases: []
    identifiers: ["arxiv:2205.13504"]
    year: 2023
    material: papers/2023-DLinear/paper.md
    _material: material_1ec346c934e6
    description: Questions whether Transformer-based models are effective for LTSF and introduces DLinear …
    CITES:
      - to: paper_0002
        description: 表 2 中 FEDformer、Autoformer、Informer 的结果引自该文
        source_refs: ["material_1ec346c934e6::5.1 Experimental Settings::172:172"]

  method_0016:
    kind: Method
    name: DLinear
    aliases: []
    definition: A linear forecasting model that decomposes the input into trend and remainder …
    BROADER: [method_0011]

  dataset_0002:
    kind: Dataset
    name: ETTh1
    aliases: []
    identifiers: ["url:https://github.com/zhouhaoyi/ETDataset"]
    description: Hourly electricity transformer temperature data …
    PART_OF: [dataset_0001]

  exp_0001:
    kind: Experiment
    anchors: [S5.T2, A3.T9]
    text: 在九个数据集上比较 DLinear、NLinear 与五个 Transformer 基线的多变量长程预测 …
    FROM:
      - {to: paper_0001, locators: ["5.2 Comparison of Multivariate Forecasting with Transformers::198:240"], _material: material_1ec346c934e6}
    EVALUATES:
      - {to: method_0016, role: target}
      - {to: method_0005, role: baseline}
    USES:
      - {to: dataset_0002, role: evaluation_data}
    ON_TASK: [task_0002]
    EVALUATED_ON: [bench_0001]

  claim_0004:
    kind: Claim
    text: 在九个基准上，DLinear 在大多数设置下优于现有 Transformer 方法
    FROM:
      - {to: paper_0001, locators: ["Abstract::10:14"], _material: material_1ec346c934e6}
    ABOUT: [method_0016, task_0002]
    SUPPORTED_BY: [exp_0001]

  obs_0002:
    kind: Observation
    _formed_by: claude
    _formed_at: 2026-10-04T15:30:00Z
    text: 两文在 ETTh1 上的 96 步结果可比，但 PatchTST 的回看窗口更长 …
    ABOUT: [exp_0001, exp_0014, art_0003]
    FROM:
      - {to: art_0003, locators: ["Check::12:20"], _material: material_7a02c4f9e1b3}

  art_0003:                                           # Artifact：全部只读
    _op: Check
    _title: DLinear 与 PatchTST 在 ETTh1 上的可比性
    _abs: 核对两文 ETTh1 结果在切分、回看窗口与预测长度上的可比性 …
    _params:
      items: {dlinear: art_0002#method_0016-dataset_0002-96, patchtst: art_0002#method_0027-dataset_0002-96}
      pairs: all_pairs
      dimensions: [{id: split, question: …}, {id: lookback, question: …}, {id: horizon, question: …}]
    _formed_by: claude
    _formed_at: 2026-10-04T15:10:00Z
    _session: s-0412
    _material: material_7a02c4f9e1b3
    _document: artifacts/7a02c4f9e1b3.md
    _stale: []
    _USED:
      - {to: art_0002, role: [dlinear, method_0016-dataset_0002-96, method_0027-dataset_0002-96, patchtst]}
      - {to: paper_0001, locators: ["5.1 Experimental Settings::160:172"], _material: material_1ec346c934e6}
```

### W1　新论文第一次入库

新建论文、本文方法、实验、主张和自述贡献。已有对象只用 id 引用（先经 Resolve 解析）；被引用但尚未入库的论文和基线方法建为桩节点。

```yaml
graph-doc: v0.1
by: claude

nodes:
  $paper:
    kind: Paper
    name: "A Time Series is Worth 64 Words: Long-term Forecasting with Transformers"
    identifiers: ["arxiv:2211.14730"]
    year: 2023
    material: papers/2023-PatchTST/paper.md           # 登记 Material，哈希由中间件计算
    description: Proposes PatchTST, a channel-independent patch-based Transformer …
    CITES:
      - to: paper_0001
        description: 表 3 中 DLinear 的结果引自该文
        source_refs: ["$paper::4.1 Long-term Time Series Forecasting::210:212"]   # 新论文用临时引用定位

  $patchtst:
    kind: Method
    name: PatchTST
    aliases: [PatchTST/64, PatchTST/42]
    definition: A Transformer for multivariate forecasting that splits each channel into patches …
    BROADER: [method_0004]                            # Transformer-based time series forecasting
    HAS_PART: [method_0012, method_0013]              # Patching、Channel independence

  $timesnet:                                          # 桩节点：基线方法，原论文尚未入库
    kind: Method
    name: TimesNet
    stub: true

  $exp-t3:
    kind: Experiment
    anchors: [S4.T3, A1.T8]
    text: 在八个数据集上比较 PatchTST 与 DLinear 及 Transformer 基线的多变量长程预测 …
    FROM:
      - {to: $paper, locators: ["4.1 Long-term Time Series Forecasting::200:240"]}
    EVALUATES:
      - {to: $patchtst, role: target}
      - {to: method_0016, role: baseline}
      - {to: $timesnet, role: baseline}
    USES:
      - {to: dataset_0002, role: evaluation_data}
    ON_TASK: [task_0002]

  $claim-sota:
    kind: Claim
    text: PatchTST 在长程预测上显著优于此前的 Transformer 模型
    FROM:
      - {to: $paper, locators: ["Abstract::8:12"]}
    ABOUT: [$patchtst, task_0002]
    SUPPORTED_BY: [$exp-t3]

  $contrib-patch:
    kind: Contribution
    stated_by: paper
    text: 提出按子序列切块作为 Transformer 的输入单元
    FROM:
      - {to: $paper, locators: ["1 Introduction::60:66"]}
    ABOUT: [$patchtst, method_0012]
```

### P　W1 的 dry_run 返回

库中已有 PatchTST 论文的桩节点 `paper_0003`，标识相同。有阻塞项时不计算差异，所以没有 `changes`。

```yaml
graph-plan: v0.1
status: blocked                                       # ready | blocked | noop
errors:
  - rule: identifier-taken
    at: nodes.$paper.identifiers[0]
    msg: arxiv:2211.14730 already identifies
    candidates: [{ref: paper_0003, kind: Paper, name: "A Time Series is Worth 64 Words …", stub: true}]
    fix: "if it is the same object, edit the existing node by id; otherwise correct the identifier"
  - rule: dedup
    at: nodes.$paper
    msg: 2 possible duplicate(s) not yet judged
    candidates:
      - {ref: paper_0003, kind: Paper, name: "A Time Series is Worth 64 Words …", stub: true,
         channels: [identifier, lexical_name, semantic]}
      - {ref: paper_0001, kind: Paper, name: Are Transformers Effective for Time Series Forecasting?,
         channels: [semantic]}
    fix: "same object: replace $paper with the candidate id; different: list it in confirm.$paper.distinct_from"
  - rule: dedup
    at: nodes.$patchtst
    msg: 1 possible duplicate(s) not yet judged
    candidates: [{ref: method_0004, kind: Method, name: Transformer-based time series forecasting, channels: [semantic]}]
    fix: "same object: replace $patchtst with the candidate id; different: list it in confirm.$patchtst.distinct_from"
```

语义通道会给出所有相近的同类对象，所以 `paper_0001` 也成了 `$paper` 的候选，需要明确判断。`$timesnet` 是桩节点，只查名称词面，这里没有候选。

### W2　查重往返：按 P 修改后重交

- 判定是同一对象：把 `$` 引用全部换成已有 id，节点内容就变成对已有节点的修改（这里顺带补全桩节点）。
- 判定不是同一对象：在 `confirm` 中写 `distinct_from`。

```yaml
graph-doc: v0.1
by: claude
confirm:
  $patchtst: {distinct_from: [method_0004]}           # 候选 method_0004 是类别，不是 PatchTST 本身

nodes:
  paper_0003:                                         # 原来的 $paper：库中已有它的桩节点
    stub: null                                        # 清掉桩标记 = 补全
    kind: Paper
    name: "A Time Series is Worth 64 Words: Long-term Forecasting with Transformers"
    identifiers: ["arxiv:2211.14730"]
    year: 2023
    material: papers/2023-PatchTST/paper.md
    description: Proposes PatchTST …
    CITES:
      - to: paper_0001
        description: 表 3 中 DLinear 的结果引自该文
        source_refs: ["paper_0003::4.1 Long-term Time Series Forecasting::210:212"]

  $patchtst:
    kind: Method
    name: PatchTST
    definition: …
    BROADER: [method_0004]

  # $exp-t3、$claim-sota、$contrib-patch 同 W1，其中的 $paper 全部换成 paper_0003（略）
```

### A　W2 的 apply 返回

```yaml
graph-result: v0.1
status: committed
commit: commit_000008
ids:
  $patchtst: method_0022
  $timesnet: method_0023
  $exp-t3: exp_0023
  $claim-sota: claim_0031
  $contrib-patch: contrib_0012
counts: {nodes_created: 8, nodes_updated: 1, nodes_deleted: 0, edges_created: 19, edges_updated: 0, edges_deleted: 0}
```

计数包括系统节点与系统边。新建的 8 个节点是 5 个模型节点、1 个 Material，以及 PatchTST、TimesNet 两个 NameKey；边数只作示意。

### W3　在读到的视图上修改已有节点

这份文档从 R 改出来，只保留了改动过的节点。示例涉及：修改属性、清空属性、增删别名、增删边、修改边属性、修改 kind。

```yaml
graph-doc: v0.1
by: claude

nodes:
  method_0016:
    kind: Method
    name: DLinear
    aliases: [Decomposition-Linear]                   # 加别名：注册一条 NameKey
    definition: >                                     # 改属性
      A linear forecasting model that decomposes the input into a moving-average trend and a
      remainder, maps each with a one-layer linear layer along time, and sums the outputs.
    note: null                                        # 清空属性
    BROADER: [method_0011]

  exp_0001:
    kind: Experiment
    anchors: [S5.T2, A3.T9]
    text: 在九个数据集上比较 DLinear、NLinear 与五个 Transformer 基线的多变量长程预测 …
    FROM:
      - {to: paper_0001, locators: ["5.2 Comparison of Multivariate Forecasting with Transformers::198:240"], _material: material_1ec346c934e6}
    EVALUATES:
      - {to: method_0016, role: target}
      - {to: method_0005, role: baseline}
      - {to: method_0007, role: baseline}             # 加一条边
    USES:
      - {to: dataset_0002, role: evaluation_data}
    ON_TASK: [task_0002]
    # EVALUATED_ON 键整个不写：不动

  dataset_0009:
    kind: Benchmark                                   # 改 kind：Dataset → Benchmark；id 不变，原有边按新端点规则复核
    PART_OF: []                                       # 删掉全部 PART_OF 出边
```

### W4　依据读到的子图追加理解

示例包括：新建 Issue 并把已有 Claim 挂上去；Agent 判断的正反关系；Observation；Agent 认为的贡献。依据可以是论文原文，也可以是 Artifact 文档，后者相当于把工作产物提升为长期记录。

```yaml
graph-doc: v0.1
by: claude

nodes:
  $linear-vs-tf:
    kind: Issue
    text: 线性模型能否在长程预测上替代 Transformer
    description: 关键在回看窗口、归一化与通道处理是否一致

  claim_0004:
    ABOUT: [method_0016, task_0002, $linear-vs-tf]    # 给已有 Claim 加 ABOUT：只交这个关系键

  claim_0011:
    ABOUT: [method_0022, task_0002, $linear-vs-tf]
    SUPPORTS: []
    OPPOSES:
      - to: claim_0004
        stated_by: agent                              # Agent 判断的正反关系；_formed_by 取自 by
        description: 在回看窗口为 336 时 PatchTST 优于 DLinear，与 claim_0004 的结论相反

  $obs-comparable:
    kind: Observation
    text: 两文 ETTh1 的 96 步结果切分一致、回看窗口不同，直接比较需要说明窗口差异
    ABOUT: [exp_0001, exp_0014, art_0003]
    FROM:
      - {to: art_0003, locators: ["Check::12:20"]}    # 依据是 Artifact 文档的行
      - {to: paper_0001, locators: ["5.1 Experimental Settings::160:172"]}

  $contrib-agent:
    kind: Contribution
    stated_by: agent
    text: 这篇论文促使后续工作在比较时报告回看窗口
    FROM: [paper_0001]                                # Agent 贡献：连到所属论文，可不带定位
    ABOUT: [paper_0001]
```

### W5　删除节点

把节点写成 `null`，它的全部入边和出边一并删除。

```yaml
graph-doc: v0.1
by: claude

nodes:
  obs_0002: null
```

### P′　W5 的 dry_run 返回

删除不需要二次确认：graph-plan 只列出影响面，删错了可以用 `Revert` 撤销。下面假设 `claim_0019` 有一条 `SUPPORTED_BY` 边指向 `obs_0002`。

```yaml
graph-plan: v0.1
status: ready
changes:
  create: []
  update: {}
  delete: [obs_0002]
  edges: {create: 0, update: 0, delete: 5}
warnings:
  - rule: delete-impact
    at: nodes.obs_0002
    msg: "also removes 1 incoming relationship(s): claim_0019-[SUPPORTED_BY]->obs_0002"
```

影响面只列来自其他模型节点的入边；随节点一起删除的出边，以及 NameKey、Material 等系统边，不列在这里。

### W6　合并（组合写法）

`method_0021` 与 `method_0016` 是同一方法，保留 `method_0016`。前提是先 Traverse，取得 `method_0021` 的全部入边、出边，以及指向它的节点。

```yaml
graph-doc: v0.1
by: claude

nodes:
  method_0016:
    aliases: [Decomposition-Linear, D-Linear]         # 把 method_0021 的名称挪过来
    BROADER: [method_0011]

  exp_0007:                                           # 原来 EVALUATES 指向 method_0021 的实验
    EVALUATES:
      - {to: method_0016, role: baseline}
      - {to: method_0002, role: target}

  claim_0019:                                         # 原来 ABOUT 指向 method_0021 的主张
    ABOUT: [method_0016]

  method_0021: null                                   # 最后删掉被并入的节点
```

### W7　会被拒绝的写法

```yaml
graph-doc: v0.1
by: claude

nodes:
  art_0003:
    _title: 改个标题                                   # 错误：Artifact 只由 Agent 算子写入
  obs_0002:
    _formed_by: someone-else                          # 错误：改了只读字段
  method_0016:
    EVALUATES: [method_0005]                          # 错误：Method 不能有 EVALUATES 出边（端点规则）
  $orphan:
    kind: Observation
    text: …                                           # 错误：Observation 必须有 ABOUT
  claim_0004:
    ABOUT: [method_9999]                              # 错误：引用不在库中，也不是本文档的 $ 引用
```

## 7. 与现行操作集的对应

| 现行操作（commit_contract §3） | graph-doc 中的写法 |
| --- | --- |
| `create_object` | 新的 `$` 节点；桩节点写 `stub: true` |
| `register_name` | 增加 `aliases` 的元素（删除元素即撤销） |
| `fill_stub` | 在已有桩节点上写属性并写 `stub: null`；不再限于只填空字段 |
| `add_material` | Paper 上的 `material` |
| `add_experiment`、`add_content` | 新的 Content `$` 节点及其关系键 |
| `link` | 关系键，任意关系类型都可写 |
| `record_batch` | 每次 apply 产生一个 Commit 记录，取代 IngestBatch（§8） |
| 修订、撤回、合并（原先不做） | 修改属性与关系键、写 `null` 删除、组合写法（W3、W5、W6） |
| Issue、Proposition（原先无写入路径） | 与其他 Concept 一样新建和修改（W4） |

## 8. 版本管理（规划）

> 本节是工程规划，尚未实现，也尚未评估。各项机制以 graph-doc 的写入语义为基础；分支的存储方式、视图选择与回流规则仍待讨论（§9）。

### 8.1 定位

我们不研究如何优化版本控制，而是让学术资源管理系统支持版本管理，并提供配套的机制。版本管理服务于两件事：

- **全局与项目两个范围的知识管理。** 全局库从 main 分出项目分支（fork）。项目在自己的分支上演进：建立项目视图、写入 Artifact、追加理解。项目分支可以吸收 main 的更新，也可以把经过检验的成果回流到 main。
- **让 Agent 的知识持久化过程可追溯。** 对某个 Method、Issue 或 Claim 的理解是如何一步步形成和修改的，由谁写入，当时依据哪些 Artifact、做过哪些查重判断，都可以按时间顺序查询。

要区分两条链：Artifact 的 `USED` 边是**输入来源**，记录一个产物用了哪些对象；Commit 的父链是**提交祖先**，记录知识状态由哪些写入演变而来。两条链各自独立。

### 8.2 Commit 记录

每次写入产生一个 Commit 记录，取代 IngestBatch。Commit 是系统记录（与 Material、NameKey 同层），只服务于数据管理机制，不进入 graph model 的学术层，graph_model 因此不需要修改。

**统一的写入底层。** 对图的修改都经过同一个底层 util：输入一份解析后的变更集，在单事务中执行这些修改并写入 Commit 记录。Commit 工具（graph-doc）和 Agent 算子（Artifact）是这个底层的两个上游：

```text
graph-doc ──dry_run / apply──┐
                             ├──▶ 变更集 ──▶ apply-changeset（单事务：改图 + 写 Commit）
Agent 算子 ──校验──▶ Artifact ─┘
```

不计空间成本，每个 Commit 保存三类内容：

| 内容 | 作用 |
| --- | --- |
| 交上来的输入原文：graph-doc，或 Agent 算子的调用参数 | 记录写入者想要什么；也用于评估 Agent 的行为，如来回轮数与查重判断 |
| 解析后的变更集：每个改动的属性和每条边，改前与改后的值；`$` 引用已换成 id | 真正的版本数据，支撑 log、diff、按时间点还原、撤销和追查改动来源 |
| 元数据：父 Commit、分支、写入者、时间、来源、`base`、`confirm`、轮数 | 提交祖先链与写入过程的记录 |

只存输入原文不够。graph-doc 的语义是“不写就不动”，`$` 引用和查重判断又依赖写入时的库状态，所以单凭输入原文无法还原历史状态，也无法撤销。

以 §6 的 W2/A 为例：

```yaml
commit: commit_0008
parents: [commit_0007]
branch: main
by: claude
at: 2026-10-05T10:12:00Z
source: {tool: Commit}                 # Agent 算子写入时为 {operator: Check, artifact: art_0004}
base: commit_0007                      # 写入者读视图时所在的 Commit
rounds: 2                              # dry_run 来回轮数
confirm:
  $patchtst: {distinct_from: [method_0004]}
ids: {$patchtst: method_0022, $timesnet: method_0023, $exp-t3: exp_0023, $claim-sota: claim_0031, $contrib-patch: contrib_0012}
input: |                               # 交上来的 graph-doc 原文
  graph-doc: v0.1
  by: claude
  …
changes:
  nodes:
    paper_0003:
      op: update
      props:
        stub: {before: true, after: null}
        year: {before: null, after: 2023}
        description: {before: null, after: Proposes PatchTST …}
    method_0022:
      op: create
      after: {kind: Method, name: PatchTST, definition: …}
    method_0023:
      op: create
      after: {kind: Method, name: TimesNet, stub: true}
    # …
    patchtst|method|global:                            # NameKey 也是普通节点，id 就是 key
      op: create
      after: {key: patchtst|method|global, raw: PatchTST, kind: Method, registered_by: claude, registered_from: commit-tool, …}
    material_9c41d2a07b18:
      op: create
      after: {path: papers/2023-PatchTST/paper.md, format: markdown, content_hash: 9c41d2a07b18…}
    # …
  edges:
    - {op: create, type: CITES, from: paper_0003, to: paper_0001,
       after: {description: 表 3 中 DLinear 的结果引自该文, source_refs: ["material_9c41d2a07b18::4.1 …::210:212"]}}
    - {op: create, type: BROADER, from: method_0022, to: method_0004}
    - {op: create, type: NAMES, from: patchtst|method|global, to: method_0022}
    - {op: create, type: MATERIAL_OF, from: material_9c41d2a07b18, to: paper_0003}
    # …
  files:
    - {path: papers/2023-PatchTST/paper.md, sha256: 9c41d2a07b18…}
```

变更集的约定：

- **删除。** `op: delete` 记录被删节点的全部属性（`before`），连同的边逐条记为 `op: delete`，带边属性的 `before`，所以每个 Commit 都可以逆向执行。
- **边的标识。** 一条边由起点、类型和终点确定。修改边属性记为 `op: update`。
- **派生字段。** 向量这类派生字段不进入变更集，重放或撤销后重新计算。自然键要靠它发现重复提交，所以作为普通属性记入变更集。
- **系统节点。** 名称与材料的增删就是 NameKey、Material 节点及其 `NAMES`、`MATERIAL_OF` 边的增删，不另设专门的段。

**实现（graph-vc）。** Commit 节点上的属性见 `packages/graph-vc/README.md`，与上例的对应如下：

| 上例 | 实现 |
| --- | --- |
| `commit`、`parents`、`branch`、`by`、`at`、`source`、`base`、`input` | `id`、`parent`（线性历史只有一个父提交）、`branch` 与分支内序号 `seq`、`author`、`at`、`source`、`base`、`input` |
| `changes` | `changeset`（JSON） |
| `ids` | `meta.ids`；`meta.dedup` 记这次写入是否查重 |
| `confirm` | 不单独保存，留在 `input` 原文中 |
| `rounds` | 尚未计数（§9.2） |
| — | `message`：调用方给的说明，可选 |
| — | `touched`、`removed`：本次触及且仍存在的节点、本次删除的节点（采纳 §10.3 建议 5） |

### 8.3 Commit 在图中的表示

- **节点与父链。** Commit 是一个节点，带 `PARENT` 边指向父 Commit。线性历史只有一个父 Commit；回流合并（§8.6）时有两个。
- **指向被写入的节点。** Commit 用 `TOUCHED {op}` 边连到本次新建或修改、并且仍然存在的节点。这些边只是索引，用来快速回答“这个节点被哪些 Commit 改过”。被删的节点和边的修改只记在变更集里；以变更集为准。
- **与学术层隔离。** Search、Traverse 默认排除 Commit 节点和 `TOUCHED` 边，以免它们混进学术层的遍历结果。版本信息由 §8.4 的算子查询。
- **大字段的存放。** 输入原文和变更集可以直接存成节点属性；也可以像 Artifact 文档那样存为文件，节点上只记路径与哈希。实现时再定。

### 8.4 历史查询

这些是机制层的算子，与学术层算子分开列出。下表只是规划，契约待写；目前只有 `Revert` 已由 graph-vc 实现，`graph.history()` 与 `graph.snapshot()` 可作为 `Log` 与当前状态读取的底层。

| 算子 | 作用 |
| --- | --- |
| `Log` | 按时间顺序列出 Commit；可以按分支、写入者、来源（Commit 工具或某个 Agent 算子）、时间范围过滤，也可以只列触及某个节点的 Commit |
| `Show` | 一个 Commit 的完整记录 |
| `Diff` | 两个 Commit 之间，或一个分支相对它的分叉点，节点与边的差异，用 graph-doc 的形状给出 |
| `AsOf` | 某个 Commit 时一个节点或一个子图的状态：从当前状态出发，逆向执行之后的变更集 |
| `Blame` | 一个节点上每个属性和每个关系键最后由哪个 Commit 写入 |
| `Revert` | 把一个 Commit 的逆向变更集作为一个新 Commit 写入，不改写历史 |

### 8.5 Artifact 的特殊处理

Artifact 写入同样产生 Commit（`source: operator:<op>`，`meta: {artifact, session}`，`files` 记文档的路径与哈希），走同一个写入底层（`docs/designs/v2/operators.md` §5.5）。区别在于它的文档存放在文件系统中，不在图里：

- **文件按内容寻址，写入后不再改动。** 文件为材料根目录下的 `artifacts/<内容哈希前 12 位>.md`，Commit 记录文档的路径与哈希。Artifact 只读，所以文件的版本只有一个。
- **只写不删。** 分支操作和 Revert 只改变 Artifact 节点在某个分支上是否存在，不删除文件。即使 Artifact 节点被删除，文件仍然保留，否则 `AsOf` 和重放会失效。
- **随 Commit 走。** 文档文件放在 git 之外（E09 为 `data/raw/e09-paper-knowledge/artifacts/`），Commit 链才是它的版本记录。重放时要求文件存在，并且哈希一致。
- **论文材料同理。** Paper 的材料也按路径加哈希记入变更集（`changes.materials`）。

### 8.6 分支：全局与项目

| 操作 | 含义 |
| --- | --- |
| `main` | 全局库 |
| `Fork(base, name)` | 从 main 的某个 Commit 分出项目分支。这个 Commit 就是项目的基线（AGENTS.md 所说的 defined baseline） |
| `Branch(base, name)` | 在项目内（或 main 上）分出试探线，例如对同一个 Issue 的两种整理方式 |
| `Sync(project)` | 把 main 在分叉点之后的 Commit 带进项目分支 |
| `Promote(project, commits)` | 把项目分支上选定的 Commit 回流到 main，形成一个有两个父 Commit 的合并 Commit |

**冲突检测。** 变更集记录了 `before`，所以把一个变更集应用到另一条分支时，只需逐项核对 `before` 是否等于目标分支的当前值：

- 全部一致：直接应用。
- 不一致：说明两边改了同一个属性或同一个关系键，记为冲突。同一节点上一边删除、一边修改，也是冲突。
- 冲突交给 Agent 处理：读两边的值，交一份 graph-doc 作为决议，这和平时的写入是同一流程。

同一机制也可以用于 main 上的并发检测：写入时如果带上 `base`，就能发现读到的视图已经过期，补上 §3 乐观检测发现不了的那部分。

**回流时还要处理：**

- **id 不冲突。** id 由全局计数器分配，与分支无关，因此回流时不会撞号。
- **重复对象。** 项目分支和 main 可能各自建了同一个对象，比如两边都入库了同一篇论文。所以回流前要按 dry_run 的规则重新查重，判定结果与 `confirm` 一并记入合并 Commit。

**项目视图与分支的关系。** 项目视图是从项目分支上按选择规则取出的一部分（选择算法待定）。分支提供独立演进与隔离，视图决定项目里用到哪些知识。

**物化方式（待定）。** 论文规模下最简单的做法是每条分支各存一份完整的图（复制），所有分支共用同一条 Commit 链。其他候选：

- main 物化存储，项目分支只存叠加的变更集，读取时合成；
- 节点和边带分支、有效区间等属性。

Neo4j 社区版只支持一个用户数据库，所以按分支复制需要多个实例，或在同一个库内用命名空间区分。

### 8.7 不变式

这几条既是实现时必须通过的检查，也是版本管理正确性的实验证据：

1. **重放一致。** 从空库按顺序重放某条分支上的全部 Commit，得到的状态与该分支的当前状态相同（派生字段重新计算）。
2. **可逆。** 对每个 Commit，从写入后的状态逆向执行它的变更集，得到写入前的状态。
3. **原子。** 图的修改与 Commit 记录在同一个事务里，不存在没有 Commit 的修改。
4. **文件完整。** Commit 引用的每个文件（材料、Artifact 文档）都存在，并且哈希一致。

## 9. 已定与待定问题

原先的问题编号保留，§10 按编号引用它们。

### 9.1 已定（实现中落地，2026-10-05）

- **问题 1　`confirm` 段。** 键名定为 `confirm`，每项只有 `distinct_from`，列出判定为不同对象的已有 id。它不入图，随 `input` 原文记入 Commit 记录。
- **问题 2　删除不需要二次确认。** 取消 `delete_ok`。graph-plan 在 `warnings` 中列出影响面（P′），删错了用 `Revert` 撤销。
- **问题 3　来源引用读写不对称。** 按 §2.4 实现：写入时开头可以是 `$` 引用、节点 id 或材料 id，入库时一律换成材料 id。
- **问题 4　只接受 id 和 `$` 引用。** 按此实现，`{mention, kind}` 引用取消。
- **问题 6　改 kind 时 id 不变。** 现行实现接受：改 kind 只换 Label，id 保持不变，原有的边按新 kind 复核（W3）。id 的类型前缀因此可能与 kind 不符，id 只作标识，不用来判断类型。
- **问题 8　用 `stub: null` 补全桩节点。** 按此实现：`stub` 只能写 `true` 或不写，补全时写 `null` 清掉。
- **NameKey。** `id` 就是 `key`，从而纳入版本管理；`registered_from` 填调用方给的来源标签（§2.5）。
- **自然键。** `content_key` 用新建时的 `$` 引用名生成，之后不变（§2.5）。
- **种子入库不查重。** 调用方可以关闭查重，用于可信的批量入库，是否查重记入 `meta.dedup`（§5）。
- **文档内部不查重。** 同一文档中的新节点之间不互相查重。
- **更换材料。** Paper 登记材料后暂不支持更换或清空（§2.4）。
- **Metric 不建节点。** 冻结的模型中没有 Metric。旧表单中的指标在转换成 graph-doc 时写进 Experiment 的 `text`。
- **问题 12　graph-doc 不能写入或删除 Artifact。** Artifact 只由 Agent 算子写入；读视图原样带回的 Artifact 被忽略，写了字段或写 `null` 删除都是 `readonly` 错误。删除被 `USED` 指向的节点时，graph-plan 提示用过它的 Artifact 将显示为可能过期。
- **向量补算失败不回滚。** 向量是提交后补算的派生属性，向量服务不可用时只给提示，提交保留，之后再补。

### 9.2 仍待定

- **问题 5　轮数。** `by` 已兼作提交者。dry_run 的来回轮数尚未计数，仍需决定中间件如何判定几次 dry_run 属于同一次提交。
- **问题 7　`meta.bindings` 的格式。** 路径绑定目前写成交替排列的节点与关系的列表。读视图渲染时再定。
- **问题 9　分支的物化方式。** 见 §8.6。
- **问题 10　fork 与 branch 是否需要区分。** 两者的机制相同，区别在于用途。
- **问题 11　project 回流到 main 的粒度。** 可以按 Commit 挑选，也可以按节点或子图挑选。按子图挑选会切断 Commit 的完整性，需要重新生成变更集。
- **问题 13　写入是否必须带 `base`。** 现在 `base` 可选，只记录、不使用。乐观检测（§3）只能发现 dry_run 之后的改动，不能区分“被别人改过”与“读的视图已过期”。

## 10. TerminusDB 调研：工程见解与改进建议（2026-10-05）

> 依据：`references/repos/terminusdb` 源码（SWI-Prolog 服务，存储引擎为外部的 terminusdb-store Rust crate）与官方文档 [Graphs Explanation](https://terminusdb.org/docs/graphs-explanation/)。本节是调研记录与建议，**尚未改动 §8、§9 的设计**；采纳后再落实到相应小节。

### 10.1 TerminusDB 的机制要点

| 机制 | 做法 | 源码位置 |
| --- | --- | --- |
| 存储 | 不可变、内容寻址的层（layer）：基础层是全量快照，子层是 delta（正平面新增 + 负平面删除 + 父指针）；读沿父链级联，子层命中优先，被后代负平面删除的祖先条目被过滤 | terminusdb-store（未含在本仓库）；绑定在 `src/rust/` |
| 读取成本 | 查询沿层链深度线性退化，约 10 层可感；因此有 `rollup`（原地压平为基础层，头 id 不变）与 `squash`（生成无父新基础层）两个压实 API | `src/core/api/api_rollup.pl`、`api_squash.pl` |
| 提交图即数据 | ref schema 定义 `Branch { name, head }`、`Commit { identifier, author, message, timestamp, parent（单父）, schema: Layer, instance: Layer, instance_added/updated/removed, metadata }`；分支只是指向 Commit 的文档，reset / fast-forward 是纯指针移动 | `src/terminus-schema/ref.json`、`src/core/transaction/ref_entity.pl` |
| 寻址 | descriptor 链 `database → repository → branch \| commit`；历史访问 = commit id → 层 id → 只读打开，没有专门的 checkout | `src/core/transaction/descriptor.pl` |
| 整合 | 没有三方内容合并，也没有双父合并 Commit：只能 fast-forward，否则 rebase——从共同祖先起把己方 Commit 的 delta 逐个 `nb_apply_delta` 盲重放到对方头上，每条重放后重新过 schema 校验，策略 `error \| continue \| fixup`；校验失败可记为 `InvalidCommit` 而非中断 | `src/core/api/db_rebase.pl`、`db_fast_forward.pl`、`ref_entity.pl:805-852` |
| 文档级 diff | 三元组层上每个子层本身就是 diff；文档层有 `simple_diff`（JSON patch）与 `api_apply_squash_commit`：算两个版本的文档 diff，作为**新 Commit** 应用到目标 | `src/core/document/diff.pl`、`src/core/api/api_patch.pl:168-260` |
| diff 加速 | 两版本比较时先找共同祖先，取两侧 Commit 链上 changed-set（`instance_added/updated/removed`）的并集圈定候选文档，不全库比较 | `src/core/document/history.pl:138-155` |
| schema / instance | 两条并行的层链，每个 Commit 各带一个层指针；instance 变更过 schema 校验后才接受，schema 变更触发迁移推断 | `ref.json`、`src/core/transaction/database.pl:284-338` |

### 10.2 与本设计同构的部分

§8 的逻辑模型与 TerminusDB 已经一致，调研结果是验证而非推翻：

| 本设计 | TerminusDB 对应 |
| --- | --- |
| Commit 节点 + `PARENT` 边，提交图与学术层隔离 | ref graph 与 instance graph 分离，提交图本身是可查询的图数据 |
| 变更集记 `before`/`after`，支撑撤销与还原 | 子层 delta（正/负平面）；本设计记双向值，比它的单向 delta 多支撑逆向执行 |
| 分支 = 指向 Commit 的指针，fork/branch 同机制 | `Branch.head` 文档；分支创建只写一个文档 |
| `Revert` 不改写历史 | reset 只移动分支头，层与 Commit 对象不动 |
| Artifact / 材料文件内容寻址、只写不删 | 层内容寻址、不可变 |
| 冲突交 Agent 以 graph-doc 决议 | rebase 的 `fixup` 策略位（它用 WOQL，本设计用正常写入流程，更符合责任边界） |

### 10.3 改进建议

1. **Sync / Promote 改为“重放 + `before` 校验”，取消双父合并 Commit（§8.6）。** TerminusDB 的 Commit 是单父，整合只有 fast-forward 与 rebase。本设计的变更集带 `before`，比它的盲重放更强：重放每个 Commit 时逐项核对 `before` 与当前值即可在写入前发现冲突，冲突时暂停、由 Agent 交 graph-doc 决议（占据 `fixup` 的位置），决议本身是一个新 Commit。历史保持线性、每条 Commit 的变更集都真实执行过，§8.7 不变式 1 的适用范围随之扩大；双父合并 Commit 的“变更集”是两个父状态的综合，需要专门定义，可因此移除。可选：借 `continue` / `InvalidCommit` 思路，允许重放时校验失败的 Commit 标记为 invalid 记录在链上，用于项目分支一次性吸收 main 大量变更的场景。
2. **子图回流收敛为 diff-then-apply（§9 问题 11）。** 参照 `api_apply_squash_commit`：计算项目分支 `base ↔ head` 之间、限定在选定节点集上的差异（`Diff` 已能给出 graph-doc 形状），把这份差异当作一份 graph-doc 在 main 上走正常 dry_run/apply——查重、端点校验、`confirm` 全部复用，生成的普通 Commit 自带重新计算的变更集，不存在“切断 Commit 完整性”的问题。回流因此统一为两条已明确的路径：按 Commit 挑选 = 重放（建议 1），按子图挑选 = diff-then-apply。
3. **补 `Squash` / `Checkpoint` 压实算子与“压实无损”不变式（§8.4、§8.7）。** `AsOf` 从当前状态逆向重放，成本随目标与 HEAD 的距离增长，而“重访旧报告所依据的知识状态”恰恰访问旧状态、历史越长越贵——这正是 TerminusDB 需要 rollup/squash 的原因（方向相反，问题相同）。建议增加一个压实操作：把某段历史压成携带全量快照或净变更集的 Checkpoint Commit，`AsOf` 与重放从最近的 Checkpoint 出发；§8.7 补不变式“压实后 `AsOf`/`Diff`/`Blame` 结果与压实前一致”。这同时控制不变式 1 的实验成本（不必每次从空库重放）。
4. **分支物化倾向整图复制（§8.6、§9 问题 9）。** 候选二（main 物化、项目分支存叠加变更集、读取合成）本质是在应用层重新实现 TerminusDB 的分层存储，会完整继承它的深度-成本问题，且 Neo4j 上没有对应的简洁索引，合成读每次都要重放 N 个变更集；走这条路则建议 3 的压实从可选变为必需。论文规模下候选一（每条分支一份完整图、共用 Commit 链）最简单，delta 叠加留作实现章节有依据的备选。
5. **Commit 记录补 `removed` 索引与可选 `message`（§8.2、§8.3）。** TerminusDB 在 Commit 上记 `instance_added/updated/removed` 三组集合；本设计的 `TOUCHED` 只覆盖仍存在的节点，被删节点只埋在变更集里，“哪些 Commit 删过节点 X”“本分支净删了哪些节点”都要扫变更集。在 Commit 节点上加 `removed: [...]` 列表属性成本很低，使 `Log` 过滤与 `Diff` 候选圈定对增删改一致。另：它的 Commit 强制 `message`，建议 graph-doc 顶层加可选 `message` 记入元数据，`Log` 可读性主要靠它。
6. **`Diff` 写明加速路径（§8.4）。** 照搬 `commits_changed_id`：先找共同祖先，取两侧链上 changed-set（`TOUCHED` ∪ `removed`）的并集，只比较这些节点。
7. **明确不借鉴的部分，避免范围膨胀。** repository graph / push-pull / 多实例同步（无远程协作场景）；commit graph 自身再版本化（它的 repository head 链为同步服务）；内容寻址的层 id（序列 id + `PARENT` 链足够，文件哈希已在 §8.5 承担内容寻址）。

### 10.4 对实现章节的约束

TerminusDB 的以下性质依赖其专用不可变分层存储，Neo4j 上没有对应物，本设计需在应用层自行承担：

- **不可变内容寻址层**——O(1) 分支与廉价历史打开的前提；Neo4j 上分支意味着整图复制或变更集叠加（§9 问题 9 因此是真问题）。
- **负平面级联删除读**——历史查询在存储索引内完成；本设计的逆向重放把这笔成本放在 `AsOf` 上，由建议 3 的压实控制。
- **`nb_apply_delta` 盲重放**——依赖三元组的全局稳定身份；本设计的节点 id（全局计数器、与分支无关，§8.6）加上变更集的 `before` 校验，已经构成等效且更强的重放基础。

## 11. 理论建议：项目知识的选择性继承与版本化演化（2026-10-05）

> 本节整理当前讨论形成的理论建议。项目知识视图、完整提交记录和版本历史属于已确认范围；下述初始化方式、历史保留策略与 Summarize 扩展仍需收敛契约、实现和评价。本节不改动 §8–10 的工程安排，也不预先确定单父／多父历史、分支物化或压实方案。两篇必需引用的参照论文列于 §11.7。

### 11.1 理论主线：从全局论文经验到项目工作基础

版本管理服务于全局与项目两个范围中的知识选择、使用、积累和整合。方法叙事围绕项目知识的生命周期组织：

> **系统支持从全局论文经验中选择并构造项目知识状态，允许通过固定引用和 Agent 生成的摘要组织未纳入的历史上下文，并以独立的提交历史管理项目后续的使用与演化。**

具体过程为：确定全局基线 → 选择知识并组织必要上下文 → 建立项目起点 → 使用知识并提交新产物 → 开展独立探索 → 显式吸收或回流知识 → 核查历史状态。子图选择决定项目纳入什么；版本机制使起点、后续变化和各条路线的状态可确定。

理论需要定义这些操作的输入、输出、身份、作用域和正确性条件。全量复制、检查点、delta 与对象共享属于实现选择；本项目不以版本控制性能优化为研究目标。需要报告构建、使用和维护成本，但不把零复制或某种索引作为版本管理成立的条件。

### 11.2 分别定义知识状态、形成来源与项目历史

**继承知识状态与继承形成历史是两个独立选择。** 项目可以继承一组对象的选定状态，而不把这些对象的全部历史以及所有上游论文都纳入本地库。

| 关系 | 表达的含义 | 在项目中的作用 |
| --- | --- | --- |
| 领域语义关系 | 方法、实验、主张、判断及其范围 | 组织可查询、可解释的知识 |
| Artifact 输入谱系 | 产物声明使用了哪些对象版本、记录和材料 | 核查内容形成依据；不等于完整推理过程 |
| 项目初始化来源 | 项目从哪个全局状态、哪些对象版本及派生产物构造而来 | 说明继承与选择；不必全部转成普通父提交 |
| 项目提交祖先 | 初始化后哪些提交建立和改变了项目状态 | 支持独立演化、历史读取和变化检查 |
| 物理恢复关系 | 从哪些快照、delta 或对象块恢复一个状态 | 支持后端执行；不改变上述逻辑含义 |

同一 Commit 同时修改论文 A、B、C，不足以推出 B、C 的内容使用了 A。反之，一个 Artifact 实际使用 A，即使项目省略 A 的节点，它的形成依赖也不会自动消失。共同提交祖先与内容依赖必须分别判断。

项目知识视图允许包含选出的原有记录，以及 Agent 为项目新生成的概述、判断等 Artifact，因此可以是派生的知识状态，不限于原图的原样子图。必要上下文按对象和使用契约规定，不要求无条件复制全部传递依赖；跨出项目范围的引用必须有明确处理方式。

### 11.3 贯穿情形：选择 B、C，并处理与 A 相关的历史

全局库已有论文 A、B、C 的理解与使用经验。Agent 判断项目只需要 B、C，但部分属性修改与 Artifact 的形成涉及 A。项目初始化可以组合以下两种方式。

**方式一：继承选定状态，以摘要组织未展开的上下文。** 项目纳入 B、C 的有关节点、关系和选定 Artifact；Agent 对与本项目有关的上游经验调用 Summarize，形成新的摘要 Artifact。A 的完整子图和全部提交历史不必纳入项目。摘要应围绕项目需要，例如此前比较中发现的适用条件，不要求复述 A 的所有历史。

**方式二：从选定状态建立新的项目根提交。** 先依据固定的全局提交恢复目标状态，再抽出 B、C 及约定的上下文，把初始化结果保存为足以恢复的快照或完整初始化变更集。项目记录全局来源基线和选择结果，但不必将全局提交接为本地的普通父提交。项目从这个起点拥有完整的后续历史。

两种方式可以组合为“B、C 的选定状态＋摘要 Artifact＋新的项目根提交”。前者决定哪些经验进入项目，后者确定本地历史的起点。项目自身的 `AsOf` 与重放承诺从初始化状态开始；更早的形成过程通过明确保留的外部历史访问，不隐式承诺本地包含它们。

| A 与被选内容的关联 | 可采用的处理 | 应保留的解释边界 |
| --- | --- | --- |
| 仅处于同一提交或共享祖先历史 | 直接取得 B、C 的选定状态 | 不将共同提交误作内容依赖 |
| 用来解释 B、C 的演化背景 | 概述为新的 Artifact，按需保留固定外部引用 | 摘要有输入与覆盖范围，但不等价于完整历史 |
| 原有 Artifact 实际使用了 A | 保留固定外部来源，或使用新生成的派生产物；也可不选入该 Artifact | 不改变原产物的形成事实 |
| 项目要求结论在内容上不依赖 A | 由 Agent 重新检查、抽取或形成相应记录 | 切断历史或生成摘要本身不能证明独立性 |

因此，“项目图中没有 A、项目提交历史不携带 A”可以由系统保证；“留下的理解从未使用 A”是另一个需要依据的语义判断。

初始化记录应交代选定对象与版本、成员范围、选择依据、摘要及其输入范围、外部引用与未纳入内容。未选入不等于删除，项目内移除也不自动意味着从全局撤回。后续吸收和回流须尊重这一范围；新根项目需要利用来源版本和对象映射定义整合，不能仅依赖共同提交祖先。

### 11.4 Summarize 与 Commit 的双向联系

现行 [Summarize 契约](../../../designs/v2/operators.md#43-summarize)压缩和重组输入中已有的内容，结果保存为 Artifact。可在这一契约上讨论历史输入扩展：`branchsummary` 先作为用途、标题或 `focus` 表达，不预先增加新的 Artifact 类型。

**Summarize 读取历史。** `Log`、`Show`、`Diff`、`AsOf` 可以提供固定的历史输入：明确的提交集合或范围、相关对象版本、选定的属性和关系变化，以及关联的输入材料、Artifact 和提交说明。Agent 基于这些输入给出摘要，中间件校验声明的引用与结构并持久化，不在内部用 LLM 解释历史。

变化日志可以支撑“改了什么”；“为什么这样改”还需要提交说明、判断产物或其他依据，不能由 before/after 自动推出。用于摘要的具体输入集合与版本应固定；只记录“总结 A 的历史”不足以确定来源。也不能把 Artifact 的写入提交默认为输入版本，因为 Agent 的读取可能早于写入。

现有 `inputs` / `USED` 的类型尚不包含 Commit，外部项目或历史引用的解析规则也未定义。因此，这里提出的是契约扩展方向：明确历史引用类型、版本和定位方式，以及它在系统关系或材料接口中的映射；不直接将 Commit 当作普通学术对象，也不自动修改学术层 Search / Traverse 的默认范围。

**Commit 记录摘要的采纳。** 项目初始化或后续提交记录“采用了哪个摘要，以及它在项目中承担什么上下文作用”。摘要自己的输入谱系解释它从何而来；采纳提交解释它何时进入哪个项目状态。两者通过固定引用关联，不能合并为同一种父子关系。生成摘要也不会自动将其提升为经独立验证的 Observation。

**原有 Artifact 的输入关系保持真实。** 若已有产物使用 A、B、C，之后才生成摘要，则不能把其 `USED` 指向 A 的关系改成指向新摘要，并继续声称它是同一个不可变产物。可保留原身份及外部固定来源、另建新派生产物，或不将原产物纳入项目；具体引用表示待定。

**语义摘要与精确历史恢复分别承担保证。** 摘要为项目保留可用经验，不承担恢复每个旧值、执行 `Revert` 或保持所有历史查询答案的责任。需要精确恢复时，依据仍是被保留的状态和完整变更数据。若项目只保留摘要而不保留上游明细的访问能力，应显式记录这一边界；本地状态可恢复不等于上游全过程可复查。

### 11.5 方法应定义的操作契约与正确性目标

方法按“项目建立、项目内演化、跨范围整合”组织，不以版本 API 清单代替问题定义。

| 操作阶段 | 必须确定的内容 | 候选正确性目标 |
| --- | --- | --- |
| 项目建立 | 固定来源状态、选择结果、上下文处理、摘要及初始化状态 | 原样继承的内容与来源一致，新生成内容明确标为派生；项目起点可恢复 |
| 项目内使用与提交 | 读取版本、目标作用域、实际生效变化、结果状态 | 历史版本含义稳定；变更与记录一致发布；结构和引用约束保持 |
| 独立探索 | 分支的起始状态、成员范围和后续写入归属 | 一条路线的写入不隐式改变另一条路线的状态 |
| 吸收与回流 | 接纳范围、来源映射、比较基线、冲突决议 | 未选入不被当作删除；整合保持约束并记录实际采纳内容 |
| 历史核查 | 本地保留范围、固定外部引用及材料内容 | 可恢复声明范围内的状态；能够区分未纳入、仅有摘要和可访问明细 |

令 $S_{p,c}$ 表示项目 $p$ 在提交 $c$ 下的逻辑状态。对该状态支持的查询 $q$，历史读取的候选语义为：

$$
\operatorname{ReadAt}(p,c,q)=q(S_{p,c}).
$$

不同的物理快照、delta 和物化方案应保持这个结果。逻辑状态需要覆盖所声明的知识与 Artifact、项目成员／绑定以及固定材料引用；不要求它们全部物理存放在图数据库内。若摘要替代了一部分上游历史，项目仍需精确恢复其自身状态，但不宣称能够由摘要恢复已省略的全局状态。

对写入与整合，候选目标是：从合法状态出发，被接受的变更产生满足声明约束的新状态。这里的约束包括类型、身份、引用、作用域和内容可访问性；它们不证明论文判断真实。查重、证据解释、摘要是否忠实和是否足够支持项目任务，仍由外部 Agent 与独立质量评价承担。

版本可标识、历史可访问、完整生效记录和分支隔离应进入相应功能的契约。可逆 delta、全量复制、自动三方合并、`Blame` 或某种压实算法则按实际承诺选择；不会因为采用简单存储而失去版本管理的语义，也不能因为有 before/after 就自动获得全部整合正确性。

### 11.6 评价边界与待收敛事项

评价首先检验中间件是否支持上述项目生命周期：继承结果、作用域、输入版本、完整提交和历史读取是否正确，交互与维护成本如何变化。再检查项目使用中的摘要忠实度、上下文充分性与下游任务质量。快照恢复正确、来源链接存在，不等于摘要保留了所有重要条件。

在论文 A、B、C 的例子中，可以比较完整保留、固定外部引用、摘要承接和新根初始化等候选方式；具体任务、预算、材料访问环境和质量标准须另行讨论确定，本节不启动新实验。成本包括项目构造、摘要生成、历史保存、材料保留及后续补查，不能只报告局部图变小的收益。

优先收敛：哪些内容属于项目状态；哪些跨范围引用必须能解析；初始化来源与普通提交祖先怎样区分；Summarize 的历史输入如何定位；只保留摘要时声明哪些信息边界；新根项目怎样吸收和回流知识。这些问题涉及语义模型、操作组合和版本正确性。具体新颖性及效果需要进一步论证，不能仅由两篇参照论文未覆盖这一组合而推出。

### 11.7 必需引用的论文及参照作用

以下两篇已列入 [references/refs.bib](../../../../references/refs.bib)，作为本设计及后续稿件中版本化数据管理部分的引用。精读材料保留在用户指定的 `references/papers/graph_version_control/` 下。

| Citekey 与论文 | 应引用的论点与位置 | 对本设计的边界 |
| --- | --- | --- |
| `2026-Git4Data` — Gou 等，*Git4Data: Database-Native Version Control for AI Agents*，arXiv:2609.02106v1，2026 | [§2–3](https://arxiv.org/html/2609.02106v1#S2)：固定状态、独立分支、内容 diff、带策略的三方合并及原子发布；[§6](https://arxiv.org/html/2609.02106v1#S6)：行级整合与更强约束的边界 | 用于定义版本操作与责任；不要求采用 MatrixOne、零复制或自动三方合并，也不提供项目知识选择和摘要化继承契约 |
| `2013-GraphSnapshot` — Khurana、Deshpande，*Efficient Snapshot Retrieval over Historical Graph Data*，ICDE 2013 | 本地精读依据 2012 年技术报告 [arXiv:1207.5777v1 §3–6](https://arxiv.org/html/1207.5777v1#S3)：完整事件、历史状态恢复、DeltaGraph 索引与 GraphPool 多快照共享 | 用于区分逻辑历史与物理恢复；内部合成索引节点不是实际提交，不要求实现该索引，也不支持用语义摘要替代精确状态数据 |

Git4Data 按预印本引用；GraphSnapshot 的会议归属见[作者出版页](https://www.cs.umd.edu/~amol/DBGroup/graphs.html)，正式版本见 [DOI](https://doi.org/10.1109/ICDE.2013.6544892)。会议条目与本次精读使用的技术报告版本保持区分。

两篇论文分别为版本操作与历史恢复提供参照。本节的项目选择、历史保留边界、Summarize 与 Commit 的互动，是结合本项目需求提出的设计建议，不归为它们已经提出或验证的机制。

本地阅读材料：[Git4Data 精读](../../../../references/papers/graph_version_control/2026-Git4Data/analysis.md)、[GraphSnapshot 精读](../../../../references/papers/graph_version_control/2013-GraphSnapshot/analysis.md)、[综合设计启示](../../../../references/papers/graph_version_control/design_implications.md)。
