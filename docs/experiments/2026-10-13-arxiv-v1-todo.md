# arXiv v1：评测前的工程待办

> **状态：** 2026-10-13 建立。范围依据 [讨论稿](../discussions/2026-10-13-skills-catalog-and-checkin.md) §11 与 [评测草案](../designs/v2/evaluation_draft.md) §11.1。完成一项勾一项；每一组开工前先给出实现方案，讨论后再落代码。
>
> **已定：**
> - v1 的产物类型：Leaderboard、Generate、Skill 必做；CompareSettings、Verify、Summarize 只登记契约，不写种子；
> - 写入保留 `Commit` 与 `CheckIn` 两个工具；
> - A0 不给 skill；
> - 不放开模型冻结：Skill 是 Artifact 的一个类型，不加实体类型与字段；
> - 第一步是 A1–A3，先交实现方案；
> - 2026-10-14：标题改回 Knowledge；Skill 维持必做，砍掉 B3（[头脑风暴](../discussions/2026-10-14-design-brainstorm.md)）。
>
> **更正：** 评测草案 §10 把 `_stale` 的 `revised` 记为待实现，代码已有（`c3a4336`）。

## 执行顺序

1. A：系统部分，带测试；
2. B：种子 skill 与种子产物，由 Claude 起草，用户确认后冻结；
3. C1–C3：运行框架接入；
4. pilot-3：A0 与 A3，1 个与 4 个写者各一条时间线；实测写入重叠、采用率、skill 读取率与单篇成本；
5. C4–C7 定稿，冻结协议（伪用户背景、探针、金标准、判分口径、正式语料与规模），记录写入 `docs/decisions/`；
6. 8 条正式时间线与探针。

## A. 系统（`experiments/e09/`）

- [ ] **A1 `CheckIn`。** 从文档头部读出类型，按类型取契约：身份键、行键、轻度规则。先校验，带 `confirm` 才写入；撞键时退回已有的那份；`base` 冲突检查；改他人的行须写理由（[算子契约](../designs/v2/operators.md) §4.1）。在 `artifact/write.py` 的基础上改：现有的是旧版“一次性请求、写入后不可修改”的形状，引用校验、写文档与单事务提交可沿用。
- [ ] **A2 产物版本。** 新版本的 Material；上一版本记 `superseded_by`；按新版本重写 `USED`；更新 `title`、`abs`；版本号与编辑者由提交链推出（算子契约 §5.5）。
- [ ] **A3 `FetchArtifact`。** 文档取到工作目录，带 `id`、`base`；编辑提示（版本号、最近的编辑者与修改说明、各编辑者，以及“自你上次编辑以来别人改了哪些行”）；可一次取多份；`at` 取历史版本（算子契约 §3.6、§5.6）。Skill 写到 `.agents/skills/<name>/SKILL.md`，`id`、`base` 放进头部的 `metadata`。
- [ ] **A4 类型契约。**
  - Leaderboard：身份键（任务、数据集、设置），行键对齐，`others`，读取时的附注；
  - Generate：只要求引用存在；
  - Skill：Agent Skills 格式（`name`、`description`），身份键为所服务的类型；
  - CompareSettings、Verify、Summarize：只登记契约。

  旧的 Summarize、Generate、Verify 的校验可沿用（`operators/agent/`）。
- [ ] **A5 产物的 `_stale`：** 加上 `superseded`，即所引产物有了新版本（`artifact/stale.py`）。
- [ ] **A6 按键查找（G1）：** `Search` 在 Artifact 上加精确匹配的 `key` 条件（`query/conditions.py`）。
- [ ] **A7 Commit 返回相关的共同产物：** 本次写入或修改的 Experiment → 所用的评测数据集 → 以该数据集为身份键的 Leaderboard；另列出还没有 Leaderboard 的数据集（算子契约 §3.5）。
- [ ] **A8 MCP 工具面。** 去掉旧的 7 个 Agent 算子（Extract、Summarize、Generate、Check、Verify、Filter、MatrixConstruct），加上 `FetchArtifact`、`CheckIn`。工具描述只写接口契约（参数、错误、返回），类型特有的用法移入 skill（`mcp/server.yml`）。
- [ ] **A9（可选）消融开关 −写入时提示：** Commit 不返回相关的共同产物；配置开关，不改默认行为。

## B. 种子（运行前冻结，经用户确认）

- [ ] **B1 paper-form 的 skill：** 把[抽取原则](../designs/v2/extraction_principles.md)、表单模板与示例、Commit 工具描述三处中的用法整理到一处，不新增规则。
- [ ] **B2 Leaderboard、Generate 的 skill。**
- ~~**B3 Skill 的 skill**~~：2026-10-14 砍掉，推迟到投会议。Skill 仍是 v1 的必做类型；怎样写 skill 由 `CheckIn` 中 Skill 的契约说明（A4）。
- [ ] **B4 种子 Leaderboard：** 种子论文（Informer、SCINet）在各主要数据集上的 Leaderboard，包含难写的行（如 look-back 写成说明文字）。种子不能与金标准重合。
- [ ] **B5 A0 的种子：** 同样的 Leaderboard 写成文件，不附维护提示，不给 skill。

## C. 评测框架（`experiments/t1/`）

- [ ] **C1 skill 的放置：** A3 每次会话开始前，把库中各 skill 的当前版本放进写者工作目录的 `.agents/skills/`（pi 启动时扫描）；A0 不放（`run.py`、`sandbox.py`）。
- [ ] **C2 伪用户与调度：** 身份与背景（各对应一个意图）、任务提示（不提共同产物）；1 个与 4 个写者两种构成；同篇重叠 25%；固定的分配种子（[评测草案](../designs/v2/evaluation_draft.md) §2.1、§4.2）。现有调度只有先导用的 K = 2。
- [ ] **C3 起点：** A3 写入种子产物与种子 skill，并与重放状态核对；A0 渲染种子 Leaderboard 文件（`setup_a3`、`a0_seed.py`）。
- [ ] **C4 健康度 M1–M6：** 数值的来源从旧的 Extract 产物改为 Leaderboard；A0 的结果表文件也计入；补 M4 碎片化与 M6 知识流失（`health.py`，评测草案 §4.3）。
- [ ] **C5 审计 DAG：** 解析文档 → 解析 id → 规范化行键 → 出处核对 → 对照 PwC；PwC 覆盖不到的格子按固定比例抽样，供人工核对（评测草案 §4.4）。
- [ ] **C6 探针：** 从 PwC 抽取，加上按意图新写的探针；`store_only` 为主测量，另有闭卷下限与神谕上限；冻结时标注意图、所在层与交汇类型（`probe.py`、`grade.py`，评测草案 §2.4）。
- [ ] **C7 统计：** skill 被读取的会话比例与被改写的情况（来自 pi 轨迹）；绕过率；`Commit`、`CheckIn` 与各访问方法的延迟（来自服务日志）。

## 不在 v1

见讨论稿 §11 右栏与评测草案 §11.2：访问日志进库、类型定义进库、skill 随类型升级而过时、`Commit` 与 `CheckIn` 合并、ProjectView、A2 与 A4、注入事件、−skill 消融与 A0+skill 稳健性组、E3。
