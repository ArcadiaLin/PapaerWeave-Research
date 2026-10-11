# 草稿文件：大块内容经文件交给算子

状态：已同意（2026-10-11），待实现。涉及 Extract、MatrixConstruct、Commit；其余 Agent 算子在冒烟验证后再定。

## 1. 问题

T1 先导 pilot-1（`~/t1-runs/pilot-1`，停于 A3 第 5 个会话）暴露两个问题。

**写入成本中近一半是重交。** A3 全部会话的输出 token 按写入结果分：

| 去向 | 占比 |
| --- | --- |
| 被拒绝或被拦下、随后整份重交的写入调用 | 45% |
| 成功的写入 | 39% |
| 读取等其他工具 | 11% |
| 预演通过（之后原样再交） | 4% |
| 最终回复 | 1% |

原因是写入内容全部放在工具参数里：

- Extract 的每一行都是一个带键名的 JSON 对象，约 70 token。168 行的主表约 1.15 万 token。
- 校验发现几行引用格式不对，写者也只能把整份表重新生成一遍：同一份 168 行的表交了 3 次。
- Commit 的工具描述要求先预演、再带 `apply: true` 原样重交，一份 4000 token 的文档至少要生成两遍。

**大参数被客户端超时截断。** sglang 的 `qwen3_coder` 解析器把一个工具参数整段生成完才发出，期间连接上没有任何字节。pi 的空闲超时 `httpIdleTimeoutMs` 默认为 300 秒，到点即断开（`terminated`）。按约 80 到 110 token/秒的速度，单个参数超过约 2.5 万 token 就会失败。A0 一次写出整篇论文笔记时失败了 5 次。这一点在 T1 运行框架里单独修复（§9），本设计只保证工具参数不再变大。

## 2. 原则

**草稿是写者的，产物是服务端的。**

- 写者用自己的文件工具（pi 的 `write`、`edit`）在工作目录里写草稿；调用算子时只传路径与少量声明。
- 服务端解析并校验草稿。被拒时，报错指出草稿的文件与行号，写者就地修改那几行后，用同样的短参数再交。
- 通过后，服务端从解析后的内容重新生成产物文档并登记。写者怎么排版草稿，不影响产物的格式。

**这不改变写入契约。** 校验规则、引用覆盖、查重退回写者、有据层修订、解释层归属、`USED` 与 `_stale` 都不变。变的只是内容进入服务端的通道。

**引导只经工具描述与工具返回。** 符合"通用 Agent 经 MCP 使用系统"的设定：不改系统提示，不加专用工具。

## 3. 接口变化

| 算子 | 新参数 | 替代 | 保留 |
| --- | --- | --- | --- |
| Extract | `payload_file`：CSV 草稿的路径 | `payload.rows` | `payload.note`（行数为 0 时的说明）；小表仍可直接写 `payload.rows` |
| MatrixConstruct | `payload_file`：CSV 草稿的路径 | `payload.cells` | `payload.note`；小矩阵仍可直接写 `payload.cells` |
| Commit | `doc_file`：graph-doc YAML 草稿的路径 | `doc` | 小文档仍可直接写 `doc` |

`payload_file` 与 `payload.rows`（或 `payload.cells`）二选一，同时给出时拒绝（`format`）；`doc_file` 与 `doc` 同理。工具描述写明：超过约 20 行、或文档较长时用文件。

`params`、`inputs`、`title`、`abs` 仍直接写在参数里。它们是声明，一般只有几百 token。

## 4. 草稿格式

**Extract：CSV。** 表头是 `params.schema.fields` 中声明的字段，加上 `source`，列顺序不限：

```text
method,dataset,horizon,setting,mse,mae,source
method_0014,ETTm2,96,multivariate,0.255,0.339,exp_0015
method_0014,ETTm2,192,multivariate,0.281,0.340,exp_0015
```

- 每格按声明的类型解析：`number` 解析为浮点数，`integer` 解析为整数，`boolean` 只接受 `true` / `false`，`ref`、`string`、`enum[…]` 按原文字符串处理。空格视为未给出。
- 含逗号或引号的值按 CSV 规则加引号（Python `csv` 模块的默认方言）。
- 表头多出未声明的列，或缺少 `source`，整份拒绝。

**MatrixConstruct：CSV 长表。** 一格一行：

```text
row,col,value,basis,note
autoformer,etth1_96,0.449,art_0002#autoformer-etth1-96,
informer,etth1_96,,,"not reported in this paper"
```

- `value` 按 `params.cell.type` 解析，空格视为 `null`。
- `basis` 有多项时用 `;` 分隔。
- `row` 与 `col` 必须是 `params` 中声明的键。

**Commit：graph-doc YAML。** 内容与现在的 `doc` 参数完全相同。

解析后得到的 `payload`（或 `doc`）与直接写在参数里的形式一致，之后交给现有的校验。校验代码不需要知道内容来自文件。

## 5. 模板与报错

**模板。** Extract 与 MatrixConstruct 调用时只给 `params`、不给 `payload_file` 与 `payload` 时，返回 `status: template`，不写入：

```yaml
status: template
header: method,dataset,horizon,setting,mse,mae,source
example: <method id>,ETTh1,96,multivariate,0.375,0.402,<material id>::<section>::<start>:<end>
next: write the rows to a CSV file in your working directory with this header, then call again with payload_file
```

表头由服务端按声明生成，写者照着填，不用猜格式。

**报错带行号。** 现有校验报告的位置形如 `payload.rows[17].source`、`payload.cells[3].basis`、`nodes.$exp.FROM[0].locators`。内容来自文件时，服务端把这些位置换算成文件位置：

```yaml
status: rejected
errors:
- rule: reference
  at: tables/autoformer-t1.csv:19 (source)
  msg: source "material_fa42…::line::291:291" is not <material>::<section>::<start>:<end>
```

- CSV：第 $i$ 条记录对应它在文件中的行号（表头为第 1 行，引号内跨行的记录取起始行）。
- YAML：用 YAML 解析器记下的节点位置，把结构路径换算成行号，换算不到时退回结构路径。
- 一次列出全部错误，不在第一处出错时就停止，与现在相同。

工具描述给出固定的工作流程：先取模板；写草稿；用路径调用；被拒时只改报错列出的行，再用同样的参数调用。

## 6. 定稿与溯源

- **提交即定稿。** 校验通过后，产物文档由服务端从解析后的内容生成（与现在相同），写入材料根目录的 `artifacts/`。之后草稿再被修改，不影响已登记的产物。读者只看得到产物，看不到草稿。
- **幂等不变。** `artifact_key` 按解析后的 `payload` 计算，与内容来自文件还是参数无关。同一份草稿再交一次，返回已有的产物。
- **记下草稿。** 提交的 `input` 记录调用参数，加上草稿原文。提交的 `meta.draft` 记录草稿的路径与 SHA-256。评估写者行为时，可以看到每次交上来的完整内容（工作原则 4）。Commit 同理：`input` 为草稿原文，`meta.draft` 记录路径与哈希。

## 7. 路径

- 只接受写者工作目录内的路径：相对路径相对于工作目录；绝对路径必须落在工作目录之内。规范化后（解析 `..` 与符号链接）仍须在工作目录内，否则拒绝（`format`）。
- 不接受论文材料目录下的路径。草稿是写者自己的文件，不是材料。
- **工作目录由服务端决定**，写者无法自行声明：
  - 设置了 `E09_WORKDIR` 时用它（T1：写者工作目录在宿主机上的路径）。`E09_WORKDIR_ALIAS` 给出写者看到的同一目录（T1 沙箱中为 `/work`），以这个前缀开头的绝对路径按它换算。
  - 未设置时，用 MCP 服务进程的当前目录。pi 是否在工作区中启动 MCP 服务，实现时核实；不是的话，`make workspace` 生成的 MCP 登记里要写入 `E09_WORKDIR`。
- 单个草稿文件不超过 2 MB，超过时拒绝。

## 8. Commit：一次调用完成

现有实现中，`apply: true` 本来就会先预演；有阻塞项时返回 graph-plan、不写入，没有时直接提交。"先预演、再原样重交"只是工具描述规定的流程。改为：

- MCP 中 Commit 的 `apply` 默认值改为 `true`。工具描述写明：直接交；被拦下（`blocked`）就按报错修改草稿后再交；只想预览时传 `apply: false`。
- 查重候选、修订要求等阻塞项照常在写入之前退回写者，写入时的裁决仍由写者做出。
- 命令行（`python -m e09`）的默认值不变，仍需显式 `--apply`。

## 9. T1 运行框架的配套修复（不属于系统设计，一并记录）

- 沙箱内 pi 的设置加入 `httpIdleTimeoutMs: 1800000`，写入实验配置留档。
- MCP 服务的启动环境加入 `E09_WORKDIR`（写者工作目录在宿主机上的路径）与 `E09_WORKDIR_ALIAS=/work`。
- A0 会话结束后，记录笔记库中未提交的改动清单（写入 `sessions.jsonl`），然后丢弃这些改动，使两组对称：A3 中未经 Commit 的内容不进库；A0 中未经 git commit 的内容也不留给下一个写者。
- `sessions.jsonl` 增加每个会话的请求出错次数（`stopReason: error`）。会话前后的库版本已有记录，库没有变化的会话因此能直接看出来。

## 10. 验证

先跑单元测试，再跑冒烟测试。

**单元测试**

- CSV 与 YAML 草稿解析后，与直接写在参数里的等价内容得到相同的产物与 `artifact_key`；
- 类型解析与报错行号，包括引号内跨行的记录；
- 路径规则：越出工作目录、指向材料目录、符号链接越界、文件过大都被拒绝；
- 模板返回的表头与声明一致；
- Commit 的 `apply` 默认为 `true` 时，有阻塞项不写入，没有则提交。

**冒烟测试**（与 pilot-1 的同一槽位对照，A3 跑 writer-i3 读 Autoformer）

- 工具调用参数的大小：最大值与中位数；
- 被拒或被拦下后重交的输出 token 占比（pilot-1 为 45%）；
- 写者是否走文件路径：使用 `payload_file` / `doc_file` 的调用占比；
- 会话总时长与总输出 token。

冒烟结果只用于判断这条路是否可行，不计入评测。

## 11. 不在本次范围

- Check、Verify、Filter、Summarize、Generate 的草稿文件。Generate 的正文天然是 Markdown，最可能接着改。
- 产物的增量修改（对已登记产物追加行）。产物仍是一次形成、整体登记。
- 草稿格式之外的工具描述改写。只改涉及的三个算子的描述。
