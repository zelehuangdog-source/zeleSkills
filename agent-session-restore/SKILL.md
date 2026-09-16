---
name: agent-session-restore
description: "重启电脑前后，存档/恢复 Warp 里所有正在跑的 agent 会话（Claude Code + Grok，含真实分屏布局）。每个 pane 自动识别自己跑的是哪个 agent。触发词：存档会话、恢复会话、重启前保存、重启后恢复、agent session snapshot、agent session restore、warp 分屏恢复、claude 会话恢复、grok 会话恢复。"
disable-model-invocation: true
tags:
  - warp
  - claude-code
  - grok
  - restore
visibility: private
---

# Agent 会话存档 / 恢复（Warp 分屏）

解决的问题：Warp 里常年开着十几个 tab、每个 tab 里还分了好几个 pane 跑 Claude Code 和 Grok，电脑重启后所有进程被杀掉，之前只能一个个手动回忆目录、重新 `--resume`。这套工具能把当前所有会话（连同真实的分屏布局）记录下来，重启后一键精确复原。

**每个 pane 各自识别自己跑的是哪个 agent**：claude 的格子用 claude 的存储和启动命令，grok 的格子用 grok 的，两种混在同一个 tab 里也能一起还原。

## 关键路径

- 存档脚本：`~/.claude/skills/agent-session-restore/agent-session-snapshot.py`
- 恢复脚本：`~/.claude/skills/agent-session-restore/agent-restore-sessions.sh`
- 存档目录（每份存档一个子目录，恢复时读取）：`~/.claude/skills/agent-session-restore/snapshots/<snapshot-id>/`
  - `manifest.txt`：这份存档要打开的 Warp tab-config 名称列表
  - `meta.txt`：第 1 行存档时间、第 2 行会话数、第 3 行 tab 数
- 保留策略：最多保留最近 10 份存档，更旧的连同其 tab-config 自动删除

## 执行流程

### 1. 询问用户要存档还是恢复（强制，禁止跳过）

用 AskUserQuestion 问用户这次是"存档"（重启前）还是"恢复"（重启后），二选一。

**⚠️ 这一步不能因为任何理由省略**，包括但不限于：
- 命令名本身叫 `agent-session-restore`，字面带"restore"——这只是 skill 的固定名称，不代表用户这次的意图就是恢复，历史上已经因为这个原因被跳过询问过一次。
- 命令参数（`command-args`）为空，看起来"没什么好问的"。
- 上下文里看起来"显然"是重启后（或重启前）的场景。

只要触发了本 skill，第一个动作永远是调用 AskUserQuestion，没有例外。

### 2a. 如果选存档

直接运行：

```bash
~/.claude/skills/agent-session-restore/agent-session-snapshot.py
```

把输出的汇总（记录了几个会话、生成了几个 tab-config、这份存档的 ID）原样展示给用户。**每次存档都是独立的一份历史**——带唯一的 snapshot-id（时间戳），最多保留最近 10 份，恢复时可以在这些历史存档里挑，不再是只能恢复最新的那一份。

### 2b. 如果选恢复（先列出、让用户选、再恢复）

分三步，不要直接闷头恢复最新的：

**第一步：列出所有存档**

```bash
bash ~/.claude/skills/agent-session-restore/agent-restore-sessions.sh --list
```

输出每行是一份存档：`snapshot-id ⭾ 存档时间 ⭾ N 个会话 ⭾ M 个 tab`，最新的在最上面。

**第二步：用 AskUserQuestion 让用户选要恢复哪一份 + 用哪个启动命令**

把最新的几份（AskUserQuestion 最多 4 个选项）作为候选，label 用「存档时间 + 会话数」，description 补上 snapshot-id。如果存档份数超过 4，告诉用户可以在「Other」里手输某个更早的 snapshot-id。

**同一个 AskUserQuestion 里再加一个问题问 claude 的启动命令**，二选一：

- `mc --code 启动`（默认）：claude 的 pane 用 `mc --code --dangerously-skip-permissions --resume <session_id>` 拉起
- `claude 命令启动`：claude 的 pane 改用 `claude --dangerously-skip-permissions --resume <session_id>`

这个选择**只作用于存档里 claude 的 pane**；grok 的 pane 始终用 `grok --always-approve --resume <session_id>`，不受影响。用户在对话里已经明确说了用哪个启动命令时，可以不再问这一题。

**第三步：用选中的 snapshot-id + 启动命令恢复**

```bash
bash ~/.claude/skills/agent-session-restore/agent-restore-sessions.sh <用户选中的 snapshot-id> <mc|claude>
```

（用户如果明确说"就恢复最新的"，可以直接用 `latest` 代替 snapshot-id，跳过一二步。）把恢复过程的输出展示给用户。

## 原理（如果要排查问题，看这里）

1. **会话精确定位**：Warp pane 里的进程，环境变量都有 `WARP_TERMINAL_SESSION_UUID`，跟 Warp 自己的状态库 `~/Library/Group Containers/2BBY89MBSN.dev.warp/Library/Application Support/dev.warp.Warp-Stable/warp.sqlite` 里 `terminal_panes.uuid` 字段是完全相同的值——用这个做精确匹配，不是靠猜。读取另一个进程环境变量用的是 `psutil`（`pip3 install --user psutil`，已装好）。
2. **两个 agent 的会话索引不同**（这是这套工具最容易踩的地方）：

   | | Claude Code | Grok |
   |---|---|---|
   | 存活会话登记 | `~/.claude/sessions/<pid>.json`（一个进程一个文件，含 `sessionId`/`cwd`/`startedAt`） | `~/.grok/active_sessions.json`（一张存活登记表，含 `session_id`/`pid`/`cwd`/`opened_at`） |
   | 进程自身环境变量里的 session id | 有 `CLAUDE_CODE_SESSION_ID` | **没有** `GROK_SESSION_ID`（只注入给子进程）→ `pid → session_id` 只能靠上面那张表 |
   | 会话落盘位置 | `~/.claude/projects/<编码目录>/<session-id>.jsonl` | `~/.grok/sessions/<URL 编码的 cwd>/<session-id>/`（**按 cwd 分目录**） |
   | 恢复命令 | `mc --code … --resume` / `claude … --resume` | `grok --always-approve --resume` |

   grok 会话按 cwd 落盘，所以恢复时 tab-config 的 `directory` 必须是存档时记录的原始 cwd，写错就 resume 不到。恢复脚本在开 tab 前会校验 `~/.grok/sessions/<编码 cwd>/<session-id>/` 是否还在：不在就删掉那条 `commands`（该格子降级成普通 shell）并打印警告，不会让你看到一个一启动就报 `session not found` 的 pane。
3. **真实分屏树**：同一个 sqlite 库的 `windows`/`tabs`/`pane_nodes`/`pane_branches`/`terminal_panes` 表记录了完整的窗口/tab/分屏结构，据此还原出跟原来一模一样的分屏布局（横切/竖切、嵌套层级）。
4. **恢复机制**：生成 Warp 的 Tab Config（`~/.warp/tab_configs/*.toml`），用 `open "warp://tab_config/<name>"` 非交互触发。**踩过的坑**：分屏的根节点判定规则是"文件里第一个 `[[panes]]` 条目"（源码 `warpdotdev/warp` 仓库 `app/src/tab_configs/tab_config.rs` 的 `resolve_pane_tree`），不是看 id 叫什么——写错顺序会静默退化成只开第一个 pane，不报错。
5. **只认 Warp 里的会话**：没有 `WARP_TERMINAL_SESSION_UUID` 环境变量的（比如跑在 IntelliJ 终端、iTerm、远程桌面工具里的会话）会被跳过，不会被错误地当成 Warp 会话处理。
6. **一个格子里有多个会话**：分两种，处理方式不同。
   - **同一个会话的多层壳**（`mc --code` 启动时 `mc` + `claude` 是两个进程、共享同一个 pane uuid）：登记表里只记 claude 本体，天然只算一个会话，不会重复计数。
   - **真正独立的多个会话**（先 Ctrl-Z 挂了 A 又开了 B；或在 grok 里嵌套起了 claude）：一个格子只有一个终端画面、塞不下两个。排序后（没被挂起的优先，其次启动更晚的）第一个回原格子，其余各自另开一个 tab——会话都不丢，只是回不到原来那个分屏位置。

## 已知局限

- 无法 100% 保证和原始布局分毫不差（Warp 自己的状态库写入有轻微延迟，极少数刚创建的 pane 可能还没同步进去）——这种情况下该会话会被单独恢复成一个不分屏的 tab，不会丢失，只是布局上退化。
- 只能恢复归属 Warp 窗口的会话，其他终端里跑的会话不在这套工具的管理范围内。
- pane 尺寸恢复不了、只能均分（Warp 的 tab-config 格式没有尺寸字段，硬限制）。
- 同一个格子里多出来的独立会话会被拆成额外的 tab（见原理第 6 条），那份存档的 tab 数会多于原来的 tab 数。
