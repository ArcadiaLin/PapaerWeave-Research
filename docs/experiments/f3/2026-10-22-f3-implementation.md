# f3：工程落地记录

状态：M1 完成（2026-10-22）。挡路项 B1–B7 已定，六个工作项完成；任务文字与材料表经用户复核确认后冻结（5.2），冒烟结果见第 6 节。f3-A3 写者时间线可以正式开跑。
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
| system：anchor、Paper `source`、校验、过时、`read_evidence` | 1 | 完成 | 10a8fa0 | system 测试 276 项通过、eval 测试 170 项通过（临时 Neo4j `pw-f3-test`，端口 7699）；决定见 4.1 |
| 来源服务 `read_source` | 2 | 完成 | c3101e0 | `eval/tests/test_source_server.py` 5 项通过（交付与只读、复用与完整性、拒绝不区分未开放与不存在、不带版本取已开放的最新版本、代码清单、stdio MCP）；决定见 4.2 |
| 运行器 | 3 | 完成 | 6864820 | eval 测试 178 项通过（含开放与哈希核对、全新会话目录、中断两种情形、归档、沙箱挂载）；决定见 4.3 |
| 种子转换 | 4 | 完成 | 题库 addd7b6 | `scripts/seed_f3.py` 生成 `seed/f3/`；核对 1–3 写在 `seed/f3/CHECK.md`（种子论文哈希与材料表、f2-A3 副本一致；无残留；锚点 49 个、各榜引用 18/17/18 逐份相等）；核对 4：经运行器 `setup` 在空的 `pw-f3-test` 上重放，分支头 commit_000002，49 个锚点都带来源 ID，三张榜无 `_stale`；决定见 4.5 |
| 冻结材料 | 5 | 完成（用户 2026-10-22 复核后确认，见 5.2） | 题库 c2e7e91 | `scripts/tasks.py --f3`：73 项中改写 50 个任务，其余字段与 `plan.yml` 逐项相同；材料表 33 个论文来源、3 个代码仓库，点出的来源在该会话开始时都已开放（脚本内断言）；决定见 4.4。冻结记录在第 5 节 |
| 冒烟 | 6 | 完成 | 代码 6864820 与 3cfbbe6，题库 addd7b6 | 5 个会话（build、leaderboard、note-i6、update、compare）与检查点 k10 全部正常结束，第 1.1 节第 6 项的四项检查都通过；审查修正后以 build、update 与检查点复测通过，见第 6 节 |

## 4 实现中的决定

设计文档没有写到、由实现时决定的细节，逐条记下内容与理由；需要用户确认的标出。

### 4.1 system（10a8fa0）

1. **来源不登记为 Material。** Paper 与 Code 的 `source` 是节点上的列表属性，随节点经 graph-vc 版本化；Material 只留给产物文档。理由：来源内容由来源目录按 ID 固定，库不必另存路径与哈希；版本先后从 ID 读出（设计 §4.1），不需要 `superseded_by`。
2. **来源目录**由 `PAPERWEAVE_SOURCES` 给出，默认 `<材料根目录>/sources`；布局为 `<论文来源 ID>/paper.md`、`<仓库>@<commit>/<仓库内路径>`，与 `read_source` 的落盘相同（B3）。system 只读它；目录中只放已开放的来源，由运行器维护（工作项 3）。实现在 `system/src/paperweave/store/sources.py`。
3. **锚点存规范写法**（`normalize_ref` 之后：去掉反引号与方括号、`L12-L20` 写成 `12:20`、代码路径去掉开头的 `./`）。`set` 中原样贴回的现有锚点不再检查：论文的 `source` 去掉旧版本后，`get` 出的记录贴回 `set` 不会被挡。
4. **允许的来源（B6）的具体判断：** Content 按本次提交之后所属 Paper 的 `source`（同一提交中改了 `source` 或换了论文时按改后的；修订依据的 anchor 同样）；边按库中或本次写入后任一 Paper、Code 的 `source`；产物只要可解析。
5. **同一来源可以被多个 Paper 声明**，不报错。重复论文属 C1，测量而不阻止；否则 A2 的查重消融失去意义。
6. **`source` 可以清空，也可以去掉旧版本**，不检查已有锚点：已写的锚点自带版本，按来源目录照样可读，过时仍按库中声明的最新版本判断。
7. **不再写 `material_ref`：** `FROM` 边与带锚点的边上没有它。产物中的来源引用连一条 `USED` 边到声明该来源的实体（多个时取 id 最小的），`locators` 记完整的来源引用；没有实体声明的来源不连边（B6）。产物引用产物仍在 `USED` 边上记 `material_ref`（所引的产物版本）。
8. **产物中的来源引用只检查可解析与不越界**，不检查所引行有没有文字（沿用 f2 产物的规则）；记录与边的锚点照旧检查“不是空行或纯标记”。
9. **库内 id 开头的来源引用**（`paper_0001::…`）在锚点与产物中被拒绝，提示改写来源 ID；`parse_ref` 仍能解析它，只作为 `read_evidence` 读产物文档的输入（`art_xxxx::a:b`、`material_xxxx::a:b`）。写者用论文的库内 id 调 `read_evidence` 时返回 `missing`，并给出该论文声明的来源 ID。`at` 只作用于产物文档，来源 ID 本身固定版本。
10. **过时原因：** 来源引用解析不了（不在来源目录、文件不在、行号越界、不以来源 ID 开头）记 `material`；库中有更新版本时记 `superseded`，`by` 为新版本的来源 ID。`_anchor_version` 列出记录本身与它的出边中写在旧版本上的锚点。
11. **去掉 `read_evidence` 的 `anchored` 范围**与 `query/anchored.py`：f3 读者的工具在评测侧（M2），而它依赖已去掉的 `material_ref`；f2-A3 读者若要重跑，用 10a8fa0 之前的代码。保留 `artifacts` 范围。
12. **A2 的修订约束消融不变：** `eval/baselines/a2_mcp.py` 只滤掉 rule 为 `revision` 的问题；锚点与来源的问题（rule `anchor`、`source`）不受影响，即记录有效性两组都有（设计 §4.1）。
13. **工具说明**（`system/src/paperweave/mcp/server.yml`）随之改写：示例中 Paper 写 `source: [2205.13504v3]`，锚点写 `2205.13504v3::120:135`；新版本的规则改为“把新版本的来源 ID 加进 Paper 的 `source`”；边的锚点说明去掉 `paper`。

### 4.2 来源服务（c3101e0）

1. **实现为评测侧的标准库 MCP stdio 服务**（`eval/src/pweval/harness/source_server.py`），不进 system：来源服务模拟外部世界（arXiv、代码托管站），四组共用，与被测系统无关。服务名 `Sources`，pi 中的工具名为 `mcp__Sources__read_source`。
2. **每个会话启动一次**，经 `bridge.py unix-exec` 与 `sources.sock` 接入沙箱；可取的来源由运行器写进会话目录的 `opened.json`，请求记录在会话目录的 `sources.jsonl`（时间、请求原文、解析结果、结果、拷贝字节数；拒绝另记原因：未开放、不在语料、格式）。
3. **代码的完整性**用目录内容哈希：按相对路径排序，逐个文件的“路径、NUL、内容 SHA-256”再取 SHA-256；材料表（题库 `scripts/tasks.py`）用同一算法。
4. **格式错误**（`arXiv:` 前缀、含 `/`、`::` 或空格、不像来源 ID）回答格式提示而不是统一拒绝：它们不涉及开放状态，提示不泄露材料。
5. **不带版本号的编号只在已开放的版本中选最新**，没有已开放版本时统一拒绝。
6. **`/work/sources/` 在沙箱内只读挂载**（服务在沙箱外写宿主机的同一目录），不只靠文件权限：写者不能改动或删掉取到的原文；`reused` 时仍报告 `intact`。

### 4.3 运行器（6864820）

1. **新配置 `eval/config/f3-ltsf.yml`**，成为运行器的默认配置；与 `formal-ltsf.yml` 的差别只在题库中的三个位置（`plan`、`materials`、`seed`）与说明文字，服务、模型与预算不变。运行器要求这三项，`formal-ltsf.yml` 留作 f1、f2 的记录，不再能直接运行。
2. **f3 只接通 A3、A2**：`--arms` 默认 `A3,A2`，给出 A0、A4 时拒绝运行（M3、M4）。沙箱与来源服务的接法对四组相同，A0、A4 接通时不必再改。
3. **会话目录** `<组>/sessions/<序号>-<时刻>/`，每次尝试新建，同一身份也不复用；`writers/<身份>/` 不再使用。目录在会话后保留（`sessions.jsonl` 中的事件流与会话记录路径指向它），不挂给后续会话。
4. **组的来源目录** `<组>/sources/`：会话开始时（`inflight.json` 写入之前）按材料表把到该会话为止开放的来源从语料复制进去，复制前按材料表核对哈希，不一致即停。它是 A3、A2 的 MCP 服务的 `PAPERWEAVE_SOURCES`：提交校验与写者的 `read_evidence` 认的是本组已开放的全部来源，不限于本会话取到的；`read_source` 只交付本会话可取的来源。种子来源在建立起点时开放，种子重放也用这个目录。
5. **写者的来源说明**（B2 的一句）放在 `sandbox.WRITER_NOTE`，接在 `ENV_NOTE` 之后，各组相同。
6. **`sessions.jsonl` 新增字段**：`root`（会话目录）、`materials`（`named`、`opens`、`available`：此时可取的来源数）、`read_source`（请求数、各结果的次数、取到的来源、拷贝字节数）、`archive`（会话归档的路径与哈希）。去掉 `workdir_before`、`workdir_after` 与 `rerun_inherits_workdir`。
7. **中断（B4）**：库没变时，被中断那次的目录归档为 `<序号>-interrupted-<时刻>.tar.gz`，记在重跑记录的 `rerun_after_interruption.archive` 中，重跑在新目录；库已变时按 `exit: interrupted` 记账（`recovered`），归档同样标 `interrupted`。
8. **写者时间线不再运行读者**：`--no-readers` 去掉，检查点上只记版本、快照与备份；读者按 M2 在备份上离线作答。`reader_arm` 等读者函数留给 M2 改写（其中的 `anchored` 范围已随 system 去掉）。
9. **`status` 只看配置中有的组。**

### 4.4 冻结材料（题库 c2e7e91）

1. **任务文字的改写由脚本机械完成**（`scripts/tasks.py` 的 `f3_task`）：每类只替换 B2 所列的片段，并断言原片段恰好出现一次；`plan.yml` 不动。
2. **verify-later 的句式**按 B2 写作 “Is the claim of the PatchTST paper (2211.14730v2; fetch it with read_source) that …”：把来源 ID 放进括号需要把所有格改成 “the claim of”，其余措辞不变。
3. **materials.yml** 的结构：`seed`、`sessions`（每个会话的 `seq`、`type`，有则 `named`、`opens`）、`sources`（每个来源的 `kind` 与内容哈希）。checkpoint 不在 `sessions` 中。

### 4.5 种子转换（题库 addd7b6）

1. **逐行替换而不是解析后重写**：YAML 重新输出会改动引号、折行与注释，审阅 diff 时看不出只改了位置。脚本按行替换，并断言转换前后每份文件的锚点与引用数相等。
2. **注释中的论文路径**（`01-seed.yaml` 两处节标题）一并改为来源 ID，转换后的文件中不留 `papers/` 路径。
3. **A0 的起点仓库（`a0/store/`）一并转换**：B7 列入，转换规则与 A3 相同；A0 的约定文字与运行器接法属 M3。
4. **核对 4 经运行器的 `setup` 完成**，与正式运行建立起点的路径相同（先开放两篇种子论文，再重放），不另写重放脚本。

### 4.6 冻结后的审查与修正（2026-10-22）

M1 冻结后的一轮代码审查提出六条，逐条复现属实，都已修正（代码冻结版本随之更新，见 5.1；任务文字与材料表未动，5.2 的确认仍有效）：

1. **锚点检查依赖书写顺序**（78f38b3）。原实现处理到节点就检查锚点，只看得到已处理的来源声明：记录写在 Paper 之前，或同一提交中 `create` 新记录、`set` 给已有 Paper 加新版本，都被拒绝。改为全部节点与边写完之后统一检查，所属论文与 `source` 都取本次提交之后的；边上的锚点同样。4.1 第 4 条的“按本次提交之后的来源判断”至此才完整成立。新测试覆盖三种情形，修正前失败。
2. **`read_source` 与 MCP 服务读的不是同一份**（b745c00）。来源服务原从语料交付，MCP 服务读组的来源目录；组内副本存在即跳过核对。改为来源服务只从组的来源目录交付（语料只用来在拒绝时记原因），运行器在每个会话开始前对组内全部已开放来源逐个核对材料表的哈希，不一致即停；交付记录中写入所交付内容的哈希。
3. **代码不在续跑的拒绝条件中**（5593b6a）。新增“写者会话所执行代码”的指纹（`timeline.SESSION_CODE`：`system/src`、graph-doc 与 graph-vc 的源码、`eval/baselines`、运行器、沙箱、转发、来源服务、导出，加 `uv.lock` 与各 `pyproject.toml`），按磁盘内容计算，未提交的改动与未跟踪的新文件都算。续跑时与第一次调用不同即拒绝，除非给出 `--allow-code-change`（与 `--allow-config-change` 分开，放行记入 `run.yml`）；运行中每个会话开始前再比对一次，不同则这一组停下。指纹不含读者侧与其他评测代码，M2 在 A3 运行期间开发不会触发它；M2 若要改上述文件，正式运行会停下，须显式放行并记录。
4. **备份的完整性判断**（3cfbbe6）。`backup_complete` 现在还核对篇数与 `checkpoints.yml` 记录的版本（不取在线库的当前分支头）；已有但不合格的目标另存为 `k<篇数>.invalid-<时刻>` 后重做；dump 用容器实际运行的镜像 ID，`meta.yml` 同时记标签与 ID。
5. **备份缺来源**（3cfbbe6）。备份增加 `sources.tar.gz`：组的已开放来源目录，打包前按材料表核对哈希；`meta.yml` 记各来源的哈希。来源合计只有几 MB，随每个检查点打包，恢复不依赖外部语料。
6. **代码清单的行数**（b745c00）。改为与系统读锚点相同的计法（UTF-8 解码后 `splitlines`，末行没有换行也算一行）；不是 UTF-8 文本的文件记 `-`。

## 5 冻结记录

### 5.1 冻结的版本（2026-10-22）

| 项 | 版本或 SHA-256 |
| --- | --- |
| 代码（system、eval） | 3cfbbe6（审查修正后，见 4.6；原冻结为 6864820） |
| 写者会话所执行代码的指纹（`timeline.code_fingerprint`，121 个文件） | `8bea87197e107ceedb0ad49dd37569e8e4bd2656ea11c89a180da34b2f7b862c` |
| 运行配置 `eval/config/f3-ltsf.yml` | `893311037f14b939b2df57db782d657160b93263d99b3862b207695e99b8e9a2` |
| 题库仓库 | addd7b6 |
| `tasks/plan-f3.yml`（B2） | `81b06f2aeac1fb4c347e1998dbbbe7a795349371d1a02194de00ba3fff00fce5` |
| `tasks/materials.yml`（B1） | `42156b3c4a08e73a416f61d5252729f7943ad4145d3287fc7b381613027c21b6` |
| `tasks/identities.yml`（未改） | `7acd603be718356c4b8ae6089e618c21d4a01968c552947bc2ceb5cf22cc8d12` |
| `tasks/hints.yml`（未改） | `c2f628da51f5ea35f80e84674dfc9809998f78f1d76c7f1c87db06898fb5df36` |
| `seed/f3/mapping.yml`（B7） | `547fa21f9baa67a9a70303958395c035fb0c8cf0bcbbba6effe7b6bc8e8fa466` |
| `seed/f3/01-seed.yaml` | `cefc2be1a58baedc7073f0b9febf16d2a4923507a0cc9e5405656137141bcf05` |
| `seed/f3/02-lb-etth1.md` | `dd7565921af83b6b3e004224e8fec4900f25036c346ab804cdb795effcf1bf49` |
| `seed/f3/03-lb-electricity.md` | `d7db12942eb55bb246e0c052c07c2be0a385b6d84e8bed6cd6019f058efc9e1e` |
| `seed/f3/04-lb-etth2.md` | `08522ec9075942b3a98a5660b5a15ae82427b3284d0ab6e9ec6597a721f77fd7` |
| pi | 1.2.0 |

服务、模型与预算同 f2（`formal-ltsf.yml` 的 `arms`、`runner` 逐项相同）。运行器启动时把实际生效的配置、两个仓库的提交与代码指纹写进 `run.yml`；续跑时配置或题库与第一次不同即拒绝（`--allow-config-change` 放行），代码指纹不同也拒绝（`--allow-code-change` 放行），运行中每个会话前再比对代码指纹（4.6 第 3 条）。

### 5.2 用户确认

**任务数：** 完成标准第 5 项写“40 个任务”，取自设计 §7：38 个 build、build-overlap、update 任务写着 `papers/<id>/paper.md`，2 个 note-i6 任务写着 `code/`。B2（2026-10-22 与用户敲定）把范围扩到 50 个：另有 compare 4、verify-own 3、verify-later 3 共 10 个任务，按 B1 点出来源 ID。实际改写 50 个，以 B2 为准；第 1.1 节的“40”是 B2 之前的数字。

**确认（2026-10-22）：** 用户逐项复核了任务措辞（各类的改写句式，含 verify-later 所有格的改动，见 4.4 第 2 条）、note-i6 的代码（I6-1 给 `Autoformer@09994619`，I6-2 给 `ARMA-Attention@a9e6d31b` 与 `CATS@71d18a9f`）、写者来源说明（`WRITER_NOTE`）与材料表（种子、各会话点出与新开放的来源），确认按现状冻结 `plan-f3.yml`（`81b06f2a…`）与 `materials.yml`（`42156b3c…`），哈希见 5.1。此后改动须重新确认。

## 6 冒烟结果

2026-10-22 12:45–13:31（UTC），运行名 `f3-smoke`（`~/pw-lab/runs/f3-smoke/`，配置与任务表的副本也在其中）。条件：临时 Neo4j `pw-f3-test`（7699）；空闲的 sglang 30001（当时没有正式运行）；运行配置为 `f3-ltsf.yml` 改动图库、大模型与任务表；任务表取 `plan-f3.yml` 中的第 3、5、6、14、17 个会话，最后加一个检查点 k10。

| 序号 | 类型 | 身份 | 退出 | 用时（秒） | 库版本 | `read_source` |
| --- | --- | --- | --- | --- | --- | --- |
| 3 | build（FiLM v3） | i3-b | 0 | 651 | 000002 → 000004 | 交付 1 |
| 5 | leaderboard（ETTh1） | i3-b | 0 | 216 | 不变（noop） | 0 |
| 6 | note-i6（Autoformer） | i1-b | 0 | 380 | 000004 → 000006 | 交付 2（论文与代码） |
| 14 | update（FiLM v3 → v4） | i3-b | 0 | 931 | 000006 → 000008 | 交付 2 |
| 17 | compare（C1） | i3-c | 0 | 535 | 000008 → 000012 | 交付 2、拒绝 1 |

检查点 k10：快照、离线备份（停下 `pw-f3-test` 做 dump 后重启，版本核对一致）都完成；没有运行读者。各会话的联网命令 0 条，工具命令没有被终止。

**第 1.1 节第 6 项的检查：**

1. **开放与拒绝：** 写者都用 `read_source` 取材料；note-i6 取到论文与代码仓库（2,275,901 字节，附清单）。compare 的写者请求 `2106.13008v1`（不在语料中），得到统一的拒绝，原因只进记录。拒绝“已在语料、尚未开放”的情形由单元测试覆盖（`test_refusals_do_not_tell_unopened_from_missing`），冒烟中没有出现。
2. **库中 anchor 的格式：** 结束时库中 123 个锚点（节点与边）全部以来源 ID 开头：种子 49 个，写者 74 个，分布在 FiLM v3/v4、Autoformer、TiDE、TimeMachine 上。build 写者给 Paper 声明了 `source: [2205.08897v3]`；note-i6 写者新建 `code_0001`，`source: [Autoformer@09994619]`。Note 引用了 21 处代码行（`Autoformer@09994619::<文件>::a:b`），`USED` 边连到 `code_0001`。CompareSettings 的来源引用连到 4 篇论文。
3. **update 后的过时标记：** update 写者把 `2205.08897v4` 加进 `paper_0003` 的 `source`，改写了 50 个锚点；仍写在 v3 上的 13 个锚点所在记录读出 `_anchor_version`（如 `exp_0018`：“anchor cite 2205.08897v3; paper_0003 now also has the newer version 2205.08897v4 …”）。ETTh1 排行榜中 FiLM 的行读出 `_stale`（`reason: superseded`，`by: 2205.08897v4`）。
4. **不继承私人文件：** 每个会话一个新目录 `A3/sessions/<序号>-<时刻>/`。i3-b 的三个会话（3、5、14）中，后一个的 `work/` 里没有前一个的草稿（如第 3 个会话的 `film_graph.yaml`），`sources/` 里只有本会话取到的来源。每个会话结束后的 `/work` 与 home 归档在 `A3/session-snapshots/<序号>-after-*.tar.gz`。

**附带观察（不挡 M1）：** leaderboard 会话没有改动，因为 build 写者在第 3 个会话中已把 FiLM 加进 ETTh1 排行榜（`art_0001` v2）。这是写者自己的选择：build 任务没有要求维护排行榜。leaderboard 写者核对数值时用的是 PaperWeave 的 `read_evidence`，没有调用 `read_source`。

### 6.1 审查修正后的复测

2026-10-22 15:23–15:45（UTC），运行名 `f3-smoke2`（`~/pw-lab/runs/f3-smoke2/`），代码 3cfbbe6，条件同上，任务表取第 3（build FiLM v3）、14（update 到 v4）两个会话加检查点 k10。

| 序号 | 退出 | 用时（秒） | 库版本 | `read_source` |
| --- | --- | --- | --- | --- |
| 3 | 0 | 672 | 000002 → 000003 | 交付 1 |
| 14 | 0 | 615 | 000003 → 000004 | 交付 2 |

- **同一份来源（4.6 第 2 条）：** 来源服务从组的来源目录交付，记录中带内容哈希；每个会话开始前全部已开放来源核对通过。
- **代码指纹（第 3 条）：** `run.yml` 记下指纹 `8bea8719…`，两个会话记录中的指纹相同。运行期间工程记录有改动，不在会话代码中，没有触发停止。
- **update：** `paper_0003` 的 `source` 为 `[2205.08897v3, 2205.08897v4]`。写者在 v4 上写了 19 个锚点，仍写在 v3 上的 19 条记录读出 `_anchor_version`。这次 build 写者没有改排行榜，所以排行榜上没有 `_stale`。
- **备份（第 4、5 条）：** k10 备份含 `neo4j.dump`、`data.tar.gz`、`sources.tar.gz`（12 个已开放来源），`meta.yml` 记镜像 `neo4j:ubi10` 与镜像 ID `sha256:e3650ddb…`；dump 用镜像 ID 完成，库重启后版本核对一致。
