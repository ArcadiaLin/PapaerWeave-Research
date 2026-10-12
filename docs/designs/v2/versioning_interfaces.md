# 版本记录的读取接口：Log、Show、Diff、AsOf

> **记录日期：** 2026-10-07。**状态：** 四个接口已在 E09 实现（`experiments/e09/src/e09/interfaces/`，作为 MCP 工具提供）；ReadEvidence 的 `at` 参数（第 6.2 节）与 Search、Traverse 的头提交核对（第 2.1 节）已实现（2026-10-08）。运行测试的方法见 `docs/experiments/e09/testing.md`。2026-10-12：产物改为有版本的文档（[算子契约](./operators.md) §5），产物的每次检入也是一个提交，四个接口照常适用，见第 1.1 节。实现中定下的写法已补入第 2.1、2.2、2.3、3、4 节与第 9 节。同日按评审修订：`AsOf` 以完整状态的逆向重放为准（第 6 节）；历史读取的材料访问与只读字段（第 6.2 节）；分支名与分页固定到具体提交（第 2.1 节）；容量与不截断的冲突规则（第 2.2 节）；Fork 与 Merge 的定位（第 1 节）。
>
> 依据：[版本化知识管理备忘](../../discussions/2026-10-05-versioned-knowledge-management.md) 的第 3、4 节，[Commit 工具设计](../../experiments/e09/operators/commit.md) 的第 8 节，以及 `packages/graph-vc` 的现状。

## 1. 定位：接口，而不是算子

### 1.1 产物的版本（2026-10-12）

产物的每次检入是一个提交，新版本的文档是一份新的 Material，上一版本记 `superseded_by`。因此：

- `Log(node=art_0003)` 列出这份产物的全部版本，`by` 是各版本的编辑者，`message` 是 `update_abstract`；
- `Show` 与 `Diff` 中，产物的版本变化显示为 `_document`、`_title`、`_abs` 与 `_USED` 的变化；文档内的逐行差异不在这里给出，由 `FetchArtifact` 的编辑提示给出（[算子契约](./operators.md) §5.6）；
- `AsOf` 给出产物在某个提交时的读视图，`_document` 指向当时的版本，可用 `ReadEvidence(at=…)` 或 `FetchArtifact(at=…)` 读取。


本系统对外提供的操作分为三类，来源各不相同：

| 类别 | 例子 | 从哪里来 | 位置 |
| --- | --- | --- | --- |
| 算子 | Search、Resolve、Traverse、ReadEvidence、Commit，以及七个 Agent 算子 | 从研究 workload 推导：知识的定位、导航、读取、写入与使用 | [算子契约](./operators.md)、`docs/experiments/e09/operators/` |
| 接口 | Log、Show、Diff、AsOf（本文），以及之后的 Blame、Revert | 从版本机制推导：读取提交记录与历史状态 | 本文 |
| 任务 | Fork（建立项目视图）、Merge（总图与项目之间的整合） | 多步流程，由接口、算子和 Agent 的判断组合而成 | 另文 |

接口不表达研究意图，只让版本记录可以被读取。它们的正确性由机制决定，例如逆向重放的结果必须与当时的状态一致，与 Agent 的判断无关。学术层的 Search、Traverse 默认不返回提交对象；要读历史，就用这里的接口。

"任务"指的是执行形式，不是重要性：Fork 与 Merge 要组合多步并在其中交给 Agent 判断，所以不是单个调用。但它们承载项目的选择、独立演化与回流的机制语义，是论文贡献（草稿 C3–C4）的核心部分，其契约（选择与闭合、分支隔离、整合时的核对与冲突、"选择不是删除"等不变式）需要另行定义并评测。本文的四个接口只提供它们所需的历史读取能力，不能替代这些契约。

## 2. 共同约定

### 2.1 引用

| 写法 | 含义 |
| --- | --- |
| `commit_000027` | 一个提交 |
| `main` | 分支名，代表该分支当前的头提交。现在只有 `main`，项目分支随 Fork 引入 |

**固定到具体提交。** 分支头会移动，分页期间也可能有新的提交。因此每个接口在第一次请求时把分支名解析成具体的提交 id，响应的 `meta.at` 给出它（`Diff` 为 `meta.from` 与 `meta.to`），`continuation` 也带着它；续取时只读这个固定的状态或范围，不再解析分支名。之后的新提交要重新发起请求才能看到。

续取位置写成字符串 `<下一项的序号>@<提交>`，如 `2@commit_000032`；`Diff` 为 `<序号>@<from>..<to>`；`Show` 的 `input` 中序号是字节位置。续取时若参数给的是提交 id，须与续取位置中的相同，否则拒绝。

**Search 与 Traverse 的 `snapshot` 需要补一条规则。** 现在它们先查询、再单独读一次头提交，两步之间若有写入，返回的 `snapshot` 不一定就是结果所在的状态。改为查询前后各读一次头提交：两次相同才给出 `snapshot`；不同时给 `snapshot: null`，并在 `diagnostics.snapshot` 中说明读取期间状态有变化。这样 Agent 记下的 `snapshot` 才能可靠地交给 `AsOf`。

### 2.2 输出与容量

- 输出是 YAML，与其他工具相同。
- 所有接口只读。
- **16 KB 是硬上限**（与 Search、Traverse 相同），`meta.size` 给出上限与实际大小。上限优先于"不截断"，规则如下：
  1. **先给摘要，再分页给明细。** 摘要只给计数和有限的预览：`touched`、`removed`、`ids` 等列表最多给前 20 项，并给出总数；完整列表在明细中分页取得。
  2. **明细按节点分页。** 放不下的节点整体移到下一页，`meta.continuation` 给出续取位置。
  3. **单个节点自己就放不下时**，先把过长的字符串截到同一个长度（末尾写 `…`），取放得下的最大长度；字符串截到最短（64 字节）仍放不下时，再把过长的列表截到同一个项数。被截短的位置记在该项的 `_cut` 中，写成 `{路径: {bytes: 原长}}` 或 `{路径: {items: 原项数}}`，路径用 `.` 连接键与列表下标，如 `fields.text.1`。值可能嵌在变更视图的 `[改前, 改后]` 里，所以不用 Search 的 `<字段>_bytes` 写法。
     被截短的值用分块读取取回：`Show`（`part: changes`）、`Diff`、`AsOf` 都接受 `field`（`_cut` 中的路径）与 `offset`，此时 `node` 或 `ids` 只给一个 id。结果是 `{id, field, offset, bytes | items, value, meta}`：字符串从第 `offset` 字节起、列表从第 `offset` 项起，给出放得下的最长一段，`meta.next_offset` 是下一段的起点，读完为 `null`。
- Traverse 现在在一条路径也放不下时仍返回这一条，会超过上限；之后按规则 3 统一。

### 2.3 变更视图

`Show` 的明细与 `Diff` 共用同一种逐节点的变更视图：

```yaml
- id: exp_0010
  kind: Experiment
  op: update          # create | update | delete | edges（节点本身没变，只有关系变了）
  fields:             # 只列变化的字段：[改前, 改后]；新建时改前为 null，删除时改后为 null
    note: ["Table 3 of the PatchTST paper.", "Table 3; the DLinear column is copied from the DLinear paper (L=336)."]
  edges:              # 起点为本节点的出边
    added: [{rel: USES, to: dataset_0003, role: eval}]
    removed: []
    changed: [{rel: EVALUATES, to: method_0027, fields: {role: [target, baseline]}}]
```

- 字段的拼写与读视图（graph-doc）相同：系统字段与派生字段（向量、自然键）不出现。
- 关系挂在起点一侧的节点下，与读视图一致。只有入边变化的节点不单列，它的变化在起点节点下。
- 系统关系按读视图的写法显示为字段：`NAMES` 的变化显示为对象的 `aliases` 变化，`MATERIAL_OF` 的变化显示为 `material`（Artifact 为 `_document`）变化。它们是指向对象的入边，所以求差时要把对象的这两类入边一并算入。
- 新建与删除的节点给出全部字段；修改的节点只给变化的字段。`kind` 只在外层给出，只有修改时 kind 本身变了才出现在 `fields` 中。
- Artifact 按它的读视图比较：`_op`、`_title`、`_abs`、`_document` 等只读字段与 `_USED`（按关系比较）。2026-10-12 之前的 `_params` 随旧版产物算子去掉。

## 3. Log：发生过哪些写入

```text
Log(branch="main", node?, by?, source?, since?, until?, budget=50, continuation?)
```

| 参数 | 说明 |
| --- | --- |
| `node` | 只列触及这些节点的提交：新建、修改、删除了它，或增删改了它的关系 |
| `by` | 写入者 |
| `source` | 写入来源，按前缀匹配，如 `operator:`（产物算子写的 Artifact 版本）、`operator:Leaderboard` |
| `since` / `until` | 时间范围，或提交 id（不含 `since` 本身） |

输出从新到旧排列：

```yaml
commits:
- id: commit_000032
  at: 2026-10-06T14:46:06.504516+00:00
  by: qwen3.8-27b
  source: "session: DLinear-vs-PatchTST ETTh1 comparability analysis (check art_0023, matrix art_0025)"
  message: Record comparability verdict and fair head-to-head outcome for DLinear vs PatchTST on ETTh1 as Observations
  counts: {nodes: {create: 2}, edges: {create: 6}}
  touched: [art_0023, art_0025, exp_0002, exp_0010, obs_0001, obs_0002]
meta: {returned: 1, matched: 1, continuation: null, size: {...}}
```

`touched` 与 `removed` 只列图模型对象与 Artifact，NameKey、Material 这类系统节点不列，它们的变化显示在所属对象的 `aliases` 与 `material` 上。太长时只给前 20 个，并给出总数 `touched_total`。`Log` 不给内容，内容用 `Show`。

`since` 与 `until` 给提交 id 时按序号比较（`since` 不含本身，`until` 含本身）；给 ISO 时间时按写入时间比较，`until` 只给日期时含当天。

## 4. Show：一次写入做了什么、依据什么

```text
Show(commit, part=summary | input | changes, node?, field?, offset?, continuation?)
```

一个提交的完整记录可能很大，比如一篇论文的入库有几百个节点，所以分三部分取：

| `part` | 内容 |
| --- | --- |
| `summary`（默认） | 头信息：`id`、`seq`、`parent`、`branch`、`at`、`by`、`source`、`message`、`base`；计数；`touched` 与 `removed`；`confirm`（同一性判断）；临时引用到 id 的映射 `ids`；`input` 的大小 |
| `input` | 交上来的原文：Commit 工具的 graph-doc，或 Agent 算子的调用参数。按行分页，一行就放不下时在行内断开；`meta` 给出行号范围、字节范围与总数 |
| `changes` | 变更视图（2.3 节），按节点分页 |

`confirm` 取自 Commit 交上来的 graph-doc；`ids` 写成 `临时引用 -> id` 的列表，同样只给前 20 项与总数。`changes` 就是父提交与本提交之间的净差异，与 `Diff(parent, commit)` 相同。

例：`Show(commit_000027)` 能看到 Agent 交的 doc 里把 `claim_0001` 的 `FROM` 指向 `paper_0004`，`note` 里写着 "Agent-derived"。这正是第一轮试跑那次语义误用的完整记录。

## 5. Diff：两个状态之间变了什么

```text
Diff(from, to="main", node?, field?, offset?, continuation?)
```

- **净差异：** 只比较两端的状态，中间改了又改回的不出现。逐次的变化用 `Log` 加 `Show` 查看。
- **范围：** `from` 必须是 `to` 的祖先，两者在同一条线上。跨分支的比较随 Fork 再定。
- **输出：** 先给摘要（按 kind 和操作计数，以及节点 id 列表），再按节点分页给变更视图。`node` 把比较限定在给定的节点上。

实现时不比较整图：取 `(from, to]` 之间各提交 `touched ∪ removed` 的并集，只在这些节点上比较两端的状态。两端的状态由 `AsOf` 的完整状态重放求得（第 6.1 节），所以 `Diff` 的可信度取决于它。Merge 求差也用它。

## 6. AsOf：某个时刻是什么样

```text
AsOf(at, ids, field?, offset?, continuation?)
```

返回这些对象在提交 `at` 时的读视图，形状与 Traverse（`path` 为空）相同，即 graph-doc：字段、全部出边、别名、Artifact 的只读字段。

- **在那个时刻还不存在、或已被删除的对象**记入 `meta.missing`，写成 `{ref, missing_in: at}`。
- **只按 id 读取，不沿关系走。** 要看当时的邻居，就把出边里的 id 再交给一次 `AsOf`。在过去的状态上做 Search 需要当时的索引，不提供。
- **用途：**
  - 回看一份答案所依据的状态；
  - 判断一个 Artifact 的输入在它形成之后改了什么；
  - 作为 `Diff` 的组成部分。

### 6.1 求出旧状态：先以完整状态的逆向重放为准

**参照实现：** 取当前的完整图状态（`snapshot()`，只含受版本管理的属性），把 `at` 之后的全部提交的逆向变更集从新到旧依次应用（`GraphState.apply()`），得到完整的 $S_{at}$，再从 $S_{at}$ 渲染视图。每一步都满足 `apply()` 的前提核对，因为每个逆向变更集都作用在它对应的完整状态上。

只从 `local_state(ids)` 出发、把变更集限定在这些节点及其出边上的局部重放不能保证完整，原因有两点：

- 当前状态里可能已经没有被删除的节点和它们的旧关系，而重建一条边时 `apply()` 要求两端存在；
- 别名（`NameKey -NAMES-> 对象`）和材料（`Material -MATERIAL_OF-> 对象`）是指向对象的入边，只保留出边会丢掉旧别名和材料。

当前库只有几百个节点、几十个提交，完整重放的代价可以接受。它同时用来检验不变式 1、2（重放一致、可逆）。局部重放作为之后的优化，要先定出所需的闭包：对象的全部入边与出边、边的另一端、`at` 之后被删除过的节点及其关系；再用参照实现逐项核对。

### 6.2 旧视图中的只读字段与材料访问

旧视图不能混入当前状态，所以只读字段都从 $S_{at}$ 求得，或者不提供：

| 字段 | 旧视图中的处理 |
| --- | --- |
| `aliases` | 由 $S_{at}$ 中的 `NAMES` 求得 |
| `material`、`_material`、`_document` | 由 $S_{at}$ 中的 `MATERIAL_OF` 与 Material 节点求得 |
| `_stale` | 不提供。它是相对当前状态的判断（输入后来是否变了），与"当时是什么样"不是一回事；需要时对输入用 `Diff(at, main)` |

**材料访问。** 现在 ReadEvidence 在当前图中查找 Material 节点（`query/materials.py`）。如果材料节点或它的归属关系后来被删除了，即使文件还在，也会返回 missing。因此要规定：

1. **旧视图给出的材料标识要能用于访问。** ReadEvidence 增加 `at` 参数：给出时按 $S_{at}$ 中登记的材料（路径与内容哈希）解析引用，`coverage.at` 给出固定下来的提交。
2. **文件保留。** 被任何提交引用过的材料文件不删除、不覆盖，按登记的哈希核对后读取（备忘第 7.3 节的保留根）。产物的新版本与论文的新版本都登记为新的材料文件，旧文件不覆盖，实际上满足；但这要写成约束，而不是依赖现状。

## 7. 暂缓的接口

| 接口 | 作用 | 为什么暂缓 |
| --- | --- | --- |
| `Blame(node)` | 当前每个字段、每个关系键最后由哪个提交写入 | 可以由 `Log(node)` 加逐个 `Show` 推出；等有 workload 需要时再做 |
| `Revert(commit)` | 把一个提交的逆向变更集作为新提交写入，不改写历史 | 它是写操作；graph-vc 已有 `revert`，但对外开放前要定两件事：是否经过 Commit 的检查；后来的提交依赖被撤销内容时如何报告 |

## 8. 与任务的关系

- **Fork：** 在固定的提交上选取与物化，记录 `origin`。需要 `AsOf` 来确定"选的是哪个状态"，以及 6.2 节的材料访问，项目才能读到来源状态下的原文。
- **Merge：** 用 `Diff` 求来源的净差异，由中间件持有合并计划，Agent 只答复待决项；执行时复用 Commit 的检查与查重。合并提交在 `merged_from` 中记录来源分支与提交范围。

这两个任务另文设计。本文的四个接口是它们的前提，但不包含它们的契约（第 1 节）。

## 9. 待定问题

已定（2026-10-07）：

- **四个接口都作为 MCP 工具交给 Agent**，因为"按版本读取状态"是要评测的 workload。工具说明要写清它们读的是历史，不是当前知识。
- **代码位置：** 与 `operators/` 平行，新建 `src/e09/interfaces/`，一个接口一个文件；MCP 服务一并注册。求旧状态的参照实现（第 6.1 节）放在 graph-vc（`VersionedGraph.state_at`）。

实现时定下（2026-10-07）：

- **`input` 按行分页**，一行放不下时在行内断开（第 4 节）。
- **Artifact 在变更视图中按读视图显示**，由容量规则截短（第 2.3 节）。

仍待定：

1. **`Diff` 是否允许 `from` 不是 `to` 的祖先。** 线性历史上不会出现；有了分支之后，可以以共同祖先为基线，求两侧的变化。
