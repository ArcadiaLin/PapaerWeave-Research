# PaperWeave

项目正在推进中...

## 概览

PaperWeave 研究的问题是：**许多互不协调的 Agent 长期往同一个库里写论文派生知识，
这个库怎样才不退化，使后来的读者仍能找到、信任并在其上继续工作。** 写入者可能是
不同人的 Agent、不同项目，或同一个人几个月里上下文互不相通的大量 session；库是它们
之间唯一的通道。单个 Agent 在一个项目里复用自己的产物不在此列，那里文件加 Git 可能
已经够用。

PaperWeave 是经 MCP 提供给通用 Agent 的中间件，对每次写入施加身份、契约、来源与版本
约束。它借用并改造经典机制：实体解析、provenance、值并存与过时提示、数据版本管理。
库不判断谁对，只负责可问责：有据层的记录（论文自述的实验、结果、主张）可以对照原文
核对，有分歧时回到锚点修订并保留历史；解释层的判断与产物带着来源并存。语义判断由
外部 Agent 做，中间件负责校验、持久化与记录，内部不做 LLM 推理。

评测检验一个可证伪的假设：没有这些约束时，共享积累会随写入者和写入量增长而退化。
基线包括文件加 Git、RAG，以及同一 schema 的裸 Neo4j。属性图与 Cypher 是当前的实现
基础；系统是现有原型，部分机制仍在实现，评测方案仍在商定。

## 从哪里了解这个研究

- [`AGENTS.md`](AGENTS.md)：当前研究方向、挑战、设计边界、工程现状与评测的权威表述。
- [`paper/narrative-draft.md`](paper/narrative-draft.md)：论文叙事草稿（动机、挑战、
  贡献与章节大纲）。
- [`docs/designs/v2/evaluation_draft.md`](docs/designs/v2/evaluation_draft.md)：评测设计。
- [`docs/discussions/2026-10-10-challenges-and-classical-mechanisms.md`](docs/discussions/2026-10-10-challenges-and-classical-mechanisms.md)：
  挑战与经典机制的对照、分歧的分层处理、现有工程的复用。
- [`docs/designs/v2`](docs/designs/v2)：详细系统设计（数据模型、Commit 契约、算子、
  版本接口、项目视图）。
- `references/`：外部材料；`references/refs.bib` 是论文元数据的跟踪来源。
- `system/`（包 `paperweave`）与 `packages/`（`graph-doc`、`graph-vc` 等）：原型实现；
  `eval/`（包 `pweval`）：评测（T1 的运行框架与测量），与系统互不导入。

## Setup

```bash
make setup     # 建共享 .venv（Python 3.12）+ 装 nbstripout 的 git 过滤器
make lab       # 启动 JupyterLab
make verify    # 仓库级自检：主线阶段在无第三方依赖的隔离环境中仍能跑通
```

`make setup` 每个 clone 跑一次即可。它包含 `nbstripout --install`——过滤器命令写在
本机的 `.git/config`（不进版本管理），哪些文件走过滤器写在跟踪的 `.gitattributes`。
两边缺一不可，忘了装会导致带 cell 输出的 notebook 被提交；补救入口是 `make hooks`。

`make hooks` 还会设 `filter.nbstripout.extrakeys`，额外剥掉 `metadata.language_info.version`
——JupyterLab 会把本机的 Python 补丁版号写进 notebook，换机器就产生一行无意义的 diff。
这一项必须写进 git config，命令行的 `--extra-keys` 只对当次调用生效。

仓库根是一个 uv workspace，主线实验都是它的成员，共用一份 `uv.lock` 和一个 `.venv`。
`experiments/p4a`（历史项目，依赖冲突）与所有 TypeScript 目录不在其中。
请在仓库根目录运行 setup，不要在 workspace 成员目录中运行 `uv sync`。
