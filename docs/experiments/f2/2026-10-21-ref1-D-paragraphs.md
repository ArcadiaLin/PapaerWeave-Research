# ref1-D：段落组的正式运行（2026-10-21）

状态：运行中（2026-10-21 UTC 16:01 续跑），结果与判分待补。
设计依据：`docs/designs/v3/evaluation.md` §7（各组共同的读者设置）、§10.1（段落组）。
同一运行目录 `ref1` 中的闭卷组见 `2026-10-21-ref1-C-closed-book.md`。

## 1 目的

D 段落组不给库和工具，只给依据段落：锚点处的原文，以及按题切行的主结果表。它的分数近似“检索完美时能拿多少”，是写者组（A0、A2、A3、A4）读侧的上限参照；C 闭卷组给出下限。

## 2 设置

**题库**：与 C 相同，`~/pw-lab/probes` 提交 `2f68f4e`，主题集 200 题加辅助题 6 道，共 206 题。题型分布见 C 的记录第 2 节。

**读者**：与 C 相同。pi 1.2.0，模型 `sglang/qwen3.8-27b`（推理服务 `192.168.163.112:30000`，本组独占），thinking 为 medium，上下文 262144，保留 32768。配置文件 `eval/config/refs-ltsf.yml`：

- 单次回复的输出上限为 98304 token；
- 防失控上限为 60 分钟，不设回答时限；
- 12 路并发，每题作答一次（命令行 `--reps 1`），用时不进成本比较；
- pi 不带工具（`--no-tools` 等，与 C 相同），以 `--offline` 运行。沙箱本身没有断网（`--share-net`），但读者没有工具，无法发起网络请求；回答记录中的 `network` 字段为空。

**提示语**：依次为题面原文、依据材料（库中论文清单与依据段落）、D 的说明句、题型的 Final answer 段（要点题没有这一段）。说明句为：

> No store or tools are available: the material above is all you have. Answer from these passages only. The passages contain every statement these papers make about what the question asks; if no passage shows a paper saying something, the paper does not say it.

跨论文的集合题（T5–T8 自动题）另加一句：

> The passages also include the main multivariate results tables of every paper in the store. For a question about one dataset only that dataset's rows are kept; where only the compared methods matter, only the table headers are kept.

最后一句：

> Where the question refers to "the store" or "the papers in the store", it means the papers listed above.

**与设计的偏离**：设计文档 §7 第 3 条中 D 的说明句草稿含“Cite the lines your answer rests on.”，本组实现时漏掉了，206 题都是按缺这一句的提示语作答的（10-21 在实现 P 时发现）。不重跑：D 不参与成本比较，只作读侧上限；但 D 不报“引用可核对率”，回答中有无引用也不作比较。

**依据材料**（`eval/src/pweval/protocol/evidence.py`）：

- 题目依据与参考答案中的锚点按段落展开；锚点在表内的给整张表，代码给锚点前后各 8 行（代码取自 `~/pw-lab/code` 快照，其他提交从 `references/repos` 的克隆中取）。
- 跨论文的集合题另补上库中每篇论文（最新版本）主基准的多变量结果表，以落实封闭世界：材料包含这些论文对题目所问之事的全部说法。
- 表按题目切行：
  - 题目指定数据集时，只留表头、分隔行与该数据集的行，各预测长度都留；
  - 行属于哪个数据集按 `facts/cells.csv` 判，认不出的行保留；
  - T6 补上的表只留表头，方法在行上的转置表留全表；
  - 切掉处标出“rows not asked about are omitted here”。
- 开头列出库中论文清单（标题、所用版本、首个 arXiv 版本的日期），供按日期筛选的题使用。
- 每行带原文行号（代码为文件行号）。
- 不给只供判分的背景（参考答案的 `notes` 等），也不指认题目所指的论文。
- 回答记录另存所用段落（出处、行号区间、切掉的行数）与材料的 SHA-256。

规模（按 Qwen 分词器计）：206 题合计约 547 万 token，中位 3.4 万；最长的一题是 M-T8-autoformer-etth1-336，10.7 万 token。T3、T5–T8 的中位在 3.6 万到 4.8 万之间。

**代码**：作答用 eval 提交 `4915b70`（D 的实现与材料），中途修复后为 `7cac49c`（见第 4 节）。运行记录中 eval 仓库为 `dirty: true`，原因与 C 相同：工作区里有与本组无关的未提交改动；D 用到的代码都已提交。

**命令**：`pweval-refs ref1 --groups D --reps 1 --allow-config-change`。`ref1` 的配置在 C 之后新增了 `code` 一项（D 的代码依据路径），这是与第一次调用唯一的实际差别，因此加 `--allow-config-change`，变更记入 `run.yml`。

## 3 运行前的核对

**材料核对**：逐题比对参考答案与 D 材料，看每个答案要素在材料中能否找到依据。

- 206 题的 1,006 个计分锚点在材料中全部可见，没有被切行切掉。
- 集合题的成员全部可见：T5 334 个“方法–论文”对，T6 237 个，T7 231 个。
- 材料生成没有报错。

发现的问题与处理：

1. **3 道 T7 缺锚点**（T7-bccfce23、T7-6d4ffdbe、T7-4c4f6b77）：参考答案把 Informer、Autoformer 表中的基线记为“作者自己跑的”，却没有锚点。封闭世界的说明会把读者引向“没有说明”。为此补上了原文中作者交代自己搭建、设置基线的段落：Informer 第 302 行与第 306 行所在段落，Autoformer 第 972 行。题库已冻结，补充写在 `evidence.py` 的 `SUPPLEMENT` 中，不改参考答案。
2. **M-T14-patchtst-code 的金标准缺陷**：要点 a（“v2 只说代码将会公开”）在 PatchTST v2 的原文中找不到，任何一组都无法从原文答出。题库不改，判分时注明：这一点只要答出“没有给出自己的代码链接”即算对。
3. 另有 2 个要点没有锚点，都是否定性的说法（如 M-T14-code-stated 的要点 h：PatchTST、TiDE、CATS 正文里没有给出自己的代码链接）。有封闭世界说明和论文清单，读者可以答出，不算缺材料。

**改不了的局限**（论文中需说明）：

- 要点题的材料是按参考答案的锚点挑的，材料本身透露了哪些内容相关。例如 T14 只给了各论文提到代码的那一行，T18 只给了相关仓库的那几段。这正是“检索完美”这一上限的含义。集合类的自动题补了全库主表，透露得较少。
- 代码题只给锚点前后各 8 行。

**试跑**（运行名 `ref1-trial`、`ref1-trial2`、`ref1-trial3`，共 11 题，全部正常结束，没有触顶）：

| 题 | 结果 |
| --- | --- |
| T1-2a1bae7b、T3-8ed0609d、T5-6a6e5aec | 机械判分都是 1 |
| T8-2f5d4c30 | 四组“值–论文”与参考答案一致，只剩“是否断定某值正确”待判 |
| T7-4c4f6b77 | 补材料前 Autoformer 答成“没有说明”而扣分；补材料后三篇的来源全对 |
| M-T2-patchtst | 三个要点都答对 |
| M-T18-droplast-set、M-T16-cats-split | 与参考答案的要点基本一致 |
| M-T17-autoformer-split | 公式与文件位置都对，但把 ETT 的边界算错了（8640/12960/17280，应为 8640/11520/14400）；材料中的代码是对的 |
| M-T8-autoformer-etth1-336 | 用于验证经 stdin 传入的长提示语（见第 4 节），正常结束 |

单题输入最多 10.7 万 token，输出最多 3.5 万 token，最长用时 409 秒。

## 4 运行经过

| 时间（UTC） | 事件 |
| --- | --- |
| 15:51:55 | 启动（eval 提交 `4915b70`），206 题 |
| 15:56:20 | 完成 30 题后退出：在 M-T8-autoformer-etth1-336 上报 `OSError: Argument list too long: 'bwrap'` |
| 16:01:18 | 修复后续跑（eval 提交 `7cac49c`），已完成的 30 题不重答 |
| 约 16:20–16:25 | P 原文组的断网冒烟测试误发到本组独占的服务（:30000）：完成 1 次生成请求（思考级别 low，几百 token），第 2 次请求排队约 5 分钟后随会话超时取消，另有 3 次 `/v1/models` 查询。回答内容与 token 计数不受影响，这几分钟的用时略受干扰（D 的用时不进成本比较）。之后的冒烟与试跑改用 :30001 |

退出原因：提示语作为一个命令行参数传给沙箱，而单个参数的上限是 131,072 字节（Linux `MAX_ARG_STRLEN`），这道题的提示语有 143KB。

修复（提交 `7cac49c`）：

- 超过 100KB 的提示语改经 stdin 传入 pi，并另存为会话目录下的 `runs/<时刻>.prompt.txt`。
- pi 读入 stdin 后去掉首尾空白，没有消息参数时即作为提示语。读者提示语都以一个换行结尾，经 stdin 时只少这个换行。
- 已核对会话文件中的用户消息（142,854 个字符）与提示语去掉结尾换行后逐字相同。
- D 中走 stdin 的有 4 题（M-T8-autoformer-etth1-336、T3-986ad3a8、T3-c575544a、T3-34427f35），其余仍作为参数传入。C 组与写者组的行为不变。

## 5 判分

待运行结束后进行，流程与 C 相同（机械判分，送判条目打成判分包 `D-v1`，导入判定后出分）。判分包中需加入第 3 节第 2 条的说明。

## 6 结果

待补。

## 7 已知问题与待办

- 运行记录为 `dirty: true`（见第 2 节）。
- 修复前完成的 30 题都不在上述 4 题之中，提示语都作为参数传入，与修复后的规则一致；修复只影响这 4 道长题。
- 说明句缺引用要求（见第 2 节），D 不报引用可核对率。
- 判分完成后冻结结果，方式同 C。
