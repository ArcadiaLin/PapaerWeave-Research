# 工具 V3

> **状态：** 已实现（2026-10-16 夜，`system/`，提交 `1502e44` 起），在 [V3 RPC 实验室](../../experiments/2026-10-17-v3-rpc-lab.md) 中边测边改；待用户审阅。本文列出 agent 经 MCP 使用的工具（V2 称"算子"）。数据模型见 [数据模型 V3](./data_model.md)。给模型看的全部文字在 `system/src/paperweave/mcp/server.yml`，本文只记结构与理由。
>
> 标 **〔待确认〕** 的是实现中自行决定、尚未与用户确认的改动。

## 总览：两组工具

| 组 | 工具 | 写库 |
| --- | --- | --- |
| 知识访问 | `search`、`get`、`traverse`、`read_evidence` | 否 |
| 版本管理 | `checkout`、`commit`、`log`、`show`、`diff`、`as_of` | `commit`（graph-doc 与产物文档各产生一个提交） |

工具名全部小写；在 pi 中显示为 `mcp__PaperWeave__<名>`。带 `[]` 的是列表参数。工具不调用 LLM；引用只接受已有的 id。写入者的身份由服务端登录给出（`PAPERWEAVE_USER`），不是参数。

读取工具（`search`、`get`、`traverse`）返回**带注释的 YAML**：注释（`#` 之后）给出 id 的名称与锚点所在的章节，`_` 开头的字段只读。去掉注释仍是合法的 graph-doc 片段：`get` 的节点原样贴进 `set` 是 noop。

## 知识访问

- `search(query, kind[]?, paper[]?, topn?: 10)`：一个检索覆盖全部节点、产物与带说明的关系。
  - 精确命中在前，标 `_match`：`id`、外部标识（`arxiv:2205.13504` 或不带命名空间的 arXiv 号）、名称或别名（不分大小写）。
  - 其余按四路 RRF（节点全文、节点向量、关系全文、关系向量；`RRF_K=20`，每路取 30）排序。关系命中挂在起点下，只列命中的那几条关系。
  - `kind` 可以是 kind、类别（Entity / Concept / Content）、产物类型或关系类型。不指定产物类型时，结果中至多混入 3 份产物，其余计数在开头的注释中。
  - 每条结果是紧凑投影：kind、名称或描述摘录、论文、锚点、主要出边、入边计数。
  - 说明末尾附会话开始时的库总览（下节）。
  - 〔待确认〕不再分页，不再有 `where`。按产物身份查找（V2 的 `where.key`）删除：写重复身份的产物时 `commit` 报 `identity` 并给出已有 id。
- `get(ids[])`：全部字段与出边，形状与 graph-doc 中 `set`（字段）和 `create`（边）下写的相同。
  - 只读字段：`_formed_by`、`_formed_at`、`_edges_in`（各类入边的条数）、`_supported_by` / `_opposed_by` / `_used_by`、有据层记录的 `_revised`（最近一次修订的提交、作者、理由、锚点）、产物的 `_stale`。
  - 一次至多 20 个 id。
- `traverse(start[], path?, limit?: 30)`：沿关系走，表达结构条件与穷举。
  - `path` 是 0–3 跳，每跳 `{rel, dir?: out | in | both, kind?}`；`rel` 可以是列表，含系统关系 `FROM`（Content → 论文）与 `USED`（产物 → 用到的节点）。
  - 结果是最后一跳到达的节点，按 id 排序，各带 `_via`：上一步从哪些节点、经哪条边到达，带边上的属性。总数在开头的注释中。
  - 〔待确认〕不再有分页、`where`、`edge`、`depth`。
- `read_evidence(source_refs[], at?)`：读论文或产物文档中的行。
  - 引用写作 `<论文或产物 id>::<起>:<止>`；中间带章节（V2 写法）也接受，只作提示。返回中补上所在章节。
  - 单条引用至多 400 行。

## 版本管理

- `checkout(ids[]?, new[]?)`：把要写的东西放进工作目录，不改动库。
  - `ids` 中的产物：取出当前版本的文档（头部带 `id`、`base`）与编辑提示（V2 的 `fetch_artifact`）。
  - `ids` 中的证据节点：写成一份 graph-doc，节点在 `set` 下（即 `get` 的投影），改值即修改。
  - `new` 中的 kind：一份空白 graph-doc 模板，每个 kind 一个 `$` 节点，字段与能连的关系都带注释；模板由数据模型登记表生成。产物类型（Leaderboard、Generate）给出该类型的空白文档。
  - 〔待确认〕不再支持取旧版本（V2 的 `at`）：旧状态用 `as_of`，旧文档行用 `read_evidence at`。
- `commit(files[], message, reason?, dry_run?)`：提交工作目录中的文件。
  - 以 `graph-doc:` 开头的 YAML 是 graph-doc（一次至多一份：`$` 名只在一份文件内有效），其余按头部的 `type` 是产物文档。
  - 先对全部文件做检查，任何一份有阻塞项时都不写；位置换算成 `<文件>:<行号> (<文档中的路径>)`。通过后 graph-doc 一个提交、产物文档一个提交。
  - 错误报告要短（RPC 第 2 轮：20 KB 的返回被 pi 截断，写者只能到临时文件里翻找）：规则、消息与改法都相同的错误只报一次，`at` 列出各处；查重候选一行一个；方向写反时给出另一端的写法；只检查本次写入或改动的边。
  - dry run 与提交结果的计数同一口径：只算证据节点与关系，不算名称键与材料。
  - `message` 是提交说明，也是产物的 `update_abstract`；改动他人写的产物行时要 `reason`。
  - 〔待确认〕默认直接写入（V2 的 CheckIn 默认只检查），`dry_run: true` 只检查。
  - 提交后补算检索用的派生字段（`search_text`、`embedding`），失败只提示，下次提交重算。
  - 涉及 Experiment 时返回 `related_artifacts`：其评测数据集上的 Leaderboard。
- `log`、`show`、`diff`、`as_of`：与 V2 相同，视图换成 V3 的 `get` 形状；由别的对象决定的只读字段（入边计数等）不计入变化。

## 会话开始时的总览

让写者不必主动去想，就知道库里已有哪些前人结果，作用相当于 files + Git 组的 `ls artifacts/`。

- 位置：`search` 的工具说明末尾。MCP 服务每个连接新启动一次，启动时按当前库生成；pi 以 direct 方式列出工具时，工具说明每轮都在模型面前，服务的 `instructions` 模型看不到。
- 内容：各 kind 的节点数；至多 20 篇论文（id 与名称）；各产物类型的份数与最近 3 份的标题与 id。空库时只说库是空的。
- 时效：会话开始时的快照；写者轮流运行，会话中只多出自己写的。

## 实现结构

`model ← store ← draft、commit ← query ← artifact ← operators、interfaces ← tools ← mcp、cli`，由 `system/tests/test_layers.py` 检查（AST）。

- `model/schema.py`：kind 与关系的登记表；`model/templates.py`：由登记表生成空白模板与工具说明中的词表。
- `query/search.py`：检索；`query/view.py`、`query/render.py`：投影与带注释的 YAML；`query/read.py`：读出投影；`query/dedup.py`：写入时的查重（注入 `commit`）；`query/overview.py`：总览。
- `store/derived.py`：派生字段（检索文本与向量），每次提交后补算，不受版本管理。
- `operators/db/`：一工具一文件。

## 待定

- `search` 的向量一路是否设阈值：写入时的查重已设（0.84，见数据模型的实现决定），检索还没有，小库上 `search` 几乎总能返回 `topn` 条。
- `get` 的大小上限：ETTh1 这类节点有上百条入边，现在只给计数；出边多的节点（如综述论文的 `CITES`）尚未截断。
- 检索用派生字段每次提交全量重算文本，库大时要改为增量。
