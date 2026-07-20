---
name: claude-session-restore
description: "重启电脑前后，存档/恢复 Warp 里所有正在跑的 Claude Code 会话（含真实分屏布局）。触发词：存档会话、恢复会话、重启前保存、重启后恢复、claude session snapshot、claude session restore、warp 分屏恢复。"
disable-model-invocation: true
tags:
  - warp
  - claude-code
  - restore
visibility: private
---

# Claude Code 会话存档 / 恢复（Warp 分屏）

解决的问题：Warp 里常年开着十几个 tab、每个 tab 里还分了好几个 pane 跑 Claude Code，电脑重启后所有进程被杀掉，之前只能一个个手动回忆目录、重新 `--resume`。这套工具能把当前所有会话（连同真实的分屏布局）记录下来，重启后一键精确复原。

## 关键路径

- 存档脚本：`~/.claude/skills/claude-session-restore/claude-session-snapshot.py`
- 恢复脚本：`~/.claude/skills/claude-session-restore/claude-restore-sessions.sh`
- 存档目录（每份存档一个子目录，恢复时读取）：`~/.claude/skills/claude-session-restore/snapshots/<snapshot-id>/`
  - `manifest.txt`：这份存档要打开的 Warp tab-config 名称列表
  - `meta.txt`：第 1 行存档时间、第 2 行会话数、第 3 行 tab 数
- 保留策略：最多保留最近 10 份存档，更旧的连同其 tab-config 自动删除

## 执行流程

### 1. 询问用户要存档还是恢复（强制，禁止跳过）

用 AskUserQuestion 问用户这次是"存档"（重启前）还是"恢复"（重启后），二选一。

**⚠️ 这一步不能因为任何理由省略**，包括但不限于：
- 命令名本身叫 `claude-session-restore`，字面带"restore"——这只是 skill 的固定名称，不代表用户这次的意图就是恢复，历史上已经因为这个原因被跳过询问过一次。
- 命令参数（`command-args`）为空，看起来"没什么好问的"。
- 上下文里看起来"显然"是重启后（或重启前）的场景。

只要触发了本 skill，第一个动作永远是调用 AskUserQuestion，没有例外。

### 2a. 如果选存档

直接运行：

```bash
~/.claude/skills/claude-session-restore/claude-session-snapshot.py
```

把输出的汇总（记录了几个会话、生成了几个 tab-config、这份存档的 ID）原样展示给用户。**每次存档都是独立的一份历史**——带唯一的 snapshot-id（时间戳），最多保留最近 10 份，恢复时可以在这些历史存档里挑，不再是只能恢复最新的那一份。

### 2b. 如果选恢复（先列出、让用户选、再恢复）

分三步，不要直接闷头恢复最新的：

**第一步：列出所有存档**

```bash
bash ~/.claude/skills/claude-session-restore/claude-restore-sessions.sh --list
```

输出每行是一份存档：`snapshot-id ⭾ 存档时间 ⭾ N 个会话 ⭾ M 个 tab`，最新的在最上面。

**第二步：用 AskUserQuestion 让用户选要恢复哪一份**

把最新的几份（AskUserQuestion 最多 4 个选项）作为候选，label 用「存档时间 + 会话数」，description 补上 snapshot-id。如果存档份数超过 4，告诉用户可以在「Other」里手输某个更早的 snapshot-id。

**第三步：用选中的 snapshot-id 恢复**

```bash
bash ~/.claude/skills/claude-session-restore/claude-restore-sessions.sh <用户选中的 snapshot-id>
```

（用户如果明确说"就恢复最新的"，可以直接用 `latest` 代替 snapshot-id，跳过一二步。）把恢复过程的输出展示给用户。

## 原理（如果要排查问题，看这里）

1. **会话精确定位**：每个 Warp pane 里运行的 claude 进程，环境变量都有 `WARP_TERMINAL_SESSION_UUID`，跟 Warp 自己的状态库 `~/Library/Group Containers/2BBY89MBSN.dev.warp/Library/Application Support/dev.warp.Warp-Stable/warp.sqlite` 里 `terminal_panes.uuid` 字段是完全相同的值——用这个做精确匹配，不是靠猜。读取另一个进程环境变量用的是 `psutil`（`pip3 install --user psutil`，已装好）。
2. **真实分屏树**：同一个 sqlite 库的 `windows`/`tabs`/`pane_nodes`/`pane_branches`/`terminal_panes` 表记录了完整的窗口/tab/分屏结构，据此还原出跟原来一模一样的分屏布局（横切/竖切、嵌套层级）。
3. **恢复机制**：生成 Warp 的 Tab Config（`~/.warp/tab_configs/*.toml`），用 `open "warp://tab_config/<name>"` 非交互触发。**踩过的坑**：分屏的根节点判定规则是"文件里第一个 `[[panes]]` 条目"（源码 `warpdotdev/warp` 仓库 `app/src/tab_configs/tab_config.rs` 的 `resolve_pane_tree`），不是看 id 叫什么——写错顺序会静默退化成只开第一个 pane，不报错。
4. **只认 Warp 里的会话**：没有 `WARP_TERMINAL_SESSION_UUID` 环境变量的（比如跑在 IntelliJ 终端、iTerm、远程桌面工具里的 claude 进程）会被跳过，不会被错误地当成 Warp 会话处理。
5. **同一个 pane 里有挂起的旧任务**：如果用户 Ctrl-Z 挂起过一个 claude、又在同一个 pane 里开了新的，两个进程会有相同的 `WARP_TERMINAL_SESSION_UUID`——脚本会保留没被挂起的那个，丢弃被挂起的。

## 已知局限

- 无法 100% 保证和原始布局分毫不差（Warp 自己的状态库写入有轻微延迟，极少数刚创建的 pane 可能还没同步进去）——这种情况下该会话会被单独恢复成一个不分屏的 tab，不会丢失，只是布局上退化。
- 只能恢复归属 Warp 窗口的会话，其他终端里跑的 claude 不在这套工具的管理范围内。
- pane 尺寸恢复不了、只能均分（Warp 的 tab-config 格式没有尺寸字段，硬限制）。
