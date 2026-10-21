---
name: pi-extension-dev
description: 开发、调试 pi (pi-coding-agent) 的 extension，或查阅 pi 的配置与 MCP 用法时使用。评测用的 pi 配置不在这里，由 eval 生成（见文末）。
---

# pi Extension 开发

本 skill 不重复讲解如何开发 extension——本仓库内有 pi 上游源码的 clone（`references/repos/pi`，gitignored），自带完整文档，开发时**直接引用这些文档**作为权威依据，不要凭记忆写 API。

使用前确认 clone 与本机 pi 版本一致：`git -C references/repos/pi log -1` 对比 `pi --version`，落后就 `git -C references/repos/pi pull`（远程是上游 `earendil-works/pi`）。本机 pi 是托管安装，安装包自带同版本的文档与示例，位于 `~/.pi/agent/install/releases/<版本>/node_modules/@earendil-works/pi-coding-agent/`（`docs/`、`examples/`），clone 缺失或未同步时用它（2026-10-15 迁机后 clone 尚未恢复）。

## 权威文档（开发时必读）

主文档（extension API、事件、工具、UI）：

- `references/repos/pi/packages/coding-agent/docs/extensions.md`

配套文档（按需查阅）：

- `references/repos/pi/packages/coding-agent/docs/mcp.md` — MCP 服务器配置（`pi mcp` 命令、`mcp.json`、exposure）
- `references/repos/pi/packages/coding-agent/docs/codemode.md` — codemode 工具：模型写 JS 脚本在沙箱中调用其他工具
- `references/repos/pi/packages/coding-agent/docs/custom-provider.md` — 自定义模型 provider
- `references/repos/pi/packages/coding-agent/docs/packages.md` — 把 extension 打包成 npm/git 包分发
- `references/repos/pi/packages/coding-agent/docs/tui.md` — TUI 组件 API（自定义渲染、overlay）
- `references/repos/pi/packages/coding-agent/docs/rpc.md` — RPC 模式与 extension UI 协议（细分主题见 rpc-commands.md、rpc-extension-ui.md）
- `references/repos/pi/packages/coding-agent/docs/session-format.md` — Session 存储与 SessionManager
- `references/repos/pi/packages/coding-agent/docs/keybindings.md` — 快捷键 id 列表
- `references/repos/pi/packages/coding-agent/docs/skills.md`、`slash-commands.md`、`configuration.md` — skills / 斜杠命令 / 配置

## 示例库

`references/repos/pi/packages/coding-agent/examples/extensions/` 下有 80 个可运行示例（hello、todo、permission-gate、plan-mode、ssh、subagent 等）。写新 extension 时优先找相近示例参考，不要从零发明结构。

## 1.0 起的新 API 面（extensions.md 中有详解）

- `pi.registerMcpServer()` / `pi.unregisterMcpServer()` / `pi.getMcpServers()`，及 `mcp_servers_change` 事件——extension 可注册会话级 MCP 服务器
- 工具 `exposure` 分级（`codemode` / `deferred` / callable）与 `namespace` 分组，控制工具对模型和 codemode 脚本的可见性
- 工具声明 `outputSchema` 并返回 `structuredContent` 后，codemode 脚本等程序化调用方能拿到结构化结果
- 工具 `annotations`（`readOnlyHint` 等 MCP 语义），供权限类 extension 做审批判断

## 加载与测试位置

- 仓库不再保留 `pi-configs/`（2026-10-21 删除：评测配置由 eval 生成，其余配置版本已无用途）。需要开发扩展时，再与用户商定放在哪里。
- 测试扩展：`pi --no-extensions -e ./path.ts`（`--no-extensions` 关掉自动发现，显式的 `-e` 仍加载）；`--session-dir` 把会话放到别处，免得混进本机记录。
- 不要改全局 `~/.pi/agent/` 的现役配置；评测框架从这里读模型配置（待移入 `eval/config/`）。
- 扩展支持 `/reload`，包括重新发现新增的扩展文件。

## 评测用的 pi 配置不在这里

正式运行与参照组的 pi 配置由 `eval/src/pweval/harness/sandbox.py` 的 `prepare()` 在每个会话的沙箱 `HOME` 中生成（`models.json`、`settings.json`、`mcp.json`），条件取自 `eval/config/*.yml` 的 runner 段；各组的差别在 `Arm`（`sandbox.py`、`timeline.py`、`readers.py`、`refs.py`）。要改评测条件就改这些，并按 AGENTS.md 先与用户确认；不要另建启动配置。写者与读者都是默认配置的 pi：不改系统提示，不加扩展。
