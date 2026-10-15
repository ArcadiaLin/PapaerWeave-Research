# PaperWeave 评测（包 `pweval`）

原 `experiments/t1`（包 `t1`），2026-10-15 迁到 `eval/`。评测不导入被测系统（`system/`，包 `paperweave`），只经它的
命令行与 MCP 入口（子进程）、Cypher 读与文件接触它（evaluation_draft §10.1，`tests/test_imports.py`）。

## T1：多写者积累时间线

评测设计见 [`docs/designs/v2/evaluation_draft.md`](../docs/designs/v2/evaluation_draft.md) §4；先导配置在
[`config/pilot-ltsf.yml`](config/pilot-ltsf.yml)，语料选择见
[`docs/decisions/2026-10-10-t1-pilot-corpus.md`](../docs/decisions/2026-10-10-t1-pilot-corpus.md)。

| 模块 | 作用 |
| --- | --- |
| `pweval.replay` | 在内存中按顺序重放入库文档（与 Commit 相同的写入路径），得到图状态；不需要数据库 |
| `pweval.a0_seed` | 把一个图状态渲染成 A0（文件 + git）的笔记库：每个对象一个 Markdown 文件，相对链接，不含 A3 的 id |
| `pweval.sandbox` | 一次写者会话在 bubblewrap 沙箱中运行默认配置的 pi：断网，只挂载本写者的工作目录、论文（只读）与 A0 笔记库；A3 的 MCP 服务在沙箱外按登录身份启动 |
| `pweval.bridge` | 沙箱内外经 unix socket 的字节转发（大模型服务、MCP 服务），只用标准库 |

生成 A0 的检查点 0（种子与锚点），在仓库根目录执行：

    uv run python -m pweval.a0_seed <输出目录> --git

输出目录下是 `store/`（笔记库，`--git` 时初始化为 git 仓库，提交作者 `seed`，标签 `checkpoint-0`）。
同一组入库文档渲染两次，结果逐字节相同。
