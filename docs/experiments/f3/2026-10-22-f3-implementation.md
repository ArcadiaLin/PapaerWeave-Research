# f3：工程落地记录

状态：M1 的挡路项 B1–B7 已定（2026-10-22），尚未开始实现。
设计：`docs/experiments/f3/2026-10-22-f3-design.md`（c4f97c6）。设计文档说明“要什么”，本文记录“做了什么、怎样验证的”。实现中发现设计需要改时，回到设计文档修改，本文只记一条指向那里的说明。

## 1 目标

**M1：f3-A3 写者时间线可以正式开跑。** 写者侧条件按设计文档实现，在测试环境冒烟通过；四组共用的部分冻结，冻结记录写入第 5 节。

读者在检查点快照上离线作答（写读分离，V3 §7 第 9 条），读者侧可以在 A3 写者运行期间实现，不挡 M1。

### 1.1 完成标准

全部满足才算完成：

1. **system**（设计 §4、§4.1、§7）：anchor 改为 `<source_id>::<行范围>`；Paper 的 `source` 取代 `material`；记录有效性校验 A3、A2 都启用，修订约束只在 A3 启用（A2 照旧消融）；过时检测按来源 ID 的版本号；写者的 `read_evidence` 经只读来源目录解析；单元测试覆盖并通过。
2. **来源服务 `read_source`**（设计 §4）：按计划表开放；下载到本次 `/work/sources/`；拒绝未开放来源；逐次记录；四组接法与说明相同。
3. **运行器**（设计 §2、§7）：每会话全新 `/work` 与 home；不挂载论文与代码；`sessions.jsonl` 记材料清单；检查点备份照旧。
4. **种子转换**（设计 §4.2）：材料到来源 ID 的对应表；转换后的 A3、A2 起点库中不残留 `paper_xxxx::`，并核对。
5. **冻结材料**（设计 §3、§7）：第 3.1 节的材料表与 40 个任务的文字改写经用户确认，写入冻结记录。
6. **冒烟**：临时 Neo4j、非正式运行占用的推理服务上，build、update、compare、note-i6、leaderboard 各跑一次会话，检查开放与拒绝、写入库中的 anchor 格式、update 后出现过时标记、下一会话不继承上一会话的私人文件。

### 1.2 不在 M1 内

- **M2 读者侧：** 评测侧的 `read_evidence`、按历史收集的放行名单、证据可达率、读者环境（设计 §6）。
- **M3 A0：** 每会话全新工作目录、只同步已提交内容、约定 README 的改写（设计 §2.2、§7）。
- **M4 A4 重做：** 包括检查点的备份与恢复。
- V3 `data_model.md`、`tools.md`、`evaluation.md` 的同步；f2-A3 读者（暂缓）。

## 2 挡路项

M1 开始实现前要先定的细节（取自设计 §10），逐项与用户敲定后记下结论与日期。

| # | 挡路项 | 设计中的位置 | 状态 | 结论 |
| --- | --- | --- | --- | --- |
| B1 | 每类会话直接提供的材料表 | §3.1 | 已定 2026-10-22 | 见 2.1 |
| B2 | 任务文字的具体改法（50 个任务，含 compare、verify 点出来源 ID） | §7 | 已定 2026-10-22 | 见 2.2 |
| B3 | `read_source` 的路径规则与返回格式 | §4 | 已定 2026-10-22 | 见 2.3 |
| B4 | 基础设施中断后同一会话的重试规则；会话归档 | §2.2 | 已定 2026-10-22 | 见 2.4 |
| B5 | 行范围定位之外的分隔与转义细节（含代码路径） | §4.1 | 已定 2026-10-22 | 见 2.5 |
| B6 | 关联来源（官方代码）的校验规则 | §4.1 | 已定 2026-10-22 | 见 2.6 |
| B7 | 材料到来源 ID 对应表的构建与核对 | §4.2 | 已定 2026-10-22 | 见 2.7 |

### 2.1 B1 材料表（2026-10-22 定）

| 会话 | 任务中点出的来源 ID | 新开放 |
| --- | --- | --- |
| build（28） | 该论文 | 该论文 |
| build-overlap（7） | 该论文（此前已开放） | 无 |
| update（3） | 新旧两个版本 | 新版本 |
| compare（4） | `instance` 中的 `p1`、`p2` | 无 |
| verify-own（3） | 该论文；不给代码 | 无 |
| verify-later（3） | 只给被核查的论文 | 无 |
| note-i6（2） | 该论文与代码仓库：I6-1 给 `Autoformer@09994619`；I6-2 给 `ARMA-Attention@a9e6d31b` 与 `CATS@71d18a9f` 两个 | 代码仓库 |
| note-i1（2）、leaderboard（14）、summarize（4） | 无 | 无 |

- 核对：compare、verify、update 用到的论文与旧版本，都在此前的 build 或种子中开放过（种子为 `2012.07436v3`、`2106.09305v3`），点出它们的 ID 不会提前开放任何材料。共开放 33 个论文来源（种子 2、build 28、新版本 3）与 3 个代码仓库。
- I6-2 给两个仓库：`code/README.md` 中 `2403.01673v1` 对应这两个，只给 `CATS@…` 等于交出答案；两个都给，保留“判断哪个是官方实现”这一步，也与 f2 写者看到的 README 一致。
- 代码的来源 ID 用 `code/README.md` 的目录名。
- 开放时刻照设计 §3.2：第一次直接提供它的会话开始时开放，此后一直可读；种子论文在起点开放。
- 表由 `plan.yml` 的 `paper`、`from`、`instance.p1/p2` 字段机械生成，代码对应手写（note-i6 的 key 到仓库 ID）；生成结果存为题库 `tasks/materials.yml`，与 `plan.yml` 一起冻结，运行器与来源服务都读这一份。
- note-i6 保留“地址从哪来”一问（答案在论文中给出的地址），任务文字的改法见 B2。

### 2.2 B2 任务文字（2026-10-22 定）

改 50 个任务：build 28、build-overlap 7、update 3、compare 4、verify-own 3、verify-later 3、note-i6 2；leaderboard、summarize、note-i1 不变。`identities.yml`、`hints.yml` 中没有论文或代码路径，不改。只替换路径、加一句怎样取，其余措辞不动：

| 类型 | 改为（示例） |
| --- | --- |
| build、build-overlap | `Please add the paper 2106.13008v5 (Autoformer; fetch it with read_source) to the shared knowledge store, …` |
| update | `The FiLM paper has a newer version, 2205.08897v4, after 2205.08897v3; both can be fetched with read_source. Update the store …`（“switch the paper to it”与“Records the new version leaves unchanged need no new anchors”保留） |
| compare | `… 0.278 in the TiDE paper (2304.08424v5) and 0.281 in the TimeMachine paper (2403.09898v2); both can be fetched with read_source. …` |
| verify-own | `The PatchTST paper (2211.14730v2; fetch it with read_source) claims …` |
| verify-later | `Is the claim of the PatchTST paper (2211.14730v2; fetch it with read_source) …`（“later papers in the store”不变） |
| note-i6 | I6-1：`Find the official implementation of Autoformer (2106.13008v5): … The code released with the paper can be fetched with read_source as Autoformer@09994619, at the commit matching the paper version; read it there instead of fetching it from the network.` I6-2 写 `ARMA-Attention@a9e6d31b and CATS@71d18a9f, each at the commit matching the paper version` |

- 只写来源 ID，不加“arXiv”前缀，与 `read_source` 的参数逐字一致。
- **生成：** `scripts/tasks.py` 加 f3 选项，生成新文件 `tasks/plan-f3.yml` 与 `tasks/materials.yml`；原 `plan.yml` 是 f2 的冻结材料，不动。
- **写者的来源说明：** 共用的环境说明（`ENV_NOTE`）不改，它也是 P、C、D 读者的冻结文字。所有写者会话（70 个，四组相同）在环境说明之后再接一句写者专用的说明，明确沙箱中没有别的途径取得外部材料：`You are working in a sandbox: papers and code are not available locally or from the network; fetch them by id with read_source.` 读者没有 `read_source`，不接这句。冒烟时检查写者是否正常调用 `read_source`。

### 2.3 B3 `read_source` 的路径与返回（2026-10-22 定）

- **调用：** `read_source(source_id)`，一次一个来源，每次请求记一行，拒绝也逐个记录。
- **落盘：** 本次会话的 `/work/sources/`，文件只读。论文为 `/work/sources/<来源 ID>/paper.md`；代码为 `/work/sources/<仓库>@<commit>/` 下的原有目录结构（无 git 历史），另有清单 `/work/sources/<仓库>@<commit>.files.tsv`（每行路径、行数、哈希），放在仓库目录之外。
- **返回：** 一条 JSON，不到 1 KiB。论文：`source_id`（实际版本）、`kind`、`path`、`lines`、`sha256`、`reused`；代码：`source_id`、`kind`、`root`、`files`（文件数）、`manifest`、`reused`。`reused` 为真时返回已有路径，并报告哈希是否仍一致。
- **拒绝：** 未开放与不存在统一回答 “no source with this id is available”，不区分，以免泄露以后会出现的材料；具体原因只进记录。格式错误（如 `arXiv:` 前缀、带路径）另给提示，说明应写作 `2106.13008v5`。
- **不带版本号的 ID**（如 `2106.13008`，写者从参考文献读到的编号常不带版本）：解析为该编号已开放的最新版本，返回中给出实际版本，与真实 arXiv 一致，不泄露开放状态以外的信息。写者写 anchor 时用返回的版本化 ID。
- **服务进程：** 在沙箱外运行，由运行器为每个会话启动，传入该会话 `/work/sources/` 在宿主机上的路径，与 A3 的 MCP 服务一样经 socket 接入沙箱。

### 2.4 B4 中断重试与会话归档（2026-10-22 定）

现状（`eval/src/pweval/harness/timeline.py` 的 `recover`）：库没变就重跑，但沿用被中断那次的工作目录与 home（`rerun_inherits_workdir`）；库变了不重跑，记 `exit: interrupted`。f3 改为：

- **中断**只指运行器或基础设施退出（进程被杀、宿主机重启等）。写者自己的超时、调用上限、报错退出照实记账，不重跑。
- **库没变：** 从全新的 `/work` 与 home 重跑，不继承被中断那次的任何文件，来源按需重新下载，开放状态不变。记录写 `rerun_after_interruption` 指向被中断那次；去掉 `rerun_inherits_workdir`。
- **库已变：** 不重跑，记 `exit: interrupted`。被中断那次的未发布内容照样归档，标为“中断”，不计入该组的未发布贡献。
- **“库没变”的判断：** A3、A2 看库版本；A4 看节点数、边数与哈希；A0 看共享仓库已发布的 head（不再看工作树）。
- **A0 的发布时机：** 会话正常结束时，运行器把写者本地的提交同步到共享仓库；中断的会话不同步，本地提交随归档保存。属 M3 的实现，但决定了上面的中断判断。
- **会话归档：** 每个会话结束时（不论怎样退出）把 `/work`（含 `sources/`）与 home 打包为 `session-snapshots/<序号>-after-<时刻>.tar.gz`，只供审计，不挂给后续会话。会话前不再打包：A0 记克隆时的提交号，其他组记库版本。

### 2.5 B5 引用写法（2026-10-22 定）

| 来源 | 写法 | 例 |
| --- | --- | --- |
| 论文 | `<arXiv 编号>v<版本>::<起>:<止>`，中间可加章节名作提示 | `2205.13504v2::210:245`、`2205.13504v2::Experiments::210:245` |
| 代码 | `<仓库>@<8 位 commit>::<仓库内路径>::<起>:<止>` | `Autoformer@09994619::layers/AutoCorrelation.py::30:48` |

- 按来源 ID 的形状区分：论文匹配 `\d{4}\.\d{4,5}v\d+`，代码匹配 `<名字>@<8 位十六进制>`。代码引用不支持章节提示。
- 路径相对仓库根目录，`/` 分隔，去掉开头的 `./`；含 `::` 的路径拒绝。不设转义（三个开放仓库的路径中没有 `:` 与空格）。
- 行号沿用 `system/src/paperweave/model/refs.py` 中 `normalize_ref` 的宽松写法（`L12-L20`、`12–20`、单行 `12`），去掉反引号与方括号照旧。
- anchor 必须带版本号：不带版本号的来源 ID 在 anchor 中拒绝，提示写出版本。与 `read_source` 不同，anchor 是长期记录，须固定到某个版本。
- 只写来源或只写到文件的引用，在边与产物中语法合法，在 grounded 记录中被提交校验拒绝（设计 §4.1）。
- 产物正文中的引用用同一套写法，`SOURCE_IN_TEXT` 改为识别两种来源 ID；`method_0030` 等节点 ID 照旧推出 `USED` 边；`art_xxxx::a:b` 只是写者 `read_evidence` 的读取输入，不是引用。
- **边上的 `paper` 字段去掉：** 它原来说明边的锚点行在哪篇论文中（起点不是论文或论文内容时），f3 的 anchor 自带来源 ID，系统按来源 ID 找到声明它的 Paper。Content 的 `paper` 保留（记录所属的论文，生成 `FROM` 边）。

### 2.6 B6 各类记录可用的来源（2026-10-22 定）

| 记录 | anchor 的来源须是 |
| --- | --- |
| Content（贡献、主张、实验） | 所属 Paper 声明的来源之一；不能锚到代码 |
| 边 | 库中某个 Paper 或 Code 声明过的来源；不检查来源与边两端的关系 |
| 产物中的引用 | 可解析（已开放、格式正确）即可，不要求有实体声明 |

- Content 是“论文说了什么”，属 grounded 层，证据只来自这篇论文。从代码读出的事实写成边（如 `Code -IMPLEMENTS-> Method` 锚到实现文件的行）或写进 note-i6 的产物。
- **Code 也声明来源：** 加 `source` 字段，写法同 Paper（如 `source: ["Autoformer@09994619"]`）。f2-A3 库中的 27 个 Code 实体只有 `url:` 身份标识，没有固定版本的记录。
- 每个被声明的来源都能找到声明它的实体，按版本判断过时由此成立；产物引用了没人声明的来源时，这条引用不参与过时检测，但仍然合法。

### 2.7 B7 种子转换（2026-10-22 定）

正式种子在题库 `~/pw-lab/probes/seed/`（不是 `eval/seeds/`）：`01-seed.yaml`（graph-doc，2 篇种子论文，49 个锚点，写作 `anchor: ["79:79"]`）、`02`–`04` 三张排行榜（引用写作 `paper_0001::773:773`）、`a0/store/`（A0 起点仓库）、`a4/episodes.yaml`（A4 起点）。都是冻结材料，原文件不改。

- **对应表**由种子中 Paper 的 `material` 机械推出，两行：`paper_0001` → `2012.07436v3`（Informer），`paper_0002` → `2106.09305v3`（SCINet）。种子在空库上按序提交，这两个 ID 确定（种子 README）。
- **转换：**
  - `01-seed.yaml`：Paper 的 `material` 改为 `source`；Content 的裸 anchor 按所属论文补上来源 ID；边的 anchor 按边上的 `paper` 字段或起点所属论文补上来源 ID，再去掉边的 `paper` 字段（B5）；
  - `02`–`04`：`paper_xxxx::…` 改为来源 ID；
  - `a0/store/`：节点文件与产物同样处理，位置写法按 B5；
  - `a4/episodes.yaml`：留给 M4。
- **存放：** 一次转换，生成题库 `seed/f3/` 下的同名文件，连同对应表与核对结果提交到题库仓库，供审阅 diff；运行器读这一份。
- **核对：**
  1. 来源服务中两篇种子论文的文件与种子材料 SHA-256 相同，行号原样沿用；
  2. 转换后不残留 `paper_\d{4}::` 引用，也不残留不带来源 ID 的裸行号 anchor；
  3. 转换前后锚点与引用数逐类相等（graph-doc 中 49 个，排行榜引用逐份计数）；
  4. 新系统实现后，在空的测试 Neo4j 上重放，提交校验通过，三张排行榜没有 `_stale`（属 M1 冒烟）。

## 3 工作项

按完成标准逐项记录：状态、对应 commit、验证结果。

| 工作项 | 完成标准 | 状态 | commit | 验证 |
| --- | --- | --- | --- | --- |
| system：anchor、Paper `source`、校验、过时、`read_evidence` | 1 | 未开始 | | |
| 来源服务 `read_source` | 2 | 未开始 | | |
| 运行器 | 3 | 未开始 | | |
| 种子转换 | 4 | 未开始 | | |
| 冻结材料 | 5 | 未开始 | | |
| 冒烟 | 6 | 未开始 | | |

## 4 实现中的决定

设计文档没有写到、由实现时决定的细节，逐条记下内容与理由；需要用户确认的标出。

（暂无）

## 5 冻结记录

M1 完成时填写：代码版本、运行配置、任务文字、材料表与对应表的哈希。

## 6 冒烟结果

（暂无）
