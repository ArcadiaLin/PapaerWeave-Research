# A0 的种子 Leaderboard：转换规则

> **状态：** 2026-10-14 起草（B5）。规则在此冻结，由 C3 在 harness 中实现；实现不 import e09（evaluation_draft §10.1）。

A0（文件 + git）拿到与 A3 相同的种子 Leaderboard，内容逐行相同，写法换成 A0 笔记库的约定（`t1.a0_seed`：每个对象一个
Markdown 文件，相对链接，不出现 A3 的 id）。A0 不附维护提示，不给 skill（evaluation_draft §2.2；todo B5）。

## 1. 位置与提交

- 文件：笔记库的 `leaderboards/<文件名>`，文件名与 `seeds/leaderboards/` 中的相同（如 `etth1-multivariate.md`）。
- 与锚点、种子论文的笔记一起，在检查点 0 的同一个提交中由 `seed` 提交（`checkpoint-0` 标签不变）。
- README 的布局说明加一句，只描述，不提要求：

  > `leaderboards/` holds results tables, one per dataset and setting, with the paper lines of every number.

## 2. 头部

A3 文档的 YAML 头部换成 A0 笔记的写法（标题行加要点列表）：

| A3 | A0 |
| --- | --- |
| `title` | 第一行 `# <title>` |
| `abs` | 标题下的一段正文 |
| `type: Leaderboard` | 不渲染 |
| `task`、`dataset` | `- **task:** <链接>`、`- **dataset:** <链接>`，链接文字为该对象笔记的名称 |
| `setting` | `- **setting:** variate: multivariate`（映射写成 `键: 值`，多项以逗号分隔） |
| `metrics` | `- **metrics:** MSE (lower is better), MAE (lower is better)` |

## 3. 结果表

列与行的顺序不变，只改三列：

- `method`：`method_0001 Informer` → `[Informer](../methods/informer.md)`；链接文字是单元格中 id 之后的文字，目标是该 id 的笔记。
- `paper`：`paper_0001 Informer` → `[Informer](../papers/informer-2012-07436.md)`，规则同上。
- `source`：去掉开头的论文 id，只留 `<章节>::<行>`，多个仍以 `; ` 分隔。同一行的 `paper` 列已链接到论文；CheckIn 保证
  `source` 落在该行论文的材料中，所以信息不丢。

其余列（`variant`、`role`、`origin`、`lookback`、`pred_len`、指标）原样照抄，空格子仍为空。

## 4. 正文中的引用（Notes、Papers covered）

- 方括号中的来源引用 `[paper_0002::4.2 Results and Analyses::315]` → `[SCINet](../papers/scinet-2106-09305.md) 4.2 Results and Analyses::315`：
  去掉方括号，论文 id 换成指向论文笔记的链接，链接文字是论文的短名（标题中冒号之前的部分，与论文笔记的文件名同源）。
- Papers covered 的 `paper` 列按 §3 的 `paper` 规则；`tables` 列中不带方括号的引用 `Table 2 (paper_0001::Datasets::265:273)` →
  `Table 2 (Datasets::265:273)`，理由同 §3 的 `source`。
- 其余文字原样照抄。

## 5. 不渲染的内容

- `id`、`base` 与任何 A3 的 id（`method_`、`paper_`、`dataset_`、`task_`、`art_` 等）；
- CheckIn 与 FetchArtifact 在读取时现算的附注（各编辑者的行数、所引论文已有新版本的行、同一格的多个值）与编辑提示；
- skill，以及任何“请统一维护这些表”的说明。

## 6. 例子（ETTh1，前两行）

```markdown
# ETTh1 multivariate long-term forecasting

MSE and MAE reported on ETTh1 in the multivariate setting (all seven variables predicted), by method, paper, look-back
and horizon, with the source line of every number.

- **task:** [Long-term time series forecasting](../tasks/long-term-time-series-forecasting.md)
- **dataset:** [ETTh1](../datasets/etth1.md)
- **setting:** variate: multivariate
- **metrics:** MSE (lower is better), MAE (lower is better)

## Results

| method | variant | paper | role | origin | lookback | pred_len | MSE | MAE | source |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| [Informer](../methods/informer.md) |  | [Informer](../papers/informer-2012-07436.md) | target | run | searched in {24, 48, 96, 168, 336, 480, 720} | 24 | 0.577 | 0.549 | Datasets::269 |
| [SCINet](../methods/scinet.md) |  | [SCINet](../papers/scinet-2106-09305.md) | target | run | 48 | 24 | 0.300 | 0.342 | 4.2 Results and Analyses::310:311; Appendix C Reproducibility::937 |
```

（任务与数据集笔记的名称以渲染时库中的名称为准；上例按检查点 0 的笔记库写出。）

## 7. 不变式（C3 实现时检查，任一不满足即失败）

1. 渲染结果中没有 A3 的 id（沿用 `t1.a0_seed` 的检查）；每个相对链接都指向存在的文件。
2. 与 A3 的种子文档逐行对应：结果表行数相同；每一行的方法、论文（链接目标对应原 id）、`variant`、`role`、`origin`、
   `lookback`、`pred_len`、各指标与 `source` 的章节和行号都相同。
3. 同一组种子渲染两次，结果逐字节相同。

## 8. 与 C3 的接口

- 输入：`seeds/leaderboards/*.md` 与 A0 笔记库中 id → 笔记路径、名称的映射。
- 现在的映射来自 `t1.a0_seed` 的渲染（它经 e09 的重放得到图状态，违反 §10.1）；C 阶段改写 A0 渲染时，映射改由
  A3 检查点 0 的冻结快照（graph_model_v2 的 Cypher 读取）给出，本规则不变。
