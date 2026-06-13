---
name: sync-frontend
description: 将后端 API 设计同步给前端 Claude Code session。当用户说"同步前端"、"发给前端"时使用。
---

# sync-frontend

将后端 API 设计同步给前端 Claude Code session。从当前对话中提取需求背景和完整 API 契约，组装为可直接粘贴给前端的 prompt。

## 第一步：提取并结构化信息

从当前对话上下文中提取以下内容：

**需求背景**：
- 本次需求要解决什么问题
- 业务上下文（涉及哪个模块、什么场景）
- 关键的设计决策和原因

**API 契约**（对每个接口都提取完整信息）：
- HTTP Method + URL
- Request 完整结构（字段名、类型、是否必填、说明）
- Response 完整结构（字段名、类型、说明）
- 枚举字段的所有可选值及含义
- 错误码及对应含义
- 边界说明（空值处理、默认行为、特殊逻辑）
- 分页约定（如有）

如果对话中信息不完整（比如缺少某些字段的类型或枚举值），向用户询问补全，不要猜测。

## 第二步：询问前端行为模式

使用 AskUserQuestion 工具，**multiSelect: true**：

问题："前端 session 收到后应该怎么做？（可多选，按顺序执行）"

选项：
1. **先澄清** — 提示词会要求前端先用 /clarify 与用户确认理解是否正确、有无疑问
2. **设计示例 HTML UI 界面** — 提示词会要求前端先输出一个纯 HTML 的页面骨架/交互原型，用户确认后再写正式代码
3. **直接实现** — 提示词直接要求前端开始编写 API hook、TypeScript 类型定义和页面组件

组合规则：
- 选了"直接实现"则忽略其他选项，直接生成实现类 prompt
- 选了"先澄清" + "先设计 UI"，prompt 中按顺序要求：先 clarify → 再出 UI 原型 → 最后实现
- 单选"先澄清"或"先设计 UI"，prompt 中只包含对应步骤 + 最终实现

## 第三步：组装提示词

### 共享头部

```
## 需求背景

{提取的需求背景}

## 后端 API 契约

{完整的 API 契约，包含所有接口}

## 你的任务
```

### 任务段：先澄清（如果选了）

```
### 第一步：澄清

请先阅读以上 API 契约，然后使用 /clarify 对以下维度进行澄清：
- 你对接口的理解是否有疑问
- 页面交互上有哪些不确定的点（如加载态、空态、错误态）
- 数据展示上有哪些需要确认的（如排序、筛选、分页交互）

澄清完毕后再进行下一步。
```

### 任务段：先设计 UI（如果选了）

```
### {第N步}：设计 UI 原型

基于 API 契约，设计一个纯 HTML 的页面骨架（不需要接入真实数据）：
- 展示页面的整体布局和核心交互
- 标注每个区域对应哪个 API / 哪些字段
- 包含关键的交互状态（加载中、空数据、错误）

HTML 文件输出到本需求文档同级目录下（即 obsidian/工程迭代/{工程名}/{需求名}/ui-prototype.html）。
输出后用 `open` 命令自动在浏览器中打开，然后等待我确认，确认后再进行下一步。
```

### 任务段：实现（始终作为最后一步）

```
### {第N步}：实现

基于以上 API 契约，开始实现前端代码：
1. 在 src/api/types.ts 中定义 TypeScript 类型（Request/Response）
2. 在 src/api/ 下创建对应的 API hook（遵循项目已有的 useXxx 模式）
3. 实现页面组件，接入 API hook

注意：
- 遵循项目的 CLAUDE.md 规范
- 列表筛选/分页状态同步到 URL
- 颜色/间距使用 CSS Variables
- 用户可见文案使用中文
```

### 组装规则

- 选了"直接实现" → 只输出共享头部 + 实现段
- 选了"先澄清" → 共享头部 + 澄清段（第一步） + 实现段（第二步）
- 选了"先设计 UI" → 共享头部 + UI 段（第一步） + 实现段（第二步）
- 选了"先澄清" + "先设计 UI" → 共享头部 + 澄清段（第一步） + UI 段（第二步） + 实现段（第三步）

步骤编号根据实际选中的数量动态生成。

## 第四步：保存文件

将完整的提示词保存到 Obsidian：

路径规则：`/Users/huangzele/Documents/obsidian_repo/工程迭代/{工程名}/{需求名}/sync-frontend-{日期}.md`

- **工程名**：从当前上下文推断（如涉及 archsafe_serve、arch-sight 等）。如果不确定，询问用户。
- **需求名**：从当前上下文推断（如"耦合检测"、"标签管理"）。如果不确定，询问用户。
- **日期**：当前日期，格式 `YYYYMMDD`

目录不存在时自动创建。

文件内容格式：

```markdown
---
title: "sync-frontend: {需求名}"
date: {当前日期 YYYY-MM-DD}
tags: [sync-frontend, {工程名}]
mode: {clarify/ui-first/implement/clarify-then-ui}
---

{完整的提示词内容}
```

## 第五步：输出 + 复制到剪贴板

1. **组装剪贴板内容**，格式为：
   ```
   读取 {文件绝对路径} 并按其中的任务要求执行
   ```

2. **使用 Bash 执行 pbcopy** 将上述内容复制到剪贴板

3. **生成结果预览 HTML 并打开**：

   在需求文档同级目录下生成 `sync-frontend-preview.html`，内容为：

   ```html
   <!DOCTYPE html>
   <html lang="zh">
   <head>
     <meta charset="UTF-8">
     <title>sync-frontend 结果预览</title>
     <style>
       body { font-family: -apple-system, sans-serif; max-width: 900px; margin: 40px auto; padding: 0 20px; line-height: 1.6; color: #333; }
       .meta { background: #f0f4f8; border-radius: 8px; padding: 16px 20px; margin-bottom: 24px; }
       .meta-label { font-size: 13px; color: #666; margin-bottom: 4px; }
       .meta-value { font-family: monospace; font-size: 14px; word-break: break-all; }
       hr { border: none; border-top: 1px solid #e2e8f0; margin: 24px 0; }
       pre { background: #1e293b; color: #e2e8f0; padding: 16px; border-radius: 8px; overflow-x: auto; font-size: 13px; }
       code { background: #f1f5f9; padding: 2px 6px; border-radius: 4px; font-size: 13px; }
       h2 { border-bottom: 2px solid #3b82f6; padding-bottom: 8px; }
       h3 { color: #1e40af; }
     </style>
   </head>
   <body>
     <h1>sync-frontend 结果预览</h1>
     <div class="meta">
       <div class="meta-label">给前端的提示词已经封装到：</div>
       <div class="meta-value">{文件绝对路径}</div>
     </div>
     <div class="meta">
       <div class="meta-label">你当前剪贴板的内容是：</div>
       <div class="meta-value">{剪贴板那句 prompt}</div>
     </div>
     <hr>
     {将完整文件内容（不含 frontmatter）转换为 HTML 格式展示，保留 Markdown 的结构层次}
   </body>
   </html>
   ```

   生成后用 `open` 命令在浏览器中打开。

## 注意事项

- API 契约中的代码示例使用 JSON 格式展示 Request/Response
- 枚举值必须列举完整，不能遗漏
- 如果后端有"前端不需要感知"的内部逻辑，在契约中注明（如"detectId 为空时后端自动查最近一次，前端无需处理"）
- 提示词语言：中文描述 + 英文代码/字段名
