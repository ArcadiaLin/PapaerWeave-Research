# PaperWeave 评测（包 `pweval`）

原 `experiments/t1`（包 `t1`），2026-10-15 迁到 `eval/`。评测不导入被测系统（`system/`，包 `paperweave`），只经它的
命令行与 MCP 入口（子进程）、Cypher 读与文件接触它（evaluation_draft §10.1，`tests/test_imports.py`）。

## T1：多写者积累时间线

评测设计见 [`docs/designs/v2/evaluation_draft.md`](../docs/designs/v2/evaluation_draft.md) §4；先导配置在
[`config/pilot-ltsf.yml`](config/pilot-ltsf.yml)，语料选择见
[`docs/decisions/2026-10-10-t1-pilot-corpus.md`](../docs/decisions/2026-10-10-t1-pilot-corpus.md)。

代码分三层（`src/pweval/`），依赖只向下：`harness` 与 `measure` 都可以用 `protocol`，`measure` 不用 `harness`；
层的边界由 `tests/test_imports.py` 检查。

| 层 | 模块 | 作用 |
| --- | --- | --- |
| `protocol`：共享约定，只用标准库与 pyyaml | `config` | 一次运行的配置：先导配置加上运行的覆盖 |
| | `versions` | 论文版本与版本事件 |
| | `probes` | 探针数据：有效范围、检查点时的金标准、金标准与原文的核对 |
| | `snapshot` | 检查点快照的格式与读取 |
| | `source_tables` | 原文结果表的索引 |
| `harness`：运行框架，可以连库、起子进程 | `run` | 一次运行：建立各组起点，调度写者会话，在检查点导出快照、让读者作答 |
| | `sandbox` | 一次 pi 会话在 bubblewrap 沙箱中运行：断网，只挂载本写者的工作目录、论文（只读）与 A0 笔记库；A3 的 MCP 服务在沙箱外按登录身份启动 |
| | `bridge` | 沙箱内外经 unix socket 的字节转发（大模型服务、MCP 服务），只用标准库 |
| | `mcp_client`、`seeding`、`skills` | 经系统的 MCP 入口检入种子产物、为写者放置 skill |
| | `export` | 检查点快照的导出（A3 经 Cypher，A0 经 git 标签） |
| | `a0_seed` | 把 A3 检查点 0 的快照渲染成 A0（文件 + git）的笔记库 |
| | `readers` | 读者探针：在检查点上由读者 Agent 作答，记录回答与轨迹 |
| `measure`：测量，只读快照，不连库 | `health` | 库健康度 |
| | `grade` | 探针判分 |

常用入口（在仓库根目录执行）：

    uv run python -m pweval.harness.run <运行名> [--config …]             # 一次运行
    uv run python -m pweval.harness.readers <运行名> --checkpoint K        # 单独让读者作答
    uv run python -m pweval.measure.health <运行名> --checkpoint K         # 库健康度
    uv run python -m pweval.measure.grade <运行名>                         # 判分
    uv run python -m pweval.harness.export <运行名>                        # 试跑：导出 A3 当前状态，供 --at-head 读取

生成 A0 的检查点 0（种子与锚点），在仓库根目录执行：

    uv run python -m pweval.harness.a0_seed <输出目录> --git

输出目录下是 `store/`（笔记库，`--git` 时初始化为 git 仓库，提交作者 `seed`，标签 `checkpoint-0`）。
同一组入库文档渲染两次，结果逐字节相同。
