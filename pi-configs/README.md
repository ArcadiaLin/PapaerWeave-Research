# pi 启动配置

每个子目录是一套配置，包含自己的 system prompt、extensions 和 session 记录：

```text
pi-configs/<版本>/
├── start.sh
├── SYSTEM.md
├── extensions/       # 在这里开发该配置的扩展，纳入 Git
└── sessions/         # pi 自动创建并持久化对话，Git 忽略
```

在仓库根目录启动：

```bash
./pi-configs/default/start.sh
```

`default/SYSTEM.md` 初始内容取自本机 `@earendil-works/pi-coding-agent 0.85.1`
的原版默认 system prompt，使用默认的 `read/bash/edit/write` 工具组合。
这是可编辑的静态副本，包含本机 pi 文档路径；不会随 pi 升级或工具选择自动更新。

编辑 `default/SYSTEM.md`，下次启动时即使用新的内容。它替换 system prompt
的主体；工作目录、项目 `AGENTS.md` 和 skills 仍由 pi 动态追加。

模型、登录态和内置工具配置沿用本机 pi。启动脚本保留调用时的工作目录，
用 `--session-dir` 将对话写入当前配置的 `sessions/`，并透传额外参数，例如：

```bash
./pi-configs/default/start.sh --thinking high
./pi-configs/default/start.sh --continue
./pi-configs/default/start.sh --resume
```

`--continue` 继续该配置下、当前工作目录的最近会话，`--resume` 打开会话选择器。
这些默认路径可由显式传入的 pi 参数覆盖。

扩展放在该配置的 `extensions/` 中，可以是 `my-extension.ts`，
也可以是 `my-extension/index.ts`。启动脚本使用 `--no-extensions --extension <配置目录>`，
按 pi 本地资源包规则加载该目录中的扩展；全局和项目 `.pi/extensions/`
不会自动加载。需要额外扩展时可以显式传入 `-e /path/to/extension.ts`。
修改或新增配置内扩展后，在 pi 中用 `/reload` 重新加载。

配置目录也支持 pi 资源包约定的 `skills/`、`prompts/` 和 `themes/`；
这些资源会额外加载，原有全局和项目资源仍按 pi 的规则发现。

新增配置时，创建新目录及其中的 `extensions/`（没有扩展时也保留空目录），
复制 `default/start.sh`、`default/SYSTEM.md` 和需要的扩展源码；不要复制 `sessions/` 历史记录。
启动脚本会根据自身位置选择新配置的资源和会话目录。

## no-write-bash

`no-write-bash/` 在通用结构之上做了两处调整：

- 启动脚本加 `--exclude-tools write,bash`，禁用内置的 write 和 bash 工具
  （保留 read、edit），`SYSTEM.md` 也相应改写，可继续自由编辑。
- 启动脚本设置 `PI_CODING_AGENT_DIR=<配置目录>/agent`，使模型配置来自该目录下
  自己的 `models.json`（纳入 Git）。pi 没有单独的 models.json 路径参数，只能整体
  重定向 agent 目录；因此 `agent/` 下的 `auth.json`、`settings.json`、`trust.json`
  和 `skills/` 是指向 `~/.pi/agent/` 同名条目的符号链接，登录态、设置和全局 skills
  仍沿用本机 pi。这些符号链接和 pi 生成的缓存（`models-store.json`、`npm/` 等）
  被 `.gitignore` 排除，只有 `models.json` 入库。

## paper-extract

`paper-extract/` 是 e08 论文抽取 Agent 的专用配置，设计见
[extraction-plan](../docs/experiments/e08/extraction-plan.md) 第 3 节。与通用结构相比：

- 启动脚本加 `--no-builtin-tools`，禁用全部内置工具（read、bash、edit、write、grep、find、ls）；
  Agent 只能使用 `extensions/` 中注册的专用抽取工具。
- 加 `--no-context-files --no-skills --no-prompt-templates`，不加载仓库 `AGENTS.md`、
  全局 skills 和 prompt 模板，避免把面向编码的指令带进抽取会话。
- `agent/` 的做法与 `no-write-bash/` 相同：自带 `models.json`，其余条目为指向 `~/.pi/agent/`
  的符号链接。
- `SYSTEM.md` 是初稿，工具列表待工具实现后补上。
- `GUIDE_ZH.md` 是面向 Agent 的数据模型指南，经 `--append-system-prompt` 追加在 `SYSTEM.md` 之后；
  定义以 `docs/designs/graph_model.md` 为准，文件头注明对应版本，数据模型修改后需同步。

## PaperWeave 不在这里

PaperWeave 的算子经 MCP 提供给默认配置的 pi，不需要专门的启动配置：`python -m paperweave.workspace <目录>` 在仓库外
生成一个只含 `.pi/mcp.json` 的实验目录，在其中直接运行 `pi`，见 `system/README.md`。
